from types import SimpleNamespace

from core.choices import ReviewCadence
from core.email_digest import (
    DEFAULT_CLIENT_LABEL,
    build_client_groups,
    get_digest_period_label,
    normalize_client_label,
)


def make_site(url, client_label, pages_count, due_pages_count):
    sitemap = SimpleNamespace(sitemap_url=url, client_label=client_label)
    return {
        "sitemap": sitemap,
        "pages": [SimpleNamespace(url=f"{url}/p{i}") for i in range(pages_count)],
        "pages_count": pages_count,
        "due_pages_count": due_pages_count,
    }


def test_normalize_client_label_uses_default_fallback():
    assert normalize_client_label("") == DEFAULT_CLIENT_LABEL
    assert normalize_client_label("   ") == DEFAULT_CLIENT_LABEL
    assert normalize_client_label(None) == DEFAULT_CLIENT_LABEL
    assert normalize_client_label(" Acme ") == "Acme"


def test_build_client_groups_groups_by_client_label_and_sums_counts():
    sitemaps_with_pages = [
        make_site("https://a.example.com/sitemap.xml", "Acme", pages_count=2, due_pages_count=5),
        make_site("https://b.example.com/sitemap.xml", "Acme", pages_count=1, due_pages_count=3),
        make_site("https://c.example.com/sitemap.xml", "", pages_count=1, due_pages_count=1),
    ]

    groups = build_client_groups(sitemaps_with_pages)

    assert len(groups) == 2

    acme_group = next(group for group in groups if group["client_label"] == "Acme")
    unlabeled_group = next(
        group for group in groups if group["client_label"] == DEFAULT_CLIENT_LABEL
    )

    assert acme_group["sites_count"] == 2
    assert acme_group["pages_count"] == 3
    assert acme_group["due_pages_count"] == 8

    assert unlabeled_group["sites_count"] == 1
    assert unlabeled_group["pages_count"] == 1
    assert unlabeled_group["due_pages_count"] == 1


def test_get_digest_period_label_prefers_daily_over_other_cadences():
    result = get_digest_period_label({ReviewCadence.DAILY, ReviewCadence.WEEKLY})
    assert result == "Daily review digest"


def test_get_digest_period_label_weekly_and_monthly_modes():
    assert get_digest_period_label({ReviewCadence.WEEKLY}) == "Weekly summary"
    assert get_digest_period_label({ReviewCadence.MONTHLY}) == "Monthly summary"
