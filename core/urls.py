from django.urls import path

from core import views
from core.api.views import api

urlpatterns = [
    # pages
    path("", views.LandingPageView.as_view(), name="landing_page"),
    path("home", views.HomeView.as_view(), name="home"),
    path("sitemap/<int:pk>", views.SitemapDetailView.as_view(), name="sitemap_detail"),
    path("settings", views.UserSettingsView.as_view(), name="settings"),
    path("admin-panel", views.AdminPanelView.as_view(), name="admin_panel"),
    # blog
    path("blog", views.BlogView.as_view(), name="blog_posts"),
    path("blog/<slug:slug>", views.BlogPostView.as_view(), name="blog_post"),

    # app
    path("api/", api.urls),
    # utils
    path("resend-confirmation/", views.resend_confirmation_email, name="resend_confirmation"),
    path("review-page/<int:page_id>/", views.review_page_redirect, name="review_page_redirect"),
    path("send-test-email/", views.send_test_email, name="send_test_email"),
    path("trigger-schedule-review-emails/", views.trigger_schedule_review_emails, name="trigger_schedule_review_emails"),
    # payments
    path("pricing", views.PricingView.as_view(), name="pricing"),
    path(
        "create-checkout-session/<int:pk>/<str:plan>/",
        views.create_checkout_session,
        name="user_upgrade_checkout_session",
    ),
    path(
      "create-customer-portal/",
      views.create_customer_portal_session,
      name="create_customer_portal_session"
    ),

]
