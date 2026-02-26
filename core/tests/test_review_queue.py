from datetime import timedelta

import pytest
from django.utils import timezone

from core.choices import ReviewCadence
from core.models import Page, Sitemap
from core.review_queue import reserve_pages_for_review
from core.tasks import send_page_email_to_profile


@pytest.mark.django_db
def test_review_queue_is_deterministic(profile):
    sitemap = Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://agency.example.com/sitemap.xml",
        review_cadence=ReviewCadence.DAILY,
        pages_per_review=2,
    )

    now = timezone.now()

    first = Page.objects.create(profile=profile, sitemap=sitemap, url="https://agency.example.com/a")
    second = Page.objects.create(profile=profile, sitemap=sitemap, url="https://agency.example.com/b")
    third = Page.objects.create(profile=profile, sitemap=sitemap, url="https://agency.example.com/c")

    Page.objects.filter(id=first.id).update(created_at=now - timedelta(days=3))
    Page.objects.filter(id=second.id).update(created_at=now - timedelta(days=2))
    Page.objects.filter(id=third.id).update(created_at=now - timedelta(days=1))

    selected = reserve_pages_for_review(sitemap, now=now)

    assert [page.id for page in selected] == [first.id, second.id]

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.review_queue_attempts == 1
    assert second.review_queue_attempts == 1
    assert first.last_review_email_sent_at == now
    assert second.last_review_email_sent_at == now


@pytest.mark.django_db
def test_review_queue_does_not_repeat_pages_in_same_cycle(profile):
    sitemap = Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://dupes.example.com/sitemap.xml",
        review_cadence=ReviewCadence.DAILY,
        pages_per_review=2,
    )

    Page.objects.create(profile=profile, sitemap=sitemap, url="https://dupes.example.com/a")
    Page.objects.create(profile=profile, sitemap=sitemap, url="https://dupes.example.com/b")

    now = timezone.now()

    first_run = reserve_pages_for_review(sitemap, now=now)
    second_run = reserve_pages_for_review(sitemap, now=now + timedelta(hours=1))

    assert len(first_run) == 2
    assert second_run == []


@pytest.mark.django_db
def test_review_queue_retries_after_cadence_window(profile):
    sitemap = Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://retry.example.com/sitemap.xml",
        review_cadence=ReviewCadence.DAILY,
        pages_per_review=1,
    )
    page = Page.objects.create(profile=profile, sitemap=sitemap, url="https://retry.example.com/a")

    now = timezone.now()

    first_run = reserve_pages_for_review(sitemap, now=now)
    same_cycle_run = reserve_pages_for_review(sitemap, now=now + timedelta(hours=6))
    next_cycle_run = reserve_pages_for_review(sitemap, now=now + timedelta(days=2))

    assert [p.id for p in first_run] == [page.id]
    assert same_cycle_run == []
    assert [p.id for p in next_cycle_run] == [page.id]


@pytest.mark.django_db
def test_review_queue_skips_inactive_and_no_review_pages(profile):
    sitemap = Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://skip.example.com/sitemap.xml",
        review_cadence=ReviewCadence.DAILY,
        pages_per_review=5,
    )

    Page.objects.create(
        profile=profile,
        sitemap=sitemap,
        url="https://skip.example.com/no-review",
        needs_review=False,
    )
    Page.objects.create(
        profile=profile,
        sitemap=sitemap,
        url="https://skip.example.com/inactive",
        is_active=False,
    )
    keep = Page.objects.create(profile=profile, sitemap=sitemap, url="https://skip.example.com/keep")

    selected = reserve_pages_for_review(sitemap, now=timezone.now())

    assert [page.id for page in selected] == [keep.id]


@pytest.mark.django_db
def test_send_page_email_uses_queue_window(monkeypatch, profile):
    sitemap = Sitemap.objects.create(
        profile=profile,
        sitemap_url="https://mail.example.com/sitemap.xml",
        review_cadence=ReviewCadence.DAILY,
        pages_per_review=1,
    )
    page = Page.objects.create(profile=profile, sitemap=sitemap, url="https://mail.example.com/a")

    monkeypatch.setattr("core.tasks.fetch_page_metadata", lambda _url: {})
    monkeypatch.setattr(
        "django.template.loader.render_to_string",
        lambda template_name, context=None: "<p>review page content</p>",
    )
    monkeypatch.setattr("django.core.mail.EmailMultiAlternatives.send", lambda self: None)

    first_run_message = send_page_email_to_profile(profile.id)
    second_run_message = send_page_email_to_profile(profile.id)

    page.refresh_from_db()

    assert "Successfully sent page review email" in first_run_message
    assert "No unreviewed pages found" in second_run_message
    assert page.review_queue_attempts == 1
    assert page.last_review_email_sent_at is not None
