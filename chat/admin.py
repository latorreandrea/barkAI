"""Admin registrations for the chat application."""
from django.contrib import admin

from .models import ChatMessage, ChatSession


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_id",
        "company_name",
        "hr_name",
        "hr_email",
        "interview_requested",
        "created_at",
        "last_active",
    )
    list_filter = ("interview_requested", "created_at")
    search_fields = ("hr_name", "hr_email", "company_name")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "sender", "created_at", "preview")
    list_filter = ("sender", "created_at")
    search_fields = ("content", "session__session_id")

    @admin.display(description="Preview")
    def preview(self, obj: ChatMessage) -> str:
        """Show the first 80 characters of a message in the list view."""
        return obj.content[:80]
