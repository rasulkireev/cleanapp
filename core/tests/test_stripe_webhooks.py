import pytest

from core.choices import ProfileStates
from core.models import Profile
from core.stripe_webhooks import (
    handle_created_subscription,
    handle_deleted_subscription,
    handle_updated_subscription,
)
from core.tests.test_helpers import build_subscription_event


@pytest.mark.django_db
def test_handle_created_subscription_starts_trial(sync_state_transitions, profile):
    event = build_subscription_event(
        status="trialing",
        customer_id="cus_trial",
        subscription_id="sub_trial",
        metadata={"user_id": profile.user_id, "plan": "starter"},
        trial_end=1_700_000_000,
    )

    handle_created_subscription(event)

    profile.refresh_from_db()
    assert profile.stripe_customer_id == "cus_trial"
    assert profile.stripe_subscription_id == "sub_trial"
    assert profile.stripe_plan_key == "starter"
    assert profile.state == ProfileStates.TRIAL_STARTED


@pytest.mark.django_db
def test_handle_created_subscription_normalizes_legacy_plan_key(sync_state_transitions, profile):
    event = build_subscription_event(
        status="trialing",
        customer_id="cus_legacy",
        subscription_id="sub_legacy",
        metadata={"user_id": profile.user_id, "plan": "monthly"},
    )

    handle_created_subscription(event)

    profile.refresh_from_db()
    assert profile.stripe_plan_key == "starter"


@pytest.mark.django_db
def test_handle_created_subscription_infers_plan_from_price_id(
    sync_state_transitions, profile, settings
):
    settings.CLEANAPP_BILLING_PLANS = {
        "starter": {"price_id": "price_starter", "site_limit": 5, "trial_days": 14},
        "agency": {"price_id": "price_agency", "site_limit": 30, "trial_days": 14},
    }

    event = build_subscription_event(
        status="active",
        customer_id="cus_plan",
        subscription_id="sub_plan",
        metadata={"user_id": profile.user_id},
        items={"data": [{"price": {"id": "price_agency"}}]},
    )

    handle_created_subscription(event)

    profile.refresh_from_db()
    assert profile.stripe_plan_key == "agency"


@pytest.mark.django_db
def test_handle_updated_subscription_marks_cancelled(sync_state_transitions, profile):
    event = build_subscription_event(
        status="active",
        customer_id="cus_cancel",
        subscription_id="sub_cancel",
        metadata={"user_id": profile.user_id},
        cancel_at_period_end=True,
        current_period_end=1_700_000_100,
    )

    handle_updated_subscription(event)

    profile.refresh_from_db()
    assert profile.stripe_customer_id == "cus_cancel"
    assert profile.stripe_subscription_id == "sub_cancel"
    assert profile.state == ProfileStates.CANCELLED


@pytest.mark.django_db
def test_handle_updated_subscription_marks_cancelled_on_cancel_at(sync_state_transitions, profile):
    event = build_subscription_event(
        status="active",
        customer_id="cus_cancel_at",
        subscription_id="sub_cancel_at",
        metadata={"user_id": profile.user_id},
        cancel_at_period_end=False,
        cancel_at=1_700_000_100,
    )

    handle_updated_subscription(event)

    profile.refresh_from_db()
    assert profile.state == ProfileStates.CANCELLED


@pytest.mark.django_db
def test_handle_updated_subscription_marks_trial_ended(sync_state_transitions, profile):
    event = build_subscription_event(
        status="canceled",
        customer_id="cus_trial_end",
        subscription_id="sub_trial_end",
        metadata={"user_id": profile.user_id},
    )
    event["data"]["previous_attributes"] = {"status": "trialing"}

    handle_updated_subscription(event)

    profile.refresh_from_db()
    assert profile.state == ProfileStates.TRIAL_ENDED


@pytest.mark.django_db
def test_handle_deleted_subscription_churns_and_clears_subscription_fields(
    sync_state_transitions, profile
):
    Profile.objects.filter(id=profile.id).update(
        stripe_customer_id="cus_deleted",
        stripe_subscription_id="sub_deleted",
        stripe_plan_key="starter",
        state=ProfileStates.SUBSCRIBED,
    )

    event = build_subscription_event(
        status="canceled",
        customer_id="cus_deleted",
        subscription_id="sub_deleted",
        ended_at=1_700_000_200,
    )

    handle_deleted_subscription(event)

    profile.refresh_from_db()
    assert profile.state == ProfileStates.CHURNED
    assert profile.stripe_subscription_id == ""
    assert profile.stripe_plan_key == ""
