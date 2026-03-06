from django.contrib import admin
from .models import Flow

@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "bot", "is_active", "created")
    list_filter = ("is_active", "tenant")
    search_fields = ("name", "tenant__name")
    readonly_fields = ("id", "created", "modified")
