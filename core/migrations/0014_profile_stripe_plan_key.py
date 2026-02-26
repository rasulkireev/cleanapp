from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_alter_profile_stripe_customer_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="stripe_plan_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Current normalized billing plan key derived from Stripe",
                max_length=64,
            ),
        ),
    ]
