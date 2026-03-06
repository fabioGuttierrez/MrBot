from django.contrib import admin
from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "is_active", "max_bots", "max_sessions", "created")
    list_filter = ("plan", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("id", "created", "modified")
    fieldsets = (
        (None, {"fields": ("id", "name", "slug", "logo", "plan", "is_active")}),
        ("Limites", {"fields": ("max_bots", "max_sessions", "max_messages_month")}),
        ("Atendimento", {"fields": (
            "business_hours_start",
            "business_hours_end",
            "out_of_hours_message",
            "message_concat_delay",
        )}),
        ("Datas", {"fields": ("created", "modified")}),
    )
