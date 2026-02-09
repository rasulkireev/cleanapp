from allauth.account.signals import email_confirmed, user_signed_up
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from cleanapp.utils import get_cleanapp_logger
from core.models import EmailPreference, Profile, ProfileStates, Sitemap
from core.tasks import add_email_to_buttondown

logger = get_cleanapp_logger(__name__)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        profile = Profile.objects.create(user=instance, experimental_flag=True)
        profile.track_state_change(
            to_state=ProfileStates.SIGNED_UP,
            source="create_user_profile signal",
        )

        EmailPreference.objects.create(profile=profile, email_address=instance.email, enabled=True)

    if instance.id == 1:
        User.objects.filter(id=1).update(is_staff=True, is_superuser=True)


@receiver(email_confirmed)
def add_email_to_buttondown_on_confirm(sender, **kwargs):
    logger.info(
        "Adding new user to buttondown newsletter, on email confirmation",
        kwargs=kwargs,
        sender=sender,
    )
    async_task(add_email_to_buttondown, kwargs["email_address"], tag="user")


@receiver(user_signed_up)
def email_confirmation_callback(sender, request, user, **kwargs):
    if "sociallogin" in kwargs:
        logger.info(
            "Adding new user to buttondown newsletter on social signup",
            kwargs=kwargs,
            sender=sender,
        )
        email = kwargs["sociallogin"].user.email
        if email:
            async_task(add_email_to_buttondown, email, tag="user")


@receiver(post_save, sender=Sitemap)
def process_sitemap_on_creation(sender, instance, created, **kwargs):
    if created:
        async_task(
            "core.tasks.process_sitemap_pages",
            sitemap_id=instance.id,
            group="Process Sitemap",
        )
