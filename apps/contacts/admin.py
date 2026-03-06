from django.contrib import admin
from .models import Contact

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("display_name", "phone", "tenant", "stage", "created")
    list_filter = ("stage", "tenant")
    search_fields = ("name", "phone", "email")
    readonly_fields = ("id", "created", "modified")
