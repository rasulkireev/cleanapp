import json
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import time
from urllib.parse import unquote, urlparse

import posthog
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django_q.tasks import async_task

from cleanapp.utils import get_cleanapp_logger
from core.models import Profile

logger = get_cleanapp_logger(__name__)


def add_email_to_buttondown(email, tag):
    if not settings.BUTTONDOWN_API_KEY:
        return "Buttondown API key not found."

    data = {
        "email_address": str(email),
        "metadata": {"source": tag},
        "tags": [tag],
        "referrer_url": "https://cleanapp.com",
        "type": "regular",
    }

    r = requests.post(
        "https://api.buttondown.email/v1/subscribers",
        headers={"Authorization": f"Token {settings.BUTTONDOWN_API_KEY}"},
        json=data,
    )

    return r.json()


def try_create_posthog_alias(profile_id: int, cookies: dict, source_function: str = None) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "cookies": cookies,
        "source_function": source_function,
    }

    profile = Profile.objects.get(id=profile_id)
    email = profile.user.email

    base_log_data["email"] = email
    base_log_data["profile_id"] = profile_id

    posthog_cookie = cookies.get(f"ph_{settings.POSTHOG_API_KEY}_posthog")
    if not posthog_cookie:
        logger.warning("[Try Create Posthog Alias] No PostHog cookie found.", **base_log_data)
        return f"No PostHog cookie found for profile {profile_id}."
    base_log_data["posthog_cookie"] = posthog_cookie

    logger.info("[Try Create Posthog Alias] Setting PostHog alias", **base_log_data)

    cookie_dict = json.loads(unquote(posthog_cookie))
    frontend_distinct_id = cookie_dict.get("distinct_id")

    if frontend_distinct_id:
        posthog.alias(frontend_distinct_id, email)
        posthog.alias(frontend_distinct_id, str(profile_id))

    logger.info("[Try Create Posthog Alias] Set PostHog alias", **base_log_data)


def track_event(
    profile_id: int, event_name: str, properties: dict, source_function: str = None
) -> str:
    if not settings.POSTHOG_API_KEY:
        return "PostHog API key not found."

    base_log_data = {
        "profile_id": profile_id,
        "event_name": event_name,
        "properties": properties,
        "source_function": source_function,
    }

    try:
        profile = Profile.objects.get(id=profile_id)
    except Profile.DoesNotExist:
        logger.error("[TrackEvent] Profile not found.", **base_log_data)
        return f"Profile with id {profile_id} not found."

    posthog.capture(
        profile.user.email,
        event=event_name,
        properties={
            "profile_id": profile.id,
            "email": profile.user.email,
            "current_state": profile.state,
            **properties,
        },
    )

    logger.info("[TrackEvent] Tracked event", **base_log_data)

    return f"Tracked event {event_name} for profile {profile_id}"


def track_state_change(
    profile_id: int,
    from_state: str,
    to_state: str,
    metadata: dict = None,
    source_function: str = None,
) -> None:
    from core.models import Profile, ProfileStateTransition

    base_log_data = {
        "profile_id": profile_id,
        "from_state": from_state,
        "to_state": to_state,
        "metadata": metadata,
        "source_function": source_function,
    }

    try:
        profile = Profile.objects.get(id=profile_id)
    except Profile.DoesNotExist:
        logger.error("[TrackStateChange] Profile not found.", **base_log_data)
        return f"Profile with id {profile_id} not found."

    if from_state != to_state:
        logger.info("[TrackStateChange] Tracking state change", **base_log_data)
        ProfileStateTransition.objects.create(
            profile=profile,
            from_state=from_state,
            to_state=to_state,
            backup_profile_id=profile_id,
            metadata=metadata,
        )
        profile.state = to_state
        profile.save(update_fields=["state"])

    return f"Tracked state change from {from_state} to {to_state} for profile {profile_id}"


def process_sitemap_pages(sitemap_id: int, max_sitemaps: int = 100) -> str:  # noqa: C901
    """
    TODO: Refactor this function to reduce complexity.
    Consider extracting helper functions for validation, sitemap fetching, and page creation.
    """
    from core.models import Page, Sitemap

    try:
        sitemap = Sitemap.objects.get(id=sitemap_id)
    except Sitemap.DoesNotExist:
        return f"Sitemap with id {sitemap_id} not found."

    pages_created = 0
    pages_skipped = 0
    sitemaps_processed = 0
    visited_urls = set()

    def fetch_and_parse_sitemap(sitemap_url: str, depth: int = 0) -> tuple[int, int, int]:  # noqa: C901
        nonlocal pages_created, pages_skipped, sitemaps_processed, visited_urls

        if depth > 10:
            logger.warning(
                "Max recursion depth reached",
                sitemap_id=sitemap_id,
                sitemap_url=sitemap_url,
                depth=depth,
            )
            return pages_created, pages_skipped, sitemaps_processed

        if sitemaps_processed >= max_sitemaps:
            logger.warning(
                "Max sitemaps limit reached",
                sitemap_id=sitemap_id,
                max_sitemaps=max_sitemaps,
            )
            return pages_created, pages_skipped, sitemaps_processed

        if sitemap_url in visited_urls:
            logger.warning(
                "Circular reference detected",
                sitemap_id=sitemap_id,
                sitemap_url=sitemap_url,
            )
            return pages_created, pages_skipped, sitemaps_processed

        visited_urls.add(sitemap_url)

        try:
            response = requests.get(sitemap_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(
                "Failed to fetch sitemap",
                sitemap_id=sitemap_id,
                sitemap_url=sitemap_url,
                error=str(e),
                exc_info=True,
            )
            raise

        try:
            root = ET.fromstring(response.content)
            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            nested_sitemaps = root.findall(".//ns:sitemap/ns:loc", namespace)
            if not nested_sitemaps:
                nested_sitemaps = root.findall(".//sitemap/loc")

            if nested_sitemaps:
                logger.info(
                    "Found nested sitemaps",
                    sitemap_id=sitemap_id,
                    parent_sitemap_url=sitemap_url,
                    nested_count=len(nested_sitemaps),
                    depth=depth,
                )
                for nested_sitemap_element in nested_sitemaps:
                    nested_url = nested_sitemap_element.text
                    if nested_url:
                        sitemaps_processed += 1
                        fetch_and_parse_sitemap(nested_url, depth + 1)
                return pages_created, pages_skipped, sitemaps_processed

            urls = root.findall(".//ns:url/ns:loc", namespace)
            if not urls:
                urls = root.findall(".//url/loc")

            for url_element in urls:
                url = url_element.text
                if not url:
                    continue

                existing_page = Page.objects.filter(sitemap=sitemap, url=url).first()

                if existing_page:
                    pages_skipped += 1
                    continue

                Page.objects.create(profile=sitemap.profile, sitemap=sitemap, url=url)
                pages_created += 1

            return pages_created, pages_skipped, sitemaps_processed

        except ET.ParseError as e:
            logger.error(
                "Failed to parse sitemap XML",
                sitemap_id=sitemap_id,
                sitemap_url=sitemap_url,
                error=str(e),
                exc_info=True,
            )
            raise

    try:
        sitemaps_processed = 1
        fetch_and_parse_sitemap(sitemap.sitemap_url)

        logger.info(
            "Sitemap processing complete",
            sitemap_id=sitemap_id,
            sitemap_url=sitemap.sitemap_url,
            pages_created=pages_created,
            pages_skipped=pages_skipped,
            sitemaps_processed=sitemaps_processed,
        )

        return f"Processed sitemap {sitemap_id}: created {pages_created} pages, skipped {pages_skipped} existing pages, processed {sitemaps_processed} sitemap(s)"  # noqa: E501

    except Exception as e:
        logger.error(
            "Sitemap processing failed",
            sitemap_id=sitemap_id,
            sitemap_url=sitemap.sitemap_url,
            error=str(e),
            exc_info=True,
        )
        return f"Failed to process sitemap: {str(e)}"


def fetch_page_metadata(url: str) -> dict:
    try:
        response = requests.get(
            url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; CleanappBot/1.0)"}
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")

        title = None
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title.get("content").strip()

        description = None
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc.get("content").strip()

        og_description = soup.find("meta", property="og:description")
        if og_description and og_description.get("content"):
            description = og_description.get("content").strip()

        author = None
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            author = meta_author.get("content").strip()

        og_author = soup.find("meta", property="article:author")
        if og_author and og_author.get("content"):
            author = og_author.get("content").strip()

        keywords = None
        meta_keywords = soup.find("meta", attrs={"name": "keywords"})
        if meta_keywords and meta_keywords.get("content"):
            keywords = meta_keywords.get("content").strip()

        og_image = soup.find("meta", property="og:image")
        og_image_url = (
            og_image.get("content").strip() if og_image and og_image.get("content") else None
        )

        og_type = soup.find("meta", property="og:type")
        og_type_value = (
            og_type.get("content").strip() if og_type and og_type.get("content") else None
        )

        twitter_card = soup.find("meta", attrs={"name": "twitter:card"})
        twitter_card_value = (
            twitter_card.get("content").strip()
            if twitter_card and twitter_card.get("content")
            else None
        )

        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        twitter_title_value = (
            twitter_title.get("content").strip()
            if twitter_title and twitter_title.get("content")
            else None
        )

        twitter_description = soup.find("meta", attrs={"name": "twitter:description"})
        twitter_description_value = (
            twitter_description.get("content").strip()
            if twitter_description and twitter_description.get("content")
            else None
        )

        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        twitter_image_url = (
            twitter_image.get("content").strip()
            if twitter_image and twitter_image.get("content")
            else None
        )

        metadata = {
            "title": title,
            "description": description,
            "author": author,
            "keywords": keywords,
            "og_image": og_image_url,
            "og_type": og_type_value,
            "twitter_card": twitter_card_value,
            "twitter_title": twitter_title_value,
            "twitter_description": twitter_description_value,
            "twitter_image": twitter_image_url,
        }

        logger.info(
            "Page metadata fetched successfully",
            url=url,
            has_title=bool(title),
            has_description=bool(description),
            has_author=bool(author),
            has_keywords=bool(keywords),
            has_og_tags=bool(og_image_url or og_type_value),
            has_twitter_tags=bool(twitter_card_value or twitter_title_value),
        )

        return metadata

    except requests.RequestException as e:
        logger.warning(
            "Failed to fetch page for metadata extraction",
            url=url,
            error=str(e),
        )
        return {}
    except Exception as e:
        logger.warning(
            "Failed to extract page metadata",
            url=url,
            error=str(e),
        )
        return {}


def send_page_email_to_profile(profile_id: int) -> str:
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.urls import reverse
    from django.utils.html import strip_tags

    from core.models import EmailPreference, EmailSent, Page, Profile, Sitemap

    try:
        profile = Profile.objects.get(id=profile_id)
    except Profile.DoesNotExist:
        return f"Profile with id {profile_id} not found."

    sitemaps = Sitemap.objects.filter(profile=profile)

    if not sitemaps.exists():
        return f"No sitemaps found for profile {profile_id}."

    sitemaps_with_pages = []
    total_pages_collected = 0

    for sitemap in sitemaps:
        unreviewed_pages = Page.objects.filter(
            sitemap=sitemap, reviewed=False, needs_review=True
        ).order_by("?")[: sitemap.pages_per_review]

        if unreviewed_pages.exists():
            pages_list = []
            for page in unreviewed_pages:
                metadata = fetch_page_metadata(page.url)

                page.title = metadata.get("title")
                page.description = metadata.get("description")
                page.author = metadata.get("author")
                page.keywords = metadata.get("keywords")
                page.og_image = metadata.get("og_image")
                page.og_type = metadata.get("og_type")
                page.twitter_card = metadata.get("twitter_card")
                page.twitter_title = metadata.get("twitter_title")
                page.twitter_description = metadata.get("twitter_description")
                page.twitter_image = metadata.get("twitter_image")

                review_url = f"{settings.SITE_URL}{reverse('review_page_redirect', kwargs={'page_id': page.id})}"  # noqa: E501
                page.review_url = review_url

                parsed_url = urlparse(page.url)
                page.url_path = parsed_url.path or "/"

                pages_list.append(page)

            sitemaps_with_pages.append(
                {"sitemap": sitemap, "pages": pages_list, "pages_count": len(pages_list)}
            )
            total_pages_collected += len(pages_list)

    if not sitemaps_with_pages:
        return f"No unreviewed pages found for profile {profile_id}."

    context = {
        "profile": profile,
        "user": profile.user,
        "sitemaps_with_pages": sitemaps_with_pages,
        "total_sitemaps": len(sitemaps_with_pages),
        "total_pages": total_pages_collected,
    }

    html_content = render_to_string("emails/page_review.html", context)
    text_content = strip_tags(html_content)

    subject = (
        f"Time to Review {total_pages_collected} Page{'s' if total_pages_collected > 1 else ''}"
    )

    email_preferences = EmailPreference.objects.filter(profile=profile, enabled=True).values_list(
        "email_address", flat=True
    )

    recipient_list = list(email_preferences)

    if not recipient_list:
        recipient_list = [profile.user.email]

    email = EmailMultiAlternatives(
        subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list,
    )
    email.attach_alternative(html_content, "text/html")

    try:
        email.send()
        EmailSent.objects.create(profile=profile)
        logger.info(
            "Page review email sent",
            email=profile.user.email,
            profile_id=profile_id,
            total_sitemaps=len(sitemaps_with_pages),
            total_pages=total_pages_collected,
            recipient_count=len(recipient_list),
            recipients=recipient_list,
        )
        return f"Successfully sent page review email to {len(recipient_list)} address(es) with {total_pages_collected} pages from {len(sitemaps_with_pages)} sitemaps"  # noqa: E501
    except Exception as e:
        logger.error(
            "Failed to send page review email",
            email=profile.user.email,
            profile_id=profile_id,
            error=str(e),
            exc_info=True,
        )
        return f"Failed to send email: {str(e)}"


def schedule_review_emails() -> str:
    from core.models import EmailSent, Profile
    from core.utils import should_send_email_to_profile

    profiles_with_sitemaps = Profile.objects.annotate(sitemap_count=Count("sitemap")).filter(
        sitemap_count__gt=0
    )

    emails_scheduled = 0
    profiles_checked = 0

    for profile in profiles_with_sitemaps:
        profiles_checked += 1

        try:
            user_timezone = zoneinfo.ZoneInfo(profile.timezone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            user_timezone = zoneinfo.ZoneInfo("UTC")
            logger.warning(
                "Invalid timezone for profile, using UTC",
                email=profile.user.email,
                profile_id=profile.id,
                timezone=profile.timezone,
            )

        current_time_in_user_tz = timezone.now().astimezone(user_timezone)

        preferred_email_time = profile.preferred_email_time or time(9, 0)

        last_email = EmailSent.objects.filter(profile=profile).order_by("-created_at").first()
        last_email_time = last_email.created_at.astimezone(user_timezone) if last_email else None

        if not should_send_email_to_profile(profile, last_email_time, current_time_in_user_tz):
            continue

        current_time_only = current_time_in_user_tz.time()
        time_diff = abs(
            (current_time_only.hour * 60 + current_time_only.minute)
            - (preferred_email_time.hour * 60 + preferred_email_time.minute)
        )

        if time_diff <= 5:
            async_task(
                "core.tasks.send_page_email_to_profile",
                profile_id=profile.id,
                group="Email Scheduling",
            )
            emails_scheduled += 1

    return f"Checked {profiles_checked} profiles, scheduled {emails_scheduled} emails"


def reparse_sitemap(sitemap_id: int) -> str:
    from core.models import Page, Sitemap
    from core.utils import extract_urls_from_sitemap

    try:
        sitemap = Sitemap.objects.get(id=sitemap_id)
    except Sitemap.DoesNotExist:
        return f"Sitemap with id {sitemap_id} not found."

    sitemap_url = sitemap.sitemap_url

    logger.info(
        "Starting sitemap reparse",
        sitemap_id=sitemap_id,
        sitemap_url=sitemap_url,
    )

    try:
        response = requests.get(sitemap_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(
            "Sitemap no longer accessible, marking as inactive",
            sitemap_id=sitemap_id,
            sitemap_url=sitemap_url,
            error=str(e),
        )
        sitemap.is_active = False
        sitemap.save(update_fields=["is_active"])
        return f"Sitemap {sitemap_id} marked as inactive (not accessible)"

    existing_page_urls = set(Page.objects.filter(sitemap=sitemap).values_list("url", flat=True))

    try:
        found_urls = extract_urls_from_sitemap(response.content, sitemap_id=sitemap_id)

        new_urls = found_urls - existing_page_urls
        new_pages_found = 0
        if new_urls:
            for url in new_urls:
                Page.objects.create(profile=sitemap.profile, sitemap=sitemap, url=url)
                new_pages_found += 1
                logger.info(
                    "New page found and added",
                    sitemap_id=sitemap_id,
                    url=url,
                )

        removed_urls = existing_page_urls - found_urls
        if removed_urls:
            pages_to_mark = Page.objects.filter(sitemap=sitemap, url__in=removed_urls)
            pages_to_mark.update(is_active=False)
            logger.info(
                "Pages no longer in sitemap marked as inactive",
                sitemap_id=sitemap_id,
                sitemap_url=sitemap_url,
                removed_count=len(removed_urls),
            )

        still_active_urls = existing_page_urls & found_urls
        if still_active_urls:
            pages_to_reactivate = Page.objects.filter(
                sitemap=sitemap, url__in=still_active_urls, is_active=False
            )
            reactivated_count = pages_to_reactivate.count()
            if reactivated_count > 0:
                pages_to_reactivate.update(is_active=True)
                logger.info(
                    "Pages reactivated (were previously marked inactive)",
                    sitemap_id=sitemap_id,
                    sitemap_url=sitemap_url,
                    reactivated_count=reactivated_count,
                )

        logger.info(
            "Sitemap reparsed successfully",
            sitemap_id=sitemap_id,
            sitemap_url=sitemap_url,
            new_pages=new_pages_found,
            removed_pages=len(removed_urls),
        )

        return (
            f"Reparsed sitemap {sitemap_id}: "
            f"found {new_pages_found} new pages, "
            f"marked {len(removed_urls)} pages as inactive"
        )

    except Exception as e:
        logger.error(
            "Failed to reparse sitemap",
            sitemap_id=sitemap_id,
            sitemap_url=sitemap_url,
            error=str(e),
            exc_info=True,
        )
        return f"Failed to reparse sitemap {sitemap_id}: {str(e)}"


def schedule_sitemap_reparse() -> str:
    from core.models import Sitemap

    all_sitemaps = Sitemap.objects.filter(is_active=True)

    total_sitemaps = all_sitemaps.count()
    tasks_scheduled = 0

    logger.info(
        "Starting to schedule sitemap reparse tasks",
        total_sitemaps=total_sitemaps,
    )

    for sitemap in all_sitemaps:
        async_task(
            "core.tasks.reparse_sitemap",
            sitemap_id=sitemap.id,
            group="Sitemap Reparse",
        )
        tasks_scheduled += 1

        logger.info(
            "Scheduled reparse task for sitemap",
            sitemap_id=sitemap.id,
            sitemap_url=sitemap.sitemap_url,
        )

    logger.info(
        "Finished scheduling sitemap reparse tasks",
        total_sitemaps=total_sitemaps,
        tasks_scheduled=tasks_scheduled,
    )

    return f"Scheduled {tasks_scheduled} sitemap reparse tasks"
