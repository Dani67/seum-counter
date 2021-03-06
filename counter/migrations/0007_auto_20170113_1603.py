# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-01-13 16:03
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('counter', '0006_counter_sort_by_score'),
    ]

    operations = [
        migrations.CreateModel(
            name='Hashtag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'verbose_name': 'hashtags',
            },
        ),
        migrations.CreateModel(
            name='Keyword',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.CharField(max_length=128, unique=True, verbose_name='texte')),
            ],
            options={
                'verbose_name': 'mot-clé',
                'verbose_name_plural': 'mots-clés',
            },
        ),
        migrations.AddField(
            model_name='hashtag',
            name='keyword',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='counter.Keyword', verbose_name='hashtag'),
        ),
        migrations.AddField(
            model_name='hashtag',
            name='reset',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='counter.Reset', verbose_name='remise à zéro'),
        ),
    ]
