from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.urls import reverse

from core.choices import ProfileStates
from core.models import Sitemap
from core.views import HomeView


@pytest.fixture
def configured_billing_plans(settings):
    settings.CLEANAPP_FREE_SITE_LIMIT = 1
    settings.CLEANAPP_BILLING_PLANS = {
        "starter": {
            "display_name": "Starter",
            "price_id": "price_starter",
            "site_limit": 5,
            "trial_days": 14,
        },
        "agency": {
            "display_name": "Agency",
            "price_id": "price_agency",
            "site_limit": 30,
            "trial_days": 14,
        },
    }
    settings.STRIPE_PRICE_IDS = {
        "starter": "price_starter",
        "agency": "price_agency",
        "monthly": "price_starter",
        "yearly": "price_agency",
    }


@pytest.fixture(autouse=True)
def disable_sitemap_background_tasks(monkeypatch):
    from core import signals

    monkeypatch.setattr(signals, "async_task", lambda *args, **kwargs: None)


@pytest.mark.django_db
class TestHomeView:
    def test_home_view_status_code(self, user):
        request = RequestFactory().get(reverse("home"))
        request.user = user

        response = HomeView.as_view()(request)

        assert response.status_code == 200

    def test_home_view_uses_correct_template(self, user):
        request = RequestFactory().get(reverse("home"))
        request.user = user

        response = HomeView.as_view()(request)

        assert "pages/home.html" in response.template_name

    def test_home_blocks_new_sitemap_when_limit_reached(
        self, auth_client, profile, configured_billing_plans
    ):
        profile.state = ProfileStates.SUBSCRIBED
        profile.stripe_plan_key = "starter"
        profile.save(update_fields=["state", "stripe_plan_key"])

        for idx in range(5):
            Sitemap.objects.create(
                profile=profile,
                sitemap_url=f"https://limit-{idx}.example.com/sitemap.xml",
            )

        response = auth_client.post(
            reverse("home"),
            {"sitemap_url": "https://blocked.example.com/sitemap.xml"},
        )

        assert response.status_code == 302
        assert response.url == reverse("pricing")
        assert Sitemap.objects.filter(profile=profile, is_active=True).count() == 5

    def test_home_allows_new_sitemap_when_under_limit(
        self, auth_client, profile, configured_billing_plans
    ):
        profile.state = ProfileStates.SUBSCRIBED
        profile.stripe_plan_key = "starter"
        profile.save(update_fields=["state", "stripe_plan_key"])

        for idx in range(4):
            Sitemap.objects.create(
                profile=profile,
                sitemap_url=f"https://under-{idx}.example.com/sitemap.xml",
            )

        response = auth_client.post(
            reverse("home"),
            {"sitemap_url": "https://allowed.example.com/sitemap.xml"},
        )

        assert response.status_code == 302
        assert response.url == reverse("home")
        assert Sitemap.objects.filter(profile=profile, is_active=True).count() == 5

    def test_home_limit_counts_only_active_sitemaps(
        self, auth_client, profile, configured_billing_plans
    ):
        profile.state = ProfileStates.SUBSCRIBED
        profile.stripe_plan_key = "starter"
        profile.save(update_fields=["state", "stripe_plan_key"])

        for idx in range(4):
            Sitemap.objects.create(
                profile=profile,
                sitemap_url=f"https://active-{idx}.example.com/sitemap.xml",
            )

        Sitemap.objects.create(
            profile=profile,
            sitemap_url="https://archived.example.com/sitemap.xml",
            is_active=False,
        )

        response = auth_client.post(
            reverse("home"),
            {"sitemap_url": "https://fifth-active.example.com/sitemap.xml"},
        )

        assert response.status_code == 302
        assert response.url == reverse("home")
        assert Sitemap.objects.filter(profile=profile, is_active=True).count() == 5


@pytest.mark.django_db
class TestCheckoutSession:
    def test_checkout_adds_trial_for_eligible_profiles(
        self, auth_client, user, profile, configured_billing_plans, monkeypatch
    ):
        profile.state = ProfileStates.SIGNED_UP
        profile.save(update_fields=["state"])

        captured = {}

        def fake_session_create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(url="https://stripe.test/checkout")

        monkeypatch.setattr(
            "core.views.get_or_create_stripe_customer",
            lambda *_args, **_kwargs: SimpleNamespace(id="cus_test"),
        )
        monkeypatch.setattr("core.views.stripe.checkout.Session.create", fake_session_create)

        response = auth_client.post(
            reverse("user_upgrade_checkout_session", kwargs={"pk": user.id, "plan": "starter"})
        )

        assert response.status_code == 302
        assert response.url == "https://stripe.test/checkout"
        assert captured["metadata"]["plan"] == "starter"
        assert captured["subscription_data"]["trial_period_days"] == 14

    def test_checkout_skips_trial_for_already_subscribed_profiles(
        self, auth_client, user, profile, configured_billing_plans, monkeypatch
    ):
        profile.state = ProfileStates.SUBSCRIBED
        profile.save(update_fields=["state"])

        captured = {}

        def fake_session_create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(url="https://stripe.test/checkout")

        monkeypatch.setattr(
            "core.views.get_or_create_stripe_customer",
            lambda *_args, **_kwargs: SimpleNamespace(id="cus_test"),
        )
        monkeypatch.setattr("core.views.stripe.checkout.Session.create", fake_session_create)

        response = auth_client.post(
            reverse("user_upgrade_checkout_session", kwargs={"pk": user.id, "plan": "agency"})
        )

        assert response.status_code == 302
        assert response.url == "https://stripe.test/checkout"
        assert captured["metadata"]["plan"] == "agency"
        assert "trial_period_days" not in captured["subscription_data"]
