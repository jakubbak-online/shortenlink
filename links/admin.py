from django.contrib import admin

from links.models import ClickEvent, DailyStat, Link


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("code", "target_url", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "target_url", "title")
    readonly_fields = ("created_at",)


@admin.register(ClickEvent)
class ClickEventAdmin(admin.ModelAdmin):
    list_display = ("link", "created_at", "device_type", "country", "referer_domain")
    list_filter = ("device_type", "country")
    readonly_fields = (
        "link",
        "created_at",
        "ip_hash",
        "country",
        "referer_domain",
        "device_type",
        "browser",
        "os",
    )


@admin.register(DailyStat)
class DailyStatAdmin(admin.ModelAdmin):
    list_display = ("link", "date", "clicks", "unique_visitors")
    list_filter = ("date",)
    readonly_fields = ("link", "date", "clicks", "unique_visitors")
