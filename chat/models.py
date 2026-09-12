"""Data models for the chat application.

A ``ChatSession`` represents one recruiter conversation; ``ChatMessage`` stores
the individual user/assistant turns that belong to that session.
"""
import uuid

from django.db import models
from pgvector.django import VectorField


class ChatSession(models.Model):
    """A persistent, login-free conversation identified by a public UUID."""

    class Meta:
        ordering = ["-last_active"]

    session_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="Session ID",
    )
    hr_name = models.CharField("Recruiter name", max_length=120, blank=True)
    hr_email = models.EmailField("Recruiter email", blank=True)
    company_name = models.CharField("Company name", max_length=160, blank=True)
    interview_requested = models.BooleanField(
        "Interview requested",
        default=False,
        help_text="True once the recruiter has asked to schedule an interview.",
    )
    created_at = models.DateTimeField("Created at", auto_now_add=True)
    last_active = models.DateTimeField("Last active", auto_now=True)

    def __str__(self) -> str:
        return str(self.session_id)


class ChatMessage(models.Model):
    """One user or assistant turn inside a ``ChatSession``."""

    class Sender(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Barkley (assistant)"

    class Meta:
        ordering = ["created_at", "id"]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
    )
    sender = models.CharField("Sender", max_length=16, choices=Sender.choices)
    content = models.TextField("Content")
    created_at = models.DateTimeField("Created at", auto_now_add=True, db_index=True)

    def __str__(self) -> str:
        return f"{self.get_sender_display()}: {self.content[:60]}"


class KnowledgeDocument(models.Model):
    """One piece of BarklAI's ground truth (career profile or a GitHub README).

    Populated by ``python manage.py sync_knowledge``. ``content_hash`` makes the
    sync idempotent (only changed documents are rewritten) and is the natural
    anchor for a future embeddings field once the RAG layer lands.
    """

    class Kind(models.TextChoices):
        PROFILE = "profile", "Career profile"
        GITHUB_README = "github_readme", "GitHub README"

    class Meta:
        ordering = ["kind", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "source"], name="uniq_knowledge_kind_source"
            ),
        ]

    kind = models.CharField(
        "Kind", max_length=32, choices=Kind.choices, default=Kind.PROFILE
    )
    source = models.CharField(
        "Source",
        max_length=200,
        help_text="owner/repo for READMEs, 'profile' for the local career profile.",
    )
    title = models.CharField("Title", max_length=200, blank=True)
    url = models.URLField("URL", blank=True)
    default_branch = models.CharField("Default branch", max_length=100, blank=True)
    content = models.TextField("Content")
    content_hash = models.CharField(
        "Content hash", max_length=64, blank=True, db_index=True
    )
    fetched_at = models.DateTimeField("Last fetched", auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.source}"


class KnowledgeChunk(models.Model):
    """A retrievable slice of a ``KnowledgeDocument`` plus its embedding vector.

    The vector column uses pgvector (1024 dimensions = ``@cf/baai/bge-m3``).
    Retrieval works natively on PostgreSQL; on other backends it falls back to
    a Python cosine similarity so development and the test suite stay portable.
    """

    class Meta:
        ordering = ["document", "ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "ordinal"], name="uniq_chunk_document_ordinal"
            ),
        ]

    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    ordinal = models.PositiveIntegerField("Ordinal")
    content = models.TextField("Content")
    token_count = models.PositiveIntegerField("Tokens", default=0)
    content_hash = models.CharField("Content hash", max_length=64, db_index=True)
    embedding = VectorField("Embedding", dimensions=1024, null=True)
    indexed_at = models.DateTimeField("Indexed at", auto_now=True)

    def __str__(self) -> str:
        return f"{self.document.source} #{self.ordinal}"
