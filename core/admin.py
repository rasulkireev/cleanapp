
from django.contrib import admin

from core.models import BlogPost, Sitemap, Page, Email


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'slug', 'content')


@admin.register(Sitemap)
class SitemapAdmin(admin.ModelAdmin):
    list_display = ('sitemap_url', 'profile', 'pages_per_review', 'review_cadence', 'created_at')
    list_filter = ('review_cadence', 'created_at')
    search_fields = ('sitemap_url', 'profile__user__email')


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ('url', 'profile', 'sitemap', 'needs_review', 'reviewed', 'reviewed_at', 'created_at')
    list_filter = ('needs_review', 'reviewed', 'created_at')
    search_fields = ('url', 'profile__user__email')
    list_editable = ('needs_review',)


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'profile')
    list_filter = ('created_at',)
    search_fields = ('profile__user__email',)
