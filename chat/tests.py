"""Smoke tests for the barkAI index view and the chat REST API."""
import base64
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views import defaults

from chat.models import ChatMessage, ChatSession, KnowledgeDocument
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
