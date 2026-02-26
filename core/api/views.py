from django.http import HttpRequest
from ninja import NinjaAPI

from cleanapp.utils import get_cleanapp_logger
from core.api.auth import session_auth, superuser_api_auth
from core.api.schemas import (
    AddEmailIn,
    AddEmailOut,
    BlogPostIn,
    BlogPostOut,
    BulkUpdatePagesIn,
    BulkUpdatePagesOut,
    DeleteEmailOut,
    DeleteSitemapOut,
    SubmitFeedbackIn,
    SubmitFeedbackOut,
    ToggleEmailIn,
    ToggleEmailOut,
    UserSettingsOut,
)
from core.models import BlogPost, EmailPreference, Feedback, Page, Sitemap

logger = get_cleanapp_logger(__name__)

api = NinjaAPI(docs_url=None)


@api.post("/submit-feedback", response=SubmitFeedbackOut, auth=[session_auth])
def submit_feedback(request: HttpRequest, data: SubmitFeedbackIn):
    profile = request.auth
    try:
        Feedback.objects.create(profile=profile, feedback=data.feedback, page=data.page)
        return {"status": True, "message": "Feedback submitted successfully"}
    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e), profile_id=profile.id)
        return {"status": False, "message": "Failed to submit feedback. Please try again."}


@api.post("/blog-posts/submit", response=BlogPostOut, auth=[superuser_api_auth])
def submit_blog_post(request: HttpRequest, data: BlogPostIn):
    profile = request.auth

    if not profile or not getattr(profile.user, "is_superuser", False):
        return BlogPostOut(status="error", message="Forbidden: superuser access required."), 403

    try:
        BlogPost.objects.create(
            title=data.title,
            description=data.description,
            slug=data.slug,
            tags=data.tags,
            content=data.content,
            status=data.status,
            # icon and image are ignored for now (file upload not handled)
        )
        return BlogPostOut(status="success", message="Blog post submitted successfully.")
    except Exception as e:
        return BlogPostOut(status="failure", message=f"Failed to submit blog post: {str(e)}")


@api.get("/user/settings", response=UserSettingsOut, auth=[session_auth])
def user_settings(request: HttpRequest):
    profile = request.auth
    try:
        profile_data = {
            "has_pro_subscription": profile.has_active_subscription,
        }
        data = {"profile": profile_data}

        return data
    except Exception as e:
        logger.error(
            "Error fetching user settings",
            error=str(e),
            profile_id=profile.id,
            exc_info=True,
        )
        return {"profile": {"has_pro_subscription": False}}


@api.delete("/sitemaps/{sitemap_id}", response=DeleteSitemapOut, auth=[session_auth])
def delete_sitemap(request: HttpRequest, sitemap_id: int):
    profile = request.auth
    try:
        sitemap = Sitemap.objects.get(id=sitemap_id, profile=profile)

        if not sitemap.is_active:
            return {"success": False, "message": "Sitemap is already archived"}

        sitemap.is_active = False
        sitemap.save(update_fields=["is_active"])
        Page.objects.filter(sitemap=sitemap, is_active=True).update(is_active=False)

        logger.info(
            "Sitemap archived",
            profile_id=profile.id,
            email=profile.user.email,
            sitemap_id=sitemap_id,
            sitemap_url=sitemap.sitemap_url,
        )

        return {"success": True, "message": "Sitemap archived successfully"}
    except Sitemap.DoesNotExist:
        logger.warning(
            "Sitemap not found for archive",
            profile_id=profile.id,
            email=profile.user.email,
            sitemap_id=sitemap_id,
        )
        return {"success": False, "message": "Sitemap not found"}
    except Exception as e:
        logger.error(
            "Failed to archive sitemap",
            error=str(e),
            profile_id=profile.id,
            sitemap_id=sitemap_id,
            exc_info=True,
        )
        return {"success": False, "message": "Failed to archive sitemap"}


@api.post("/pages/bulk-update", response=BulkUpdatePagesOut, auth=[session_auth])
def bulk_update_pages(request: HttpRequest, data: BulkUpdatePagesIn):
    profile = request.auth
    try:
        pages = Page.objects.filter(id__in=data.page_ids, profile=profile)

        if not pages.exists():
            logger.warning(
                "No pages found for bulk update",
                profile_id=profile.id,
                email=profile.user.email,
                page_ids=data.page_ids,
            )
            return {"success": False, "message": "No pages found", "updated_count": 0}

        updated_count = pages.update(needs_review=data.needs_review)

        action = (
            "marked as no need to review" if not data.needs_review else "marked as need to review"
        )
        return {
            "success": True,
            "message": f"{updated_count} page(s) {action}",
            "updated_count": updated_count,
        }
    except Exception as e:
        logger.error(
            "Failed to bulk update pages",
            error=str(e),
            profile_id=profile.id,
            page_ids=data.page_ids,
            exc_info=True,
        )
        return {"success": False, "message": "Failed to update pages", "updated_count": 0}


@api.post("/emails/add", response=AddEmailOut, auth=[session_auth])
def add_email(request: HttpRequest, data: AddEmailIn):
    profile = request.auth
    try:
        email_address = data.email_address.strip().lower()

        if EmailPreference.objects.filter(profile=profile, email_address=email_address).exists():
            return {"success": False, "message": "This email address is already added"}

        email_pref = EmailPreference.objects.create(
            profile=profile, email_address=email_address, enabled=True
        )

        logger.info(
            "Email preference added",
            profile_id=profile.id,
            email=profile.user.email,
            new_email=email_address,
        )

        return {
            "success": True,
            "message": "Email address added successfully",
            "email_id": email_pref.id,
        }
    except Exception as e:
        logger.error("Failed to add email", error=str(e), profile_id=profile.id, exc_info=True)
        return {"success": False, "message": "Failed to add email address"}


@api.patch("/emails/{email_id}", response=ToggleEmailOut, auth=[session_auth])
def toggle_email(request: HttpRequest, email_id: int, data: ToggleEmailIn):
    profile = request.auth
    try:
        email_pref = EmailPreference.objects.get(id=email_id, profile=profile)
        email_pref.enabled = data.enabled
        email_pref.save(update_fields=["enabled"])

        status = "enabled" if data.enabled else "disabled"
        logger.info(
            f"Email preference {status}",
            profile_id=profile.id,
            email=profile.user.email,
            email_id=email_id,
            email_address=email_pref.email_address,
        )

        return {"success": True, "message": f"Email notifications {status}"}
    except EmailPreference.DoesNotExist:
        logger.warning(
            "Email preference not found for toggle",
            profile_id=profile.id,
            email_id=email_id,
        )
        return {"success": False, "message": "Email address not found"}
    except Exception as e:
        logger.error(
            "Failed to toggle email",
            error=str(e),
            profile_id=profile.id,
            email_id=email_id,
            exc_info=True,
        )
        return {"success": False, "message": "Failed to update email address"}


@api.delete("/emails/{email_id}", response=DeleteEmailOut, auth=[session_auth])
def delete_email(request: HttpRequest, email_id: int):
    profile = request.auth
    try:
        email_pref = EmailPreference.objects.get(id=email_id, profile=profile)
        email_address = email_pref.email_address
        email_pref.delete()

        logger.info(
            "Email preference deleted",
            profile_id=profile.id,
            email=profile.user.email,
            email_id=email_id,
            deleted_email=email_address,
        )

        return {"success": True, "message": "Email address removed successfully"}
    except EmailPreference.DoesNotExist:
        logger.warning(
            "Email preference not found for deletion",
            profile_id=profile.id,
            email_id=email_id,
        )
        return {"success": False, "message": "Email address not found"}
    except Exception as e:
        logger.error(
            "Failed to delete email",
            error=str(e),
            profile_id=profile.id,
            email_id=email_id,
            exc_info=True,
        )
        return {"success": False, "message": "Failed to delete email address"}
