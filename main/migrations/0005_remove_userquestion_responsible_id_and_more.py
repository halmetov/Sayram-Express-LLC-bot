# Generated by Django 5.1.6 on 2025-03-05 16:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_category_responsible_topic_id'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userquestion',
            name='responsible_id',
        ),
        migrations.AddField(
            model_name='userquestion',
            name='responsible_name',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
