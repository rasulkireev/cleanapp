from django.db import models


class ProfileStates(models.TextChoices):
    STRANGER = "stranger"
    SIGNED_UP = "signed_up"
    TRIAL_STARTED = "trial_started"
    TRIAL_ENDED = "trial_ended"
    SUBSCRIBED = "subscribed"
    CANCELLED = "cancelled"  # when user cancels their subscription, but still have access
    CHURNED = "churned"  # when user lost access to paid features
    ACCOUNT_DELETED = "account_deleted"


class BlogPostStatus(models.TextChoices):
    DRAFT = "draft"
    PUBLISHED = "published"


class ReviewCadence(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
