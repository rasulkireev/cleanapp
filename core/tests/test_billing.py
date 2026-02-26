import pytest

from core.billing import (
    get_site_limit_for_profile,
    get_trial_days_for_plan,
    normalize_plan_key,
    resolve_plan_key_from_price_id,
)
from core.choices import ProfileStates
from core.models import Sitemap


@pytest.mark.django_db
def test_normalize_plan_key_supports_legacy_aliases():
    assert normalize_plan_key("starter") == "starter"
    assert normalize_plan_key("monthly") == "starter"
    assert normalize_plan_key("yearly") == "agency"


@pytest.mark.django_db
def test_get_site_limit_for_profile_free_plan_by_default(profile):
    profile.state = ProfileStates.SIGNED_UP
    profile.stripe_plan_key = "starter"
    profile.save(update_fields=["state", "stripe_plan_key"])

    assert get_site_limit_for_profile(profile) == 1


@pytest.mark.django_db
def test_get_site_limit_for_profile_paid_plan(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.stripe_plan_key = "starter"
    profile.save(update_fields=["state", "stripe_plan_key"])

    assert get_site_limit_for_profile(profile) == 5


@pytest.mark.django_db
def test_get_site_limit_counts_only_active_sites(profile):
    profile.state = ProfileStates.SUBSCRIBED
    profile.stripe_plan_key = "starter"
    profile.save(update_fields=["state", "stripe_plan_key"])

    for idx in range(4):
        Sitemap.objects.create(profile=profile, sitemap_url=f"https://active-{idx}.example.com/sitemap.xml")

    Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://inactive.example.com/sitemap.xml",
        is_active=False,
    )

    assert get_site_limit_for_profile(profile) == 5


@pytest.mark.django_db
def test_plan_lookup_by_price_id(settings):
    settings.CLEANAPP_BILLING_PLANS = {
        "starter": {"price_id": "price_starter", "site_limit": 5, "trial_days": 14},
        "agency": {"price_id": "price_agency", "site_limit": 30, "trial_days": 14},
    }

    assert resolve_plan_key_from_price_id("price_starter") == "starter"
    assert resolve_plan_key_from_price_id("price_agency") == "agency"
    assert resolve_plan_key_from_price_id("missing") == ""


@pytest.mark.django_db
def test_get_trial_days_for_plan(settings):
    settings.CLEANAPP_BILLING_PLANS = {
        "starter": {"price_id": "price_starter", "site_limit": 5, "trial_days": 7},
        "agency": {"price_id": "price_agency", "site_limit": 30, "trial_days": 21},
    }

    assert get_trial_days_for_plan("starter") == 7
    assert get_trial_days_for_plan("agency") == 21
    assert get_trial_days_for_plan("unknown") == 0
