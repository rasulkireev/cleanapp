from __future__ import annotations

from datetime import timedelta

from django.conf import settings

from core.choices import ProfileStates, ReviewCadence

PLAN_ALIASES = {
    "monthly": "starter",
    "yearly": "agency",
}

ACTIVE_BILLING_STATES = {
    ProfileStates.TRIAL_STARTED,
    ProfileStates.SUBSCRIBED,
    ProfileStates.CANCELLED,
}


def normalize_plan_key(plan_key: str | None) -> str:
    if not plan_key:
        return ""
    normalized = plan_key.strip().lower()
    return PLAN_ALIASES.get(normalized, normalized)


def get_plan_config(plan_key: str | None) -> dict | None:
    normalized = normalize_plan_key(plan_key)
    if not normalized:
        return None
    return settings.CLEANAPP_BILLING_PLANS.get(normalized)


def get_available_plans() -> list[dict]:
    plans: list[dict] = []
    for key, config in settings.CLEANAPP_BILLING_PLANS.items():
        if not config.get("price_id"):
            continue
        plans.append(
            {
                "key": key,
                "display_name": config.get("display_name", key.title()),
                "site_limit": int(config.get("site_limit", settings.CLEANAPP_FREE_SITE_LIMIT)),
                "trial_days": int(config.get("trial_days", 0)),
            }
        )
    return plans


def resolve_plan_key_from_price_id(price_id: str | None) -> str:
    if not price_id:
        return ""

    for plan_key, config in settings.CLEANAPP_BILLING_PLANS.items():
        if config.get("price_id") == price_id:
            return plan_key

    return ""


def get_trial_days_for_plan(plan_key: str | None) -> int:
    plan_config = get_plan_config(plan_key)
    if not plan_config:
        return 0
    return int(plan_config.get("trial_days", 0))


def get_site_limit_for_profile(profile) -> int:
    if profile.state not in ACTIVE_BILLING_STATES:
        return int(settings.CLEANAPP_FREE_SITE_LIMIT)

    plan_config = get_plan_config(profile.stripe_plan_key)
    if not plan_config:
        return int(settings.CLEANAPP_FREE_SITE_LIMIT)

    return int(plan_config.get("site_limit", settings.CLEANAPP_FREE_SITE_LIMIT))


def get_active_site_count(profile) -> int:
    from core.models import Sitemap

    return Sitemap.objects.filter(profile=profile, is_active=True).count()


def has_reached_site_limit(profile) -> bool:
    return get_active_site_count(profile) >= get_site_limit_for_profile(profile)


def cadence_to_timedelta(cadence: str) -> timedelta:
    if cadence == ReviewCadence.WEEKLY:
        return timedelta(weeks=1)
    if cadence == ReviewCadence.MONTHLY:
        return timedelta(days=30)
    return timedelta(days=1)
