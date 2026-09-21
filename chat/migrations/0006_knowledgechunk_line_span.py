"""Line spans for knowledge chunks (citation links point at the passage)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_chatmessage_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgechunk",
            name="start_line",
            field=models.PositiveIntegerField(
                default=0, verbose_name="First line"
            ),
        ),
        migrations.AddField(
            model_name="knowledgechunk",
            name="end_line",
            field=models.PositiveIntegerField(
                default=0, verbose_name="Last line"
            ),
        ),
    ]
