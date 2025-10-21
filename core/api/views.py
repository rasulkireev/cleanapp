from django.http import HttpRequest
from ninja import NinjaAPI
from ninja.errors import HttpError

from core.api.auth import session_auth, superuser_api_auth
from core.models import Feedback, BlogPost, Sitemap, Page
from core.api.schemas import (
    SubmitFeedbackIn,
    SubmitFeedbackOut,
    BlogPostIn,
    BlogPostOut,
    ProfileSettingsOut,
    UserSettingsOut,
    DeleteSitemapOut,
    BulkUpdatePagesIn,
    BulkUpdatePagesOut,
)

from cleanapp.utils import get_cleanapp_logger

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
        raise HttpError(500, "An unexpected error occurred.")


@api.delete("/sitemaps/{sitemap_id}", response=DeleteSitemapOut, auth=[session_auth])
def delete_sitemap(request: HttpRequest, sitemap_id: int):
    profile = request.auth
    try:
        sitemap = Sitemap.objects.get(id=sitemap_id, profile=profile)
        sitemap_url = sitemap.sitemap_url
        sitemap.delete()

        logger.info(
            "Sitemap deleted",
            profile_id=profile.id,
            email=profile.user.email,
            sitemap_id=sitemap_id,
            sitemap_url=sitemap_url
        )

        return {"success": True, "message": "Sitemap deleted successfully"}
    except Sitemap.DoesNotExist:
        logger.warning(
            "Sitemap not found for deletion",
            profile_id=profile.id,
            email=profile.user.email,
            sitemap_id=sitemap_id
        )
        raise HttpError(404, "Sitemap not found")
    except Exception as e:
        logger.error(
            "Failed to delete sitemap",
            error=str(e),
            profile_id=profile.id,
            sitemap_id=sitemap_id,
            exc_info=True
        )
        raise HttpError(500, "Failed to delete sitemap")


@api.post("/pages/bulk-update", response=BulkUpdatePagesOut, auth=[session_auth])
def bulk_update_pages(request: HttpRequest, data: BulkUpdatePagesIn):
    profile = request.auth
    try:
        pages = Page.objects.filter(
            id__in=data.page_ids,
            profile=profile
        )

        if not pages.exists():
            logger.warning(
                "No pages found for bulk update",
                profile_id=profile.id,
                email=profile.user.email,
                page_ids=data.page_ids
            )
            raise HttpError(404, "No pages found")

        updated_count = pages.update(needs_review=data.needs_review)

        action = "marked as no need to review" if not data.needs_review else "marked as need to review"
        return {
            "success": True,
            "message": f"{updated_count} page(s) {action}",
            "updated_count": updated_count
        }
    except HttpError:
        raise
    except Exception as e:
        logger.error(
            "Failed to bulk update pages",
            error=str(e),
            profile_id=profile.id,
            page_ids=data.page_ids,
            exc_info=True
        )
        raise HttpError(500, "Failed to update pages")
