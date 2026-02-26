from __future__ import annotations

from collections import OrderedDict

from core.choices import ReviewCadence


DEFAULT_CLIENT_LABEL = "Unlabeled clients"


def get_digest_period_label(cadences: set[str] | list[str] | tuple[str, ...]) -> str:
    cadence_set = set(cadences or [])

    if not cadence_set:
        return "Review digest"

    if ReviewCadence.DAILY in cadence_set:
        return "Daily review digest"

    if ReviewCadence.WEEKLY in cadence_set:
        return "Weekly summary"

    if ReviewCadence.MONTHLY in cadence_set:
        return "Monthly summary"

    return "Review digest"


def normalize_client_label(label: str | None) -> str:
    return (label or "").strip() or DEFAULT_CLIENT_LABEL


def build_client_groups(sitemaps_with_pages: list[dict]) -> list[dict]:
    grouped: OrderedDict[str, dict] = OrderedDict()

    for sitemap_data in sitemaps_with_pages:
        sitemap = sitemap_data["sitemap"]
        client_label = normalize_client_label(getattr(sitemap, "client_label", ""))

        if client_label not in grouped:
            grouped[client_label] = {
                "client_label": client_label,
                "sites": [],
                "sites_count": 0,
                "pages_count": 0,
                "due_pages_count": 0,
            }

        group = grouped[client_label]
        group["sites"].append(sitemap_data)
        group["sites_count"] += 1
        group["pages_count"] += sitemap_data.get("pages_count", 0)
        group["due_pages_count"] += sitemap_data.get(
            "due_pages_count", sitemap_data.get("pages_count", 0)
        )

    return sorted(grouped.values(), key=lambda item: item["client_label"].lower())
