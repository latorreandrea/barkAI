"""Smoke tests for the barkAI index view and the chat REST API."""
import base64
import json
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import connection
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.views import defaults

from chat.embeddings import EmbeddingError
from chat.models import ChatMessage, ChatSession, KnowledgeChunk, KnowledgeDocument
from chat.services import (
    FALLBACK_NO_KEY,
    FALLBACK_UNREACHABLE,
    generate_reply,
    get_knowledge_text,
)


class IndexViewTests(TestCase):
    def test_index_renders_app_template(self):
        response = self.client.get(reverse("chat:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat/index.html")


@override_settings(GROQ_API_KEY="")  # Force the offline mock: no network in CI.
class ChatApiTests(TestCase):
    HISTORY_URL = "/api/chat/history/{}"
    SEND_URL = "/api/chat/send"

    def test_history_creates_session_if_missing(self):
        session_id = uuid4()
        response = self.client.get(self.HISTORY_URL.format(session_id))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ChatSession.objects.filter(session_id=session_id).exists())
        payload = response.json()
        self.assertEqual(payload["session_id"], str(session_id))
        self.assertEqual(payload["messages"], [])

    def test_history_returns_persisted_messages(self):
        session = ChatSession.objects.create()
        ChatMessage.objects.create(
            session=session, sender=ChatMessage.Sender.USER, content="Hello"
        )
        response = self.client.get(self.HISTORY_URL.format(session.session_id))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["content"], "Hello")

    def test_send_persists_both_turns(self):
        session_id = uuid4()
        response = self.client.post(
            self.SEND_URL,
            data={"session_id": str(session_id), "message": "Hello Barkley!"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["barkley_state"], "speaking")
        self.assertFalse(payload["interview_requested"])
        session = ChatSession.objects.get(session_id=session_id)
        self.assertEqual(session.messages.count(), 2)

    def test_interview_request_flags_session_and_celebrates(self):
        session_id = uuid4()
        response = self.client.post(
            self.SEND_URL,
            data={
                "session_id": str(session_id),
                "message": "I would like to schedule an interview",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["barkley_state"], "celebrating")
        self.assertTrue(payload["interview_requested"])
        session = ChatSession.objects.get(session_id=session_id)
        self.assertTrue(session.interview_requested)


class ErrorPageTests(TestCase):
    """Ensure the project-level error templates render correctly."""

    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(DEBUG=False)
    def test_permission_denied_renders_403(self):
        request = self.factory.get("/private/")
        response = defaults.permission_denied(request, PermissionError("denied"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Error 403", status_code=403)
        self.assertContains(response, "Forbidden", status_code=403)

    @override_settings(DEBUG=False)
    def test_page_not_found_renders_404(self):
        request = self.factory.get("/missing/")
        response = defaults.page_not_found(request, Http404("Not here"))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Error 404", status_code=404)
        self.assertContains(response, "Page Not Found", status_code=404)

    @override_settings(DEBUG=False)
    def test_server_error_renders_500(self):
        request = self.factory.get("/")
        response = defaults.server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Error 500", status_code=500)
        self.assertContains(response, "Internal Server Error", status_code=500)


class I18nTests(TestCase):
    """Danish/English switching: browser detection + session toggle."""

    def test_english_is_the_default(self):
        response = self.client.get(reverse("chat:index"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, "Scroll down to meet BarklAI")

    def test_browser_danish_is_honoured(self):
        response = self.client.get(reverse("chat:index"), HTTP_ACCEPT_LANGUAGE="da")
        self.assertContains(response, 'lang="da"')
        self.assertContains(response, "Rul ned for at møde BarklAI")

    def test_toggle_overrides_the_browser(self):
        self.client.post("/i18n/setlang/", {"language": "da", "next": "/"})
        response = self.client.get(reverse("chat:index"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, 'lang="da"')
        self.assertContains(response, "Baggrund")

    def test_javascript_catalog_serves_danish(self):
        response = self.client.get("/jsi18n/", HTTP_ACCEPT_LANGUAGE="da")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Historik", response.content.decode())


class RagTests(TestCase):
    """Chunking and retrieval plumbing (embeddings are mocked)."""

    def test_split_into_chunks_respects_paragraphs(self):
        from chat.management.commands.build_index import split_into_chunks

        chunks = split_into_chunks("para one\n\npara two\n\npara three", 12)
        self.assertEqual(chunks, ["para one", "para two", "para three"])

    def test_html_comments_are_stripped(self):
        from chat.management.commands.build_index import strip_html_comments

        self.assertEqual(strip_html_comments("A <!-- TODO(Andrea) --> B"), "A  B")

    def test_split_into_chunks_hard_splits_long_blocks(self):
        from chat.management.commands.build_index import split_into_chunks

        chunks = split_into_chunks("x" * 25, 10)
        self.assertEqual([len(chunk) for chunk in chunks], [10, 10, 5])

    def test_cosine_similarity(self):
        from chat.rag import _cosine

        self.assertAlmostEqual(_cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(_cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(_cosine([0, 0], [1, 1]), 0.0)

    def test_retrieve_returns_empty_when_embedding_fails(self):
        from chat import rag

        with patch("chat.rag.embed_text", side_effect=EmbeddingError("nope")):
            self.assertEqual(rag.retrieve("anything"), [])

    def test_build_index_creates_chunks_without_embedding(self):
        # A single long block (1300 chars) splits into 1200 + 100.
        KnowledgeDocument.objects.create(
            kind="profile", source="profile", content="A" * 1300
        )
        call_command("build_index", "--no-embed", verbosity=0)
        self.assertEqual(KnowledgeChunk.objects.count(), 2)
        call_command("build_index", "--no-embed", verbosity=0)  # idempotent
        self.assertEqual(KnowledgeChunk.objects.count(), 2)
        self.assertIsNone(KnowledgeChunk.objects.first().embedding)

    def test_profile_is_always_sent_even_when_retrieval_misses(self):
        from chat import rag

        KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.PROFILE,
            source="profile",
            title="Andrea Latorre — career profile",
            content="Andrea builds RAG pipelines.",
        )
        with patch("chat.rag.embed_text", side_effect=EmbeddingError("no provider")):
            context = rag.build_retrieved_context("do you know Kubernetes?")
        self.assertIn("Andrea builds RAG pipelines.", context)

    def test_profile_chunks_are_never_searched(self):
        from chat.rag import retrievable_chunks

        profile = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.PROFILE, source="profile", content="p"
        )
        project = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README, source="o/r", content="r"
        )
        KnowledgeChunk.objects.create(
            document=profile,
            ordinal=0,
            content="p",
            content_hash="p1",
            embedding=[0.0] * 1024,
        )
        KnowledgeChunk.objects.create(
            document=project,
            ordinal=0,
            content="r",
            content_hash="r1",
            embedding=[1.0] + [0.0] * 1023,
        )
        self.assertEqual(
            [chunk.document.source for chunk in retrievable_chunks()], ["o/r"]
        )

    def test_retrieval_caps_chunks_per_source(self):
        """One long README must not fill the prompt: results stay diverse."""
        from chat import rag

        vector = [1.0] + [0.0] * 1023
        loud = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README, source="o/loud", content="l"
        )
        quiet = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README, source="o/quiet", content="q"
        )
        for ordinal in range(3):
            KnowledgeChunk.objects.create(
                document=loud,
                ordinal=ordinal,
                content=f"l{ordinal}",
                content_hash=f"l{ordinal}",
                embedding=vector,
            )
        KnowledgeChunk.objects.create(
            document=quiet,
            ordinal=0,
            content="q0",
            content_hash="q0",
            embedding=vector,
        )
        with patch("chat.rag.embed_text", return_value=vector):
            hits = rag.retrieve("anything", top_k=3, min_score=0.5)
        self.assertEqual(
            [hit["source"] for hit in hits], ["o/loud", "o/loud", "o/quiet"]
        )

    def test_limit_per_source_keeps_the_best(self):
        from chat.rag import _limit_per_source

        candidates = [
            {"source": source, "content": source, "score": 1.0} for source in "aaab"
        ]
        self.assertEqual(
            [item["source"] for item in _limit_per_source(candidates, 5, 2)],
            ["a", "a", "b"],
        )


@skipUnless(connection.vendor == "postgresql", "vector search needs pgvector")
class RagVectorTests(TestCase):
    """Full vector round-trip — run against PostgreSQL (pgvector)."""

    def test_retrieval_orders_by_similarity(self):
        from chat import rag

        document = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README,
            source="o/r",
            content="readme",
        )
        near = [1.0, 0.0] + [0.0] * 1022
        far = [0.6, 0.8] + [0.0] * 1022  # cosine similarity 0.6 with `near`
        KnowledgeChunk.objects.create(
            document=document, ordinal=0, content="near", content_hash="a", embedding=near
        )
        KnowledgeChunk.objects.create(
            document=document, ordinal=1, content="far", content_hash="b", embedding=far
        )
        with patch("chat.rag.embed_text", return_value=near):
            results = rag.retrieve("query", top_k=2, min_score=0.25)
        self.assertEqual([item["content"] for item in results], ["near", "far"])
        self.assertAlmostEqual(results[0]["score"], 1.0, places=4)
        self.assertAlmostEqual(results[1]["score"], 0.6, places=4)


class PrivacyTests(TestCase):
    """GDPR surface: the notice, and the right to erasure."""

    def test_privacy_notice_renders(self):
        response = self.client.get(reverse("chat:privacy"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy notice")

    def test_privacy_notice_is_danish_for_danish_browsers(self):
        response = self.client.get(reverse("chat:privacy"), HTTP_ACCEPT_LANGUAGE="da")
        self.assertContains(response, "Privatlivspolitik")

    def test_delete_session_erases_the_conversation(self):
        session = ChatSession.objects.create()
        ChatMessage.objects.create(
            session=session, sender=ChatMessage.Sender.USER, content="hi"
        )
        response = self.client.post(
            reverse("chat:delete_session"),
            data=json.dumps({"session_id": str(session.session_id)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(ChatSession.objects.filter(session_id=session.session_id).exists())
        self.assertEqual(ChatMessage.objects.filter(session=session).count(), 0)

    def test_delete_session_rejects_an_invalid_id(self):
        response = self.client.post(
            reverse("chat:delete_session"),
            data=json.dumps({"session_id": "not-a-uuid"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class RetentionTests(TestCase):
    """`purge_old_sessions` enforces the retention window."""

    def _aged_session(self, days: int):
        session = ChatSession.objects.create()
        ChatSession.objects.filter(pk=session.pk).update(
            last_active=timezone.now() - timedelta(days=days)
        )
        return session

    def test_purge_deletes_only_old_conversations(self):
        old = self._aged_session(200)
        fresh = ChatSession.objects.create()
        call_command("purge_old_sessions", "--days", "90", verbosity=0)
        self.assertFalse(ChatSession.objects.filter(pk=old.pk).exists())
        self.assertTrue(ChatSession.objects.filter(pk=fresh.pk).exists())

    def test_dry_run_keeps_everything(self):
        old = self._aged_session(200)
        call_command("purge_old_sessions", "--days", "90", "--dry-run", verbosity=0)
        self.assertTrue(ChatSession.objects.filter(pk=old.pk).exists())


class AgentServiceTests(TestCase):
    """The Groq path (mocked) and its consistent offline fallbacks."""

    JSON_REPLY = json.dumps(
        {
            "reply": "Woof! Here are a few ideas.",
            "interview_requested": False,
            "suggest_questions": True,
        }
    )

    @override_settings(GROQ_API_KEY="test-key")
    @patch("chat.services._call_groq", return_value=JSON_REPLY)
    def test_structured_json_becomes_a_response(self, _call):
        result = generate_reply("I do not know what to ask")
        self.assertEqual(result.reply, "Woof! Here are a few ideas.")
        self.assertTrue(result.suggest_questions)
        self.assertFalse(result.interview_requested)
        self.assertEqual(result.barkley_state, "speaking")

    @override_settings(GROQ_API_KEY="test-key")
    @patch(
        "chat.services._call_groq",
        return_value='{"reply": "yay", "interview_requested": true, "suggest_questions": false}',
    )
    def test_interview_flag_maps_to_celebrating(self, _call):
        result = generate_reply("I would like to schedule a call")
        self.assertTrue(result.interview_requested)
        self.assertEqual(result.barkley_state, "celebrating")

    @override_settings(GROQ_API_KEY="test-key")
    @patch("chat.services._call_groq", side_effect=RuntimeError("boom"))
    def test_groq_failure_uses_friendly_fallback(self, _call):
        result = generate_reply("anything")
        self.assertEqual(result.reply, FALLBACK_UNREACHABLE)
        self.assertIn("Groq", result.reply)
        self.assertIn("latorre.andrea.93@gmail.com", result.reply)
        self.assertEqual(result.barkley_state, "speaking")

    @override_settings(GROQ_API_KEY="")
    def test_offline_fallback_mentions_groq_and_email(self):
        result = generate_reply("hello there")
        self.assertEqual(result.reply, FALLBACK_NO_KEY)
        self.assertIn("Groq", result.reply)
        self.assertIn("latorre.andrea.93@gmail.com", result.reply)

    @override_settings(GROQ_API_KEY="")
    def test_offline_interview_detection_still_flags(self):
        result = generate_reply("I would like to schedule an interview")
        self.assertTrue(result.interview_requested)
        self.assertEqual(result.barkley_state, "celebrating")

    def test_knowledge_text_collects_documents(self):
        KnowledgeDocument.objects.create(
            kind="profile", source="profile", content="Andrea builds RAG pipelines."
        )
        self.assertIn("Andrea builds RAG pipelines.", get_knowledge_text())


@override_settings(GROQ_API_KEY="")
class SyncKnowledgeCommandTests(TestCase):
    """The sync command stores/idempotently refreshes the knowledge base."""

    def test_normalize_repo_accepts_slugs_and_urls(self):
        from chat.management.commands.sync_knowledge import normalize_repo

        self.assertEqual(normalize_repo("owner/repo"), "owner/repo")
        self.assertEqual(normalize_repo("https://github.com/owner/repo"), "owner/repo")
        self.assertEqual(
            normalize_repo("https://github.com/owner/repo/blob/main/README.md"),
            "owner/repo",
        )
        self.assertEqual(normalize_repo("https://github.com/owner/repo.git"), "owner/repo")
        self.assertIsNone(normalize_repo("not-a-repo"))

    def test_profile_sync_is_idempotent(self):
        call_command("sync_knowledge", "--profile-only", verbosity=0)
        self.assertEqual(KnowledgeDocument.objects.filter(kind="profile").count(), 1)
        first = KnowledgeDocument.objects.get(kind="profile")
        self.assertTrue(first.content.strip())
        call_command("sync_knowledge", "--profile-only", verbosity=0)
        self.assertEqual(KnowledgeDocument.objects.filter(kind="profile").count(), 1)
        self.assertEqual(
            KnowledgeDocument.objects.get(kind="profile").content_hash, first.content_hash
        )

    def test_github_readme_is_stored(self):
        from chat.management.commands.sync_knowledge import Command

        payload = {
            "content": base64.b64encode(b"# My repo\nGreat stuff.").decode(),
            "name": "README.md",
            "html_url": "https://github.com/o/r",
        }
        client = _FakeGithubClient(payload)
        outcome = Command()._sync_readme("o/r", client)
        self.assertEqual(outcome, "created")
        doc = KnowledgeDocument.objects.get(kind="github_readme", source="o/r")
        self.assertIn("Great stuff.", doc.content)
        self.assertEqual(doc.url, "https://github.com/o/r")

    def test_exclusion_keys_accept_names_slugs_and_urls(self):
        from chat.management.commands.sync_knowledge import exclusion_keys, is_excluded

        keys = exclusion_keys(
            [
                "owner/repo",
                "https://github.com/other/thing",
                "Love-Maths",
                "",
            ]
        )
        self.assertTrue(is_excluded("owner/repo", keys))
        self.assertTrue(is_excluded("owner/repo", keys))
        self.assertTrue(is_excluded("other/thing", keys))
        # A bare repository name matches whatever the owner is.
        self.assertTrue(is_excluded("latorreandrea/Love-Maths", keys))
        self.assertFalse(is_excluded("owner/kept", keys))

    def test_collect_repos_skips_excluded_repos(self):
        from chat.management.commands.sync_knowledge import Command

        payload = [
            {"full_name": "latorreandrea/keep-me", "fork": False},
            {"full_name": "latorreandrea/Love-Maths", "fork": False},
        ]
        with override_settings(GITHUB_EXCLUDE_REPOS=["Love-Maths"]):
            repos = Command()._collect_repos(
                "latorreandrea", [], _FakeGithubClient(payload)
            )
        self.assertEqual(repos, ["latorreandrea/keep-me"])

    def test_prune_removes_stale_documents_and_chunks(self):
        from chat.management.commands.sync_knowledge import Command

        stale = KnowledgeDocument.objects.create(
            kind="github_readme", source="o/gone", content="bye"
        )
        KnowledgeChunk.objects.create(
            document=stale, ordinal=0, content="bye", content_hash="g1"
        )
        kept = KnowledgeDocument.objects.create(
            kind="github_readme", source="o/kept", content="hi"
        )
        kept_chunk = KnowledgeChunk.objects.create(
            document=kept, ordinal=0, content="hi", content_hash="k1"
        )
        Command()._prune_github(["o/kept"])
        self.assertFalse(KnowledgeDocument.objects.filter(source="o/gone").exists())
        self.assertFalse(KnowledgeChunk.objects.filter(document_id=stale.pk).exists())
        self.assertTrue(KnowledgeChunk.objects.filter(pk=kept_chunk.pk).exists())


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""
        self.links = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeGithubClient:
    """Minimal stand-in for httpx.Client used by the sync command."""

    def __init__(self, readme_payload):
        self._readme_payload = readme_payload

    def get(self, url, params=None):
        return _FakeResponse(200, self._readme_payload)
