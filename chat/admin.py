"""Admin registrations for the chat application."""
from django.contrib import admin

from .models import ChatMessage, ChatSession, KnowledgeChunk, KnowledgeDocument


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


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("source", "kind", "title", "characters", "fetched_at")
    list_filter = ("kind", "fetched_at")
    search_fields = ("source", "title", "content")
    readonly_fields = ("content_hash", "fetched_at")

    @admin.display(description="Chars")
    def characters(self, obj: KnowledgeDocument) -> int:
        """Show how large the stored document is, in characters."""
        return len(obj.content)


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "ordinal", "token_count", "has_embedding", "indexed_at")
    list_filter = ("document__kind", "indexed_at")
    search_fields = ("content", "document__source")
    readonly_fields = ("content_hash", "indexed_at")

    @admin.display(boolean=True, description="Embedded")
    def has_embedding(self, obj: KnowledgeChunk) -> bool:
        """True once the chunk has been embedded by build_index."""
        return obj.embedding is not None
