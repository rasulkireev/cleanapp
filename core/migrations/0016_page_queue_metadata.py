from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_sitemap_client_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="last_review_email_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Last time this page was included in a review email queue",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="page",
            name="review_queue_attempts",
            field=models.PositiveIntegerField(
                default=0,
                help_text="How many queue cycles included this page in review emails",
            ),
        ),
    ]
