# Generated by Django 5.1.6 on 2025-03-18 18:53

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0008_teleuser'),
    ]

    operations = [
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=200, unique=True)),
            ],
        ),
        migrations.RemoveField(
            model_name='teleuser',
            name='last_name',
        ),
        migrations.AddField(
            model_name='teleuser',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.company'),
        ),
        migrations.CreateModel(
            name='TimeOff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_from', models.DateField()),
                ('date_till', models.DateField()),
                ('reason', models.TextField()),
                ('pause_insurance', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('teleuser', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.teleuser')),
            ],
        ),
    ]
