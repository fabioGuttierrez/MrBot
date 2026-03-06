from django.contrib import admin
from .models import Conversation, Message

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("contact", "tenant", "status", "bot", "assigned_to", "last_message_at")
    list_filter = ("status", "tenant")
    search_fields = ("contact__name", "contact__phone")
    readonly_fields = ("id", "created", "modified")

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "direction", "is_concatenated", "created")
    list_filter = ("direction", "is_concatenated")
    readonly_fields = ("id", "created", "modified")
