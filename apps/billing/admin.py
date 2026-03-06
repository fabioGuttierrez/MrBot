from django.contrib import admin
from .models import Subscription

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "plan", "started_at", "expires_at", "is_active")
    list_filter = ("plan", "is_active")
    readonly_fields = ("id", "created", "modified")
