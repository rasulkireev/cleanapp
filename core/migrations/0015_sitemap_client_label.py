from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_profile_stripe_plan_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitemap",
            name="client_label",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional client/workspace label used for grouping sites",
                max_length=120,
            ),
        ),
    ]
