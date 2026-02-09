from urllib.parse import urlencode

import stripe
from allauth.account.models import EmailAddress
from allauth.account.utils import send_email_confirmation
from allauth.account.views import SignupView
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, TemplateView, UpdateView
from django_q.tasks import async_task

from cleanapp.utils import get_cleanapp_logger
from core.choices import ProfileStates
from core.forms import ProfileUpdateForm, SitemapForm, SitemapSettingsForm
from core.models import BlogPost, Feedback, Page, Profile, Sitemap
from core.stripe_webhooks import EVENT_HANDLERS

stripe.api_key = settings.STRIPE_SECRET_KEY


logger = get_cleanapp_logger(__name__)


def get_price_id_for_plan(plan):
    plan_key = (plan or "").lower()
    price_id = settings.STRIPE_PRICE_IDS.get(plan_key) or None
    return price_id


def get_or_create_stripe_customer(profile, user):
    if profile.stripe_customer_id:
        try:
            return stripe.Customer.retrieve(profile.stripe_customer_id)
        except stripe.error.InvalidRequestError as exc:
            logger.warning(
                "Stripe customer lookup failed",
                profile_id=profile.id,
                stripe_customer_id=profile.stripe_customer_id,
                error=str(exc),
            )

    customer = stripe.Customer.create(
        email=user.email,
        name=user.get_full_name() or user.username,
        metadata={"user_id": user.id},
    )
    profile.stripe_customer_id = customer.id
    profile.save(update_fields=["stripe_customer_id"])
    return customer


@csrf_exempt
def stripe_webhook_view(request):
    logger.info("Stripe webhook received", request=request)

    if request.method != "POST":
        return HttpResponse(status=405)

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Stripe webhook secret not configured")
        return HttpResponse(status=500)

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    if not sig_header:
        return HttpResponseBadRequest("Missing Stripe-Signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return HttpResponseBadRequest("Invalid payload")
    except stripe.error.SignatureVerificationError:
        return HttpResponseBadRequest("Invalid signature")

    event_id = event.get("id")
    if event_id:
        cache_key = f"stripe_event:{event_id}"
        if cache.get(cache_key):
            logger.info(
                "Duplicate Stripe webhook received",
                event_type=event.get("type"),
                event_id=event_id,
            )
            return HttpResponse(status=200)

    handler = EVENT_HANDLERS.get(event.get("type"))
    if handler:
        handler(event)
    else:
        logger.info(
            "Unhandled Stripe webhook",
            event_type=event.get("type"),
            event_id=event.get("id"),
        )

    if event_id:
        cache.set(cache_key, True, timeout=60 * 60 * 24)

    return HttpResponse(status=200)


class LandingPageView(TemplateView):
    template_name = "pages/landing-page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(self.request, "Thanks for subscribing, I hope you enjoy the app!")
            context["show_confetti"] = True
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        if self.request.user.is_authenticated and settings.POSTHOG_API_KEY:
            user = self.request.user
            profile = user.profile

            async_task(
                "core.tasks.try_create_posthog_alias",
                profile_id=profile.id,
                cookies=self.request.COOKIES,
                source_function="LandingPageView - get_context_data",
                group="Create Posthog Alias",
            )

        return context


class HomeView(LoginRequiredMixin, SuccessMessageMixin, TemplateView):
    login_url = "account_login"
    template_name = "pages/home.html"
    success_message = "Sitemap URL added successfully"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = SitemapForm()
        context["sitemaps"] = Sitemap.objects.filter(profile=self.request.user.profile).order_by(
            "-created_at"
        )
        return context

    def post(self, request, *args, **kwargs):
        form = SitemapForm(request.POST)
        if form.is_valid():
            sitemap = form.save(commit=False)
            sitemap.profile = request.user.profile
            sitemap.save()

            logger.info(
                "Sitemap URL added",
                profile_id=request.user.profile.id,
                email=request.user.email,
                sitemap_url=sitemap.sitemap_url,
            )

            messages.success(request, self.success_message)
            return redirect("home")
        else:
            context = self.get_context_data(**kwargs)
            context["form"] = form
            return self.render_to_response(context)


class SitemapDetailView(LoginRequiredMixin, DetailView):
    login_url = "account_login"
    model = Sitemap
    template_name = "pages/sitemap_detail.html"
    context_object_name = "sitemap"

    def get_queryset(self):
        return Sitemap.objects.filter(profile=self.request.user.profile)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pages"] = Page.objects.filter(sitemap=self.object).order_by("-needs_review", "url")
        return context


class AccountSignupView(SignupView):
    template_name = "account/signup.html"

    def form_valid(self, form):
        response = super().form_valid(form)

        user = self.user
        profile = user.profile

        async_task(
            "core.tasks.try_create_posthog_alias",
            profile_id=profile.id,
            cookies=self.request.COOKIES,
            source_function="AccountSignupView - form_valid",
            group="Create Posthog Alias",
        )

        async_task(
            "core.tasks.track_event",
            profile_id=profile.id,
            event_name="user_signed_up",
            properties={
                "$set": {
                    "email": profile.user.email,
                    "username": profile.user.username,
                },
            },
            source_function="AccountSignupView - form_valid",
            group="Track Event",
        )

        return response


class UserSettingsView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    login_url = "account_login"
    model = Profile
    form_class = ProfileUpdateForm
    success_message = "User Profile Updated"
    success_url = reverse_lazy("settings")
    template_name = "pages/user-settings.html"

    def get_object(self):
        return self.request.user.profile

    def get_context_data(self, **kwargs):
        from core.forms import get_timezone_list
        from core.models import EmailPreference

        context = super().get_context_data(**kwargs)
        user = self.request.user

        payment_status = self.request.GET.get("payment")
        if payment_status == "success":
            messages.success(self.request, "Thanks for subscribing, I hope you enjoy the app!")
        elif payment_status == "failed":
            messages.error(self.request, "Something went wrong with the payment.")

        primary_email = EmailAddress.objects.get_for_user(user, user.email)
        context["email_verified"] = primary_email.verified
        context["resend_confirmation_url"] = reverse("resend_confirmation")
        context["has_subscription"] = user.profile.has_active_subscription

        sitemaps = Sitemap.objects.filter(profile=user.profile).order_by("-created_at")
        sitemap_forms = {}
        for sitemap in sitemaps:
            sitemap_forms[sitemap.id] = SitemapSettingsForm(
                instance=sitemap, prefix=f"sitemap_{sitemap.id}"
            )

        context["sitemaps"] = sitemaps
        context["sitemap_forms"] = sitemap_forms
        context["timezones"] = get_timezone_list()
        context["email_preferences"] = EmailPreference.objects.filter(
            profile=user.profile
        ).order_by("-created_at")

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        profile_form = self.get_form()

        sitemaps = Sitemap.objects.filter(profile=request.user.profile)
        sitemap_forms = []
        for sitemap in sitemaps:
            sitemap_forms.append(
                (
                    sitemap,
                    SitemapSettingsForm(
                        request.POST, instance=sitemap, prefix=f"sitemap_{sitemap.id}"
                    ),
                )
            )

        profile_valid = profile_form.is_valid()
        sitemap_forms_valid = all(form.is_valid() for _, form in sitemap_forms)

        if profile_valid and sitemap_forms_valid:
            profile_form.save()

            logger.info(
                "User profile updated", profile_id=request.user.profile.id, email=request.user.email
            )

            updated_count = 0
            for sitemap, form in sitemap_forms:
                form.save()
                updated_count += 1

                logger.info(
                    "Sitemap settings updated",
                    profile_id=request.user.profile.id,
                    email=request.user.email,
                    sitemap_id=sitemap.id,
                    pages_per_review=sitemap.pages_per_review,
                    review_cadence=sitemap.review_cadence,
                )

            messages.success(request, "Settings updated successfully")
            return redirect(self.get_success_url())
        else:
            return self.form_invalid(profile_form)


@login_required
def resend_confirmation_email(request):
    user = request.user
    send_email_confirmation(request, user, EmailAddress.objects.get_for_user(user, user.email))

    return redirect("settings")


class PricingView(TemplateView):
    template_name = "pages/pricing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_authenticated:
            try:
                profile = self.request.user.profile
                context["has_pro_subscription"] = profile.has_active_subscription
            except Profile.DoesNotExist:
                context["has_pro_subscription"] = False
        else:
            context["has_pro_subscription"] = False

        return context


@login_required
@require_POST
def create_checkout_session(request, pk, plan):
    user = request.user
    profile = user.profile
    price_id = get_price_id_for_plan(plan)
    if not price_id:
        logger.warning("Stripe price id not configured for plan", plan=plan, user_id=user.id)
        messages.error(request, "Unable to find pricing for the selected plan.")
        return redirect("pricing")

    try:
        customer = get_or_create_stripe_customer(profile, user)
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe customer setup failed",
            profile_id=profile.id,
            error=str(exc),
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    base_success_url = request.build_absolute_uri(reverse("home"))
    base_cancel_url = request.build_absolute_uri(reverse("home"))

    success_params = {"payment": "success"}
    success_url = f"{base_success_url}?{urlencode(success_params)}"

    cancel_params = {"payment": "failed"}
    cancel_url = f"{base_cancel_url}?{urlencode(cancel_params)}"

    session_params = {
        "customer": customer.id,
        "payment_method_types": ["card"],
        "allow_promotion_codes": True,
        "automatic_tax": {"enabled": True},
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "customer_update": {
            "address": "auto",
        },
        "client_reference_id": str(user.id),
        "metadata": {
            "user_id": user.id,
            "pk": pk,
            "price_id": price_id,
            "plan": plan,
        },
        "subscription_data": {"metadata": {"user_id": user.id, "plan": plan}},
    }

    try:
        checkout_session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe checkout session creation failed",
            profile_id=profile.id,
            plan=plan,
            error=str(exc),
        )
        messages.error(request, "Unable to start checkout. Please try again.")
        return redirect("pricing")

    return redirect(checkout_session.url, code=303)


@login_required
def create_customer_portal_session(request):
    user = request.user
    profile = user.profile
    if not profile.stripe_customer_id:
        messages.error(request, "No Stripe customer found for this account.")
        return redirect("pricing")

    try:
        session = stripe.billing_portal.Session.create(
            customer=profile.stripe_customer_id,
            return_url=request.build_absolute_uri(reverse("home")),
        )
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe portal session creation failed",
            profile_id=profile.id,
            stripe_customer_id=profile.stripe_customer_id,
            error=str(exc),
        )
        messages.error(request, "Unable to open the billing portal. Please try again.")
        return redirect("pricing")

    return redirect(session.url, code=303)


class BlogView(ListView):
    model = BlogPost
    template_name = "blog/blog_posts.html"
    context_object_name = "blog_posts"


class BlogPostView(DetailView):
    model = BlogPost
    template_name = "blog/blog_post.html"
    context_object_name = "blog_post"


@login_required
def review_page_redirect(request, page_id):
    from django.utils import timezone

    try:
        page = Page.objects.get(id=page_id, profile=request.user.profile)

        page.reviewed = True
        page.reviewed_at = timezone.now()
        page.save(update_fields=["reviewed", "reviewed_at"])

        return redirect(page.url)
    except Page.DoesNotExist:
        messages.error(request, "Page not found or you don't have permission to access it.")
        return redirect("home")


class AdminPanelView(UserPassesTestMixin, TemplateView):
    template_name = "pages/admin-panel.html"
    login_url = "account_login"

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, "You don't have permission to access this page.")
        return redirect("home")

    def get_context_data(self, **kwargs):
        from datetime import timedelta

        from django.contrib.auth.models import User
        from django.db.models import Count
        from django.utils import timezone

        context = super().get_context_data(**kwargs)

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        total_users = User.objects.count()
        total_profiles = Profile.objects.count()
        total_sitemaps = Sitemap.objects.count()
        total_pages = Page.objects.count()
        total_feedback = Feedback.objects.count()

        new_users_week = User.objects.filter(date_joined__gte=week_ago).count()
        new_users_month = User.objects.filter(date_joined__gte=month_ago).count()

        subscribed_users = Profile.objects.filter(
            state__in=[ProfileStates.SUBSCRIBED, ProfileStates.CANCELLED]
        ).count()

        pages_reviewed = Page.objects.filter(reviewed=True).count()
        pages_unreviewed = Page.objects.filter(reviewed=False).count()

        recent_users = User.objects.select_related("profile").order_by("-date_joined")[:10]
        recent_feedback = Feedback.objects.select_related("profile__user").order_by("-created_at")[
            :10
        ]
        recent_sitemaps = Sitemap.objects.select_related("profile__user").order_by("-created_at")[
            :10
        ]

        top_users_by_pages = (
            Profile.objects.annotate(page_count=Count("pages"))
            .filter(page_count__gt=0)
            .order_by("-page_count")[:10]
        )

        context.update(
            {
                "total_users": total_users,
                "total_profiles": total_profiles,
                "total_sitemaps": total_sitemaps,
                "total_pages": total_pages,
                "total_feedback": total_feedback,
                "new_users_week": new_users_week,
                "new_users_month": new_users_month,
                "subscribed_users": subscribed_users,
                "pages_reviewed": pages_reviewed,
                "pages_unreviewed": pages_unreviewed,
                "recent_users": recent_users,
                "recent_feedback": recent_feedback,
                "recent_sitemaps": recent_sitemaps,
                "top_users_by_pages": top_users_by_pages,
            }
        )

        logger.info(
            "Admin panel accessed",
            email=self.request.user.email,
            profile_id=self.request.user.profile.id,
        )

        return context


@staff_member_required
def send_test_email(request):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect("home")

    if request.method == "POST":
        profile_id = request.user.profile.id

        async_task(
            "core.tasks.send_page_email_to_profile",
            profile_id=profile_id,
            group="Send Test Email",
        )

        logger.info(
            "Test email queued",
            email=request.user.email,
            profile_id=profile_id,
        )

        messages.success(request, f"Test email queued and will be sent to {request.user.email}!")

    return redirect("admin_panel")


@staff_member_required
def trigger_schedule_review_emails(request):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect("home")

    if request.method == "POST":
        async_task(
            "core.tasks.schedule_review_emails",
            group="Schedule Review Emails",
        )

        logger.info(
            "Schedule review emails task triggered",
            email=request.user.email,
            profile_id=request.user.profile.id,
        )

        messages.success(request, "Review email scheduling task has been queued!")

    return redirect("admin_panel")


@staff_member_required
def trigger_schedule_sitemap_reparse(request):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect("home")

    if request.method == "POST":
        async_task(
            "core.tasks.schedule_sitemap_reparse",
            group="Schedule Sitemap Reparse",
        )

        logger.info(
            "Schedule sitemap reparse task triggered",
            email=request.user.email,
            profile_id=request.user.profile.id,
        )

        messages.success(request, "Sitemap reparse scheduling task has been queued!")

    return redirect("admin_panel")
