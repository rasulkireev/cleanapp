from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django_q.tasks import async_task

from cleanapp.utils import get_cleanapp_logger
from core.base_models import BaseModel
from core.choices import BlogPostStatus, ProfileStates, ReviewCadence
from core.model_utils import generate_random_key

logger = get_cleanapp_logger(__name__)


class Profile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=30, unique=True, default=generate_random_key)
    experimental_flag = models.BooleanField(default=False)

    subscription = models.ForeignKey(
        "djstripe.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Subscription object, if it exists",
    )
    product = models.ForeignKey(
        "djstripe.Product",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Product object, if it exists",
    )
    customer = models.ForeignKey(
        "djstripe.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profile",
        help_text="The user's Stripe Customer object, if it exists",
    )

    state = models.CharField(
        max_length=255,
        choices=ProfileStates.choices,
        default=ProfileStates.STRANGER,
        help_text="The current state of the user's profile",
    )

    preferred_email_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Preferred time of day to receive emails (in user's timezone)",
    )
    timezone = models.CharField(
        max_length=63,
        default="UTC",
        help_text="User's timezone (e.g., 'America/New_York', 'Europe/London')",
    )

    def track_state_change(self, to_state, metadata=None):
        async_task(
            "core.tasks.track_state_change",
            profile_id=self.id,
            from_state=self.current_state,
            to_state=to_state,
            metadata=metadata,
            source_function="Profile - track_state_change",
            group="Track State Change",
        )

    @property
    def current_state(self):
        if not self.state_transitions.all().exists():
            return ProfileStates.STRANGER
        latest_transition = self.state_transitions.latest("created_at")
        return latest_transition.to_state

    @property
    def has_active_subscription(self):
        return (
            self.current_state
            in [
                ProfileStates.SUBSCRIBED,
                ProfileStates.CANCELLED,
            ]
            or self.user.is_superuser
        )


class ProfileStateTransition(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="state_transitions",
    )
    from_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    to_state = models.CharField(max_length=255, choices=ProfileStates.choices)
    backup_profile_id = models.IntegerField()
    metadata = models.JSONField(null=True, blank=True)


class BlogPost(BaseModel):
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    slug = models.SlugField(max_length=250)
    tags = models.TextField()
    content = models.TextField()
    icon = models.ImageField(upload_to="blog_post_icons/", blank=True)
    image = models.ImageField(upload_to="blog_post_images/", blank=True)
    status = models.CharField(
        max_length=10,
        choices=BlogPostStatus.choices,
        default=BlogPostStatus.DRAFT,
    )

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog_post", kwargs={"slug": self.slug})


class Feedback(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="feedback",
        help_text="The user who submitted the feedback",
    )
    feedback = models.TextField(
        help_text="The feedback text",
    )
    page = models.CharField(
        max_length=255,
        help_text="The page where the feedback was submitted",
    )

    def __str__(self):
        return f"{self.profile.user.email}: {self.feedback}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)

        if is_new:
            from django.conf import settings
            from django.core.mail import send_mail

            subject = "New Feedback Submitted"
            message = f"""
                New feedback was submitted:\n\n
                User: {self.profile.user.email if self.profile else "Anonymous"}
                Feedback: {self.feedback}
                Page: {self.page}
            """
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [settings.DEFAULT_FROM_EMAIL]

            send_mail(subject, message, from_email, recipient_list, fail_silently=True)


class Sitemap(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sitemap",
    )
    sitemap_url = models.URLField(
        help_text="The sitemap text",
    )
    pages_per_review = models.PositiveIntegerField(
        default=1, help_text="Number of pages to review per email"
    )
    review_cadence = models.CharField(
        max_length=20,
        choices=ReviewCadence.choices,
        default=ReviewCadence.DAILY,
        help_text="How often to send review emails",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this sitemap is still accessible and should be processed",
    )

    def __str__(self):
        return f"{self.sitemap_url} - <{self.profile}>"

    # def get_absolute_url(self):
    #     return reverse("sitemap", kwargs={"slug": self.slug})


class Page(BaseModel):
    profile = models.ForeignKey(
        Profile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    sitemap = models.ForeignKey(
        Sitemap,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    url = models.URLField(
        help_text="The page URL",
    )
    reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    needs_review = models.BooleanField(
        default=True, help_text="Whether this page needs to be reviewed"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this page is still present in the sitemap",
    )

    def __str__(self):
        return f"{self.url} - <{self.profile}>"

    # def get_absolute_url(self):
    #     return reverse("page", kwargs={"slug": self.slug})


class EmailSent(BaseModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="emails_sent",
    )

    def __str__(self):
        return f"{self.created_at} <{self.profile.user.email}>"


class EmailPreference(BaseModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="email_preferences",
    )
    email_address = models.EmailField(help_text="Email address to receive notifications")
    enabled = models.BooleanField(
        default=True, help_text="Whether to send notifications to this email"
    )

    class Meta:
        unique_together = ("profile", "email_address")

    def __str__(self):
        return f"{self.email_address} ({'enabled' if self.enabled else 'disabled'})"
