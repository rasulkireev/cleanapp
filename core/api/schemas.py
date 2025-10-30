from ninja import Schema

from core.choices import BlogPostStatus


class SubmitFeedbackIn(Schema):
    feedback: str
    page: str


class SubmitFeedbackOut(Schema):
    success: bool
    message: str


class BlogPostIn(Schema):
    title: str
    description: str = ""
    slug: str
    tags: str = ""
    content: str
    icon: str | None = None  # URL or base64 string
    image: str | None = None  # URL or base64 string
    status: BlogPostStatus = BlogPostStatus.DRAFT


class BlogPostOut(Schema):
    status: str  # API response status: 'success' or 'failure'
    message: str


class ProfileSettingsOut(Schema):
    has_pro_subscription: bool


class UserSettingsOut(Schema):
    profile: ProfileSettingsOut


class DeleteSitemapOut(Schema):
    success: bool
    message: str


class BulkUpdatePagesIn(Schema):
    page_ids: list[int]
    needs_review: bool


class BulkUpdatePagesOut(Schema):
    success: bool
    message: str
    updated_count: int


class AddEmailIn(Schema):
    email_address: str


class AddEmailOut(Schema):
    success: bool
    message: str
    email_id: int | None = None


class ToggleEmailIn(Schema):
    enabled: bool


class ToggleEmailOut(Schema):
    success: bool
    message: str


class DeleteEmailOut(Schema):
    success: bool
    message: str
