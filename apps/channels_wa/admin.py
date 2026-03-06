from django.contrib import admin
from .models import WhatsAppSession

@admin.register(WhatsAppSession)
class WhatsAppSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "phone_number", "status", "is_active", "created")
    list_filter = ("status", "is_active", "tenant")
    search_fields = ("name", "phone_number", "instance_id")
    readonly_fields = ("id", "created", "modified")
