from django.contrib import admin

from links.models import Link


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("code", "target_url", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "target_url", "title")
    readonly_fields = ("created_at",)
