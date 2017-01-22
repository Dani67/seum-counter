import copy
from datetime import datetime, timedelta
import functools
import math
import random

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db import IntegrityError
from django.db.models import Prefetch, Count
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import ugettext as _, get_language

import arrow
from babel.dates import format_timedelta, format_datetime
from graphos.renderers import gchart
from graphos.sources.model import ModelDataSource
from graphos.sources.simple import SimpleDataSource

from counter.models import *
from counter.utils import parseSeumReason


# Number of counters displayed on the home page's best seumeurs graph
bestSeumeursNumber = 15


@login_required
def index(request):
    # Used later to keep track of the maximum JSS
    lastResets = []
    no_seum_delta = timedelta.max

    # First select our counter
    try:
        myCounter = Counter.objects.get(user__id=request.user.id)
        myLastReset = Reset.objects.select_related('who').filter(counter=myCounter).order_by('-timestamp').first()

        if myLastReset is None:
            # This person never had the seum
            myCounter.lastReset = Reset()
            myCounter.lastReset.delta = no_seum_delta
            myCounter.lastReset.noSeum = True
        else:
            myCounter.lastReset = myLastReset
            myCounter.lastReset.noSeum = False
            if myCounter.lastReset.who is None or myCounter.lastReset.who.id == myCounter.id:
                myCounter.lastReset.selfSeum = True
            else:
                myCounter.lastReset.selfSeum = False
            likesMe = list(Like.objects.select_related('liker').filter(reset=myCounter.lastReset))
            myCounter.likeCount = len(likesMe)
            if myCounter.likeCount > 0:
                myCounter.likersString = ", ".join([like.liker.trigramme for like in likesMe])

        myCounter.lastReset.formatted_delta = arrow.Arrow.fromdatetime(myCounter.lastReset.timestamp).humanize(locale=get_language())

    except Counter.DoesNotExist:
        return HttpResponseRedirect(reverse('login'))

    # Building data for counters display
    counters = Counter.objects.prefetch_related(
        'resets__likes',
        Prefetch(
            'resets',
            queryset=Reset.objects.prefetch_related('who', Prefetch('likes', queryset=Like.objects.select_related('liker'))).order_by('-timestamp'),
            to_attr='lastReset'
        )
    )
    for counter in counters:
        # Only the last reset is displayed
        lastReset = list(counter.lastReset)
        if len(lastReset) == 0:  # This person never had the seum
            counter.lastReset = Reset()
            counter.lastReset.delta = no_seum_delta
            counter.lastReset.noSeum = True
            counter.lastReset.likes_count = -1
            counter.CSSclass = "warning"
        else:  # This person already had the seum
            counter.lastReset = lastReset[0]
            # To display the last seum we have to know if it is self-inflicted
            if counter.lastReset.who is None or counter.lastReset.who == counter:
                counter.lastReset.selfSeum = True
            else:
                counter.lastReset.selfSeum = False
            # Now we compute the duration since the reset
            counter.lastReset.noSeum = False
            counter.lastReset.delta = datetime.now(
            ) - counter.lastReset.timestamp.replace(tzinfo=None)
            # Defining CSS attributes for the counter
            counter.CSSclass = 'primary' if counter == myCounter else 'default'
            # Computing the total number of likes for this counter
            likesMe = list(counter.lastReset.likes.all())
            counter.lastReset.likes_count = len(likesMe)
            counter.alreadyLiked = myCounter in likesMe
            if counter.lastReset.likes_count > 0:
                counter.likersString = ", ".join([like.liker.trigramme for like in likesMe])

        counter.lastReset.formatted_delta = format_timedelta(
            counter.lastReset.delta, locale='fr', threshold=1)
        counter.isHidden = 'hidden'

    if myCounter.sort_by_score:
        # Now we sort the counters according to a reddit-like ranking formula
        # We take into account the number of likes of a reset and recentness
        # The log on the score will give increased value to the first likes
        # The counters with no seum have a like count of -1 by convention
        sorting_key = lambda t: - (math.log(t.lastReset.likes_count + 2) / (1 + (t.lastReset.delta.total_seconds()) / (24 * 3600)))
        counters = sorted(counters, key=sorting_key)
    else:
        counters = sorted(counters, key=lambda t: + t.lastReset.delta.total_seconds())

    # Timeline graph
    resets = Reset.objects.select_related('who', 'counter').filter(timestamp__gte=timezone.now() - timedelta(days=1))
    if resets.count() == 0:
        noTimeline = True
        line_chart = None
    else:
        noTimeline = False
        for reset in resets:
            reset.timestamp = {
                'v': reset.timestamp.timestamp(),
                'f': "Il y a " + format_timedelta(datetime.now() -
                                                  reset.timestamp.replace(
                                                      tzinfo=None),
                                                  locale='fr', threshold=1)
            }
            if (reset.who is None or
                    reset.who.id == reset.counter.id):
                reset.Seum = {'v': 0,
                              'f': reset.counter.trigramme +
                              " : " + reset.reason}
            else:
                reset.Seum = {'v': 0,
                              'f': reset.who.trigramme + ' à ' +
                              reset.counter.trigramme +
                              " : " + reset.reason}
        line_data = ModelDataSource(resets, fields=['timestamp', 'Seum'])
        line_chart = gchart.LineChart(line_data, options={
            'lineWidth': 0,
            'pointSize': 10,
            'title': '',
            'vAxis': {'ticks': []},
            'hAxis': {
                'ticks': [
                    {'v': (datetime.now() - timedelta(days=1)
                           ).timestamp(), 'f': 'Il y a 24 h'},
                    {'v': datetime.now().timestamp(), 'f': 'Présent'}
                ]
            },
            'legend': 'none',
            'height': 90
        })

    # Graph of greatest seumers
    seumCounts = []
    for counter in counters:
        seumCounts.append([counter.trigramme, Reset.objects.filter(
            counter=counter).count()])
    if (len(seumCounts) == 0):
        noBestSeum = True
        best_chart = None
    else:
        seumCounts.sort(key=lambda x: -x[1])
        noBestSeum = False
        seumCounts.insert(0, ['Trigramme', 'Nombre de seums'])
        best_data = SimpleDataSource(seumCounts[:bestSeumeursNumber])
        best_chart = gchart.ColumnChart(best_data, options={
            'title': '',
            'legend': 'none',
            'vAxis': {'title': 'Nombre de seums'},
            'hAxis': {'title': 'Trigramme'},
        })

    # Graph of seum activity
    resets = Reset.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=365))
    months = {}
    for reset in resets:
        monthDate = datetime(reset.timestamp.year, reset.timestamp.month, 1)
        months[monthDate] = months.get(monthDate, 0) + 1

    monthList = sorted(months.items(), key=lambda t: t[0])
    seumActivity = []
    for month in monthList:
        seumActivity.append(
            [format_datetime(month[0], locale='fr',
                             format="MMM Y").capitalize(), month[1]])
    if (len(seumActivity) == 0):
        noSeumActivity = True
        activity_chart = None
    else:
        noSeumActivity = False
        seumActivity.insert(0, ['Mois', 'Nombre de seums'])
        activity_data = SimpleDataSource(seumActivity)
        activity_chart = gchart.ColumnChart(activity_data, options={
            'title': '',
            'legend': 'none',
            'vAxis': {'title': 'Nombre de seums'},
            'hAxis': {'title': 'Mois'},
        })

    # Graph of best likers
    likersCounts = []
    for counter in counters:
        likersCounts.append(
            [counter.trigramme, Like.objects.filter(liker=counter).count()])
    if (len(likersCounts) == 0):
        noBestLikers = True
        likers_chart = None
    else:
        likersCounts.sort(key=lambda x: -x[1])
        noBestLikers = False
        likersCounts.insert(0, ['Trigramme', 'Nombre de likes distribués'])
        likers_data = SimpleDataSource(likersCounts[:bestSeumeursNumber])
        likers_chart = gchart.ColumnChart(likers_data, options={
            'title': '',
            'legend': 'none',
            'vAxis': {'title': 'Nombre de likes distribués'},
            'hAxis': {'title': 'Trigramme'},
        })

    # Graph of popular hashtags
    hashtagsCounts = []
    keywords = Keyword.objects.all()
    for keyword in keywords:
        hashtagsCounts.append(
            ['#' + keyword.text,
             Hashtag.objects.filter(keyword=keyword).count()])
    if (len(hashtagsCounts) == 0):
        noBestHashtags = True
        hashtags_chart = None
    else:
        hashtagsCounts.sort(key=lambda x: -x[1])
        noBestHashtags = False
        hashtagsCounts.insert(0, ['Trigramme', 'Nombre de likes distribués'])
        hashtags_data = SimpleDataSource(hashtagsCounts[:bestSeumeursNumber])
        hashtags_chart = gchart.ColumnChart(hashtags_data, options={
            'title': '',
            'legend': 'none',
            'vAxis': {'title': 'Nombre de seums contenant le hashtag'},
            'hAxis': {'title': 'Hashtag'},
        })

    # Graph of best likee
    likeesCounts = []
    for counter in counters:
        likeesCounts.append(
            [counter.trigramme,
             Like.objects.filter(reset__counter=counter).count()])
    if (len(likeesCounts) == 0):
        noBestLikees = True
        likees_chart = None
    else:
        likeesCounts.sort(key=lambda x: -x[1])
        noBestLikees = False
        likeesCounts.insert(0, ['Trigramme', 'Nombre de likes reçus'])
        likees_data = SimpleDataSource(likeesCounts[:bestSeumeursNumber])
        likees_chart = gchart.ColumnChart(likees_data, options={
            'title': '',
            'legend': 'none',
            'vAxis': {'title': 'Nombre de likes reçus'},
            'hAxis': {'title': 'Trigramme'},
        })

    # At last we render the page
    return render(request, 'homeTemplate.html', {
        'counters': counters,
        'line_chart': line_chart,
        'best_chart': best_chart,
        'likers_chart': likers_chart,
        'likees_chart': likees_chart,
        'hashtags_chart': hashtags_chart,
        'activity_chart': activity_chart,
        'noTimeline': noTimeline,
        'noBestSeum': noBestSeum,
        'noBestLikers': noBestLikers,
        'noBestLikees': noBestLikees,
        'noBestHashtags': noBestHashtags,
        'noSeumActivity': noSeumActivity,
        'myCounter': myCounter,
    })


@login_required
def toggleEmailNotifications(request):
    counter = Counter.objects.get(user=request.user)
    counter.email_notifications = not counter.email_notifications
    counter.save()
    return HttpResponseRedirect(reverse('home'))


@login_required
def toggleScoreSorting(request):
    counter = Counter.objects.get(user=request.user)
    counter.sort_by_score = not counter.sort_by_score
    counter.save()
    return HttpResponseRedirect(reverse('home'))


