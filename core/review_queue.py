from __future__ import annotations

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from core.billing import cadence_to_timedelta
from core.models import Page


def get_due_pages_queryset(sitemap, now=None):
    now = now or timezone.now()
    cadence_delta = cadence_to_timedelta(sitemap.review_cadence)
    due_before = now - cadence_delta

    return (
        Page.objects.filter(
            sitemap=sitemap,
            reviewed=False,
            needs_review=True,
            is_active=True,
        )
        .filter(
            Q(last_review_email_sent_at__isnull=True)
            | Q(last_review_email_sent_at__lte=due_before)
        )
        .order_by("last_review_email_sent_at", "reviewed_at", "created_at", "id")
    )


def reserve_pages_for_review(sitemap, now=None):
    now = now or timezone.now()

    with transaction.atomic():
        selected_ids = list(
            get_due_pages_queryset(sitemap, now=now).values_list("id", flat=True)[
                : sitemap.pages_per_review
            ]
        )

        if not selected_ids:
            return []

        page_map = {page.id: page for page in Page.objects.filter(id__in=selected_ids)}
        pages = [page_map[page_id] for page_id in selected_ids if page_id in page_map]

        Page.objects.filter(id__in=selected_ids).update(
            last_review_email_sent_at=now,
            review_queue_attempts=F("review_queue_attempts") + 1,
        )

    for page in pages:
        page.last_review_email_sent_at = now
        page.review_queue_attempts = (page.review_queue_attempts or 0) + 1

    return pages
