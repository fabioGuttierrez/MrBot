from django.contrib import admin
from .models import Bot

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "department", "model", "is_active", "created")
    list_filter = ("department", "is_active", "tenant")
    search_fields = ("name", "tenant__name")
    readonly_fields = ("id", "created", "modified")
