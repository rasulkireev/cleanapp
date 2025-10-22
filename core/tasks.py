import json
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from datetime import time

import posthog


import requests
from django.conf import settings
from django.utils import timezone
from django.db.models import Count
from django_q.tasks import async_task
import zoneinfo

from core.models import Profile
from cleanapp.utils import get_cleanapp_logger

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
    profile_id: int, from_state: str, to_state: str, metadata: dict = None
) -> None:
    from core.models import Profile, ProfileStateTransition

    base_log_data = {
        "profile_id": profile_id,
        "from_state": from_state,
        "to_state": to_state,
        "metadata": metadata,
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


def process_sitemap_pages(sitemap_id: int) -> str:
    from core.models import Sitemap, Page

    try:
        sitemap = Sitemap.objects.get(id=sitemap_id)
    except Sitemap.DoesNotExist:
        return f"Sitemap with id {sitemap_id} not found."

    try:
        response = requests.get(sitemap.sitemap_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        return f"Failed to fetch sitemap: {str(e)}"

    try:
        root = ET.fromstring(response.content)
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = root.findall('.//ns:url/ns:loc', namespace)

        if not urls:
            urls = root.findall('.//url/loc')

        pages_created = 0
        pages_skipped = 0

        for url_element in urls:
            url = url_element.text
            if not url:
                continue

            existing_page = Page.objects.filter(
                sitemap=sitemap,
                url=url
            ).first()

            if existing_page:
                pages_skipped += 1
                continue

            Page.objects.create(
                profile=sitemap.profile,
                sitemap=sitemap,
                url=url
            )
            pages_created += 1

        return f"Processed sitemap {sitemap_id}: created {pages_created} pages, skipped {pages_skipped} existing pages"

    except ET.ParseError as e:
        return f"Failed to parse sitemap XML: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


def send_page_email_to_profile(profile_id: int) -> str:
    from core.models import Profile, Page, Sitemap, Email
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    from django.urls import reverse
    from django.db.models import Count

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
            sitemap=sitemap,
            reviewed=False,
            needs_review=True
        ).order_by('?')[:sitemap.pages_per_review]

        if unreviewed_pages.exists():
            pages_list = []
            for page in unreviewed_pages:
                review_url = f"{settings.SITE_URL}{reverse('review_page_redirect', kwargs={'page_id': page.id})}"
                page.review_url = review_url
                pages_list.append(page)

            sitemaps_with_pages.append({
                'sitemap': sitemap,
                'pages': pages_list,
                'pages_count': len(pages_list)
            })
            total_pages_collected += len(pages_list)

    if not sitemaps_with_pages:
        return f"No unreviewed pages found for profile {profile_id}."

    context = {
        'profile': profile,
        'user': profile.user,
        'sitemaps_with_pages': sitemaps_with_pages,
        'total_sitemaps': len(sitemaps_with_pages),
        'total_pages': total_pages_collected,
    }

    html_content = render_to_string("emails/page_review.html", context)
    text_content = strip_tags(html_content)

    subject = f"Time to Review {total_pages_collected} Page{'s' if total_pages_collected > 1 else ''}"

    email = EmailMultiAlternatives(
        subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [profile.user.email],
    )
    email.attach_alternative(html_content, "text/html")

    try:
        email.send()
        Email.objects.create(profile=profile)
        logger.info(
            "Page review email sent",
            email=profile.user.email,
            profile_id=profile_id,
            total_sitemaps=len(sitemaps_with_pages),
            total_pages=total_pages_collected
        )
        return f"Successfully sent page review email to {profile.user.email} with {total_pages_collected} pages from {len(sitemaps_with_pages)} sitemaps"
    except Exception as e:
        logger.error(
            "Failed to send page review email",
            email=profile.user.email,
            profile_id=profile_id,
            error=str(e),
            exc_info=True
        )
        return f"Failed to send email: {str(e)}"


def schedule_review_emails() -> str:
    from core.models import Profile, Email
    from core.utils import should_send_email_to_profile

    profiles_with_sitemaps = Profile.objects.annotate(
        sitemap_count=Count('sitemap')
    ).filter(sitemap_count__gt=0)

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
                timezone=profile.timezone
            )

        current_time_in_user_tz = timezone.now().astimezone(user_timezone)

        preferred_email_time = profile.preferred_email_time or time(9, 0)

        last_email = Email.objects.filter(profile=profile).order_by('-created_at').first()
        last_email_time = last_email.created_at.astimezone(user_timezone) if last_email else None

        if not should_send_email_to_profile(profile, last_email_time, current_time_in_user_tz):
            continue

        current_time_only = current_time_in_user_tz.time()
        time_diff = abs(
            (current_time_only.hour * 60 + current_time_only.minute) -
            (preferred_email_time.hour * 60 + preferred_email_time.minute)
        )

        if time_diff <= 5:
            async_task(
                'core.tasks.send_page_email_to_profile',
                profile_id=profile.id,
                group="Email Scheduling"
            )
            emails_scheduled += 1

    return f"Checked {profiles_checked} profiles, scheduled {emails_scheduled} emails"
