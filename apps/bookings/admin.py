from django.contrib import admin
from .models import Resource, Booking, BookingStatus


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "booking_type", "max_bookings_per_day", "is_active", "tenant"]
    list_filter = ["tenant", "booking_type", "is_active", "category"]
    search_fields = ["name", "description"]
    list_editable = ["is_active", "max_bookings_per_day"]
    fieldsets = (
        (None, {
            "fields": ("tenant", "name", "category", "booking_type", "max_bookings_per_day", "is_active", "description"),
        }),
        ("Configuração de Horário (apenas time_slot)", {
            "classes": ("collapse",),
            "fields": ("slot_duration_minutes", "working_hours_start", "working_hours_end"),
        }),
    )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["resource", "event_date", "client_display", "status", "tenant", "created"]
    list_filter = ["tenant", "status", "resource__category", "event_date"]
    search_fields = ["client_name", "contact__name", "resource__name", "notes"]
    readonly_fields = ["created", "modified", "id"]
    date_hierarchy = "event_date"
    list_editable = ["status"]
    raw_id_fields = ["contact", "conversation"]

    @admin.display(description="Cliente")
    def client_display(self, obj):
        if obj.contact:
            return obj.contact.name or obj.contact.phone
        return obj.client_name or "—"
