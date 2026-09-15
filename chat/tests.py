"""Smoke tests for the barkAI index view and the chat REST API."""
import base64
import json
from datetime import timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.views import defaults

from chat.embeddings import EmbeddingError
from chat.evals import evaluate_case, load_golden_set, validate_golden_set
from chat.interviews import capture_interview_request, mark_notified
from chat.models import (
    ChatMessage,
    ChatSession,
    InterviewRequest,
    KnowledgeChunk,
    KnowledgeDocument,
)
from chat.prompts import build_system_prompt
from chat.services import (
    FALLBACK_NO_KEY,
    FALLBACK_UNREACHABLE,
    BarkleyResponse,
    _sanitize_sources,
    detect_language,
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


class LanguageDetectionTests(TestCase):
    """The tiny detector behind the "answer in the recruiter's language" guard."""

    def test_danish_message_is_detected(self):
        self.assertEqual(
            detect_language("Hvilke erfaringer har Andrea med Django?"), "da"
        )

    def test_danish_letters_are_enough(self):
        self.assertEqual(detect_language("Kan vi mødes i næste uge?"), "da")

    def test_english_message_is_detected(self):
        self.assertEqual(detect_language("What projects has Andrea built?"), "en")

    def test_ambiguous_message_stays_undecided(self):
        # A one-word greeting must not trigger an (expensive) model retry.
        self.assertIsNone(detect_language("ok"))
        self.assertIsNone(detect_language("Andrea"))

    def test_prompt_no_longer_demands_a_hardcoded_english_reply(self):
        prompt = build_system_prompt("some knowledge", "da")
        self.assertIn("LANGUAGE", prompt)
        self.assertIn("Danish", prompt)
        self.assertNotIn("Your answer, in English", prompt)


class LanguageGuardTests(TestCase):
    """A Danish question must not come back in English (the v0.3 regression)."""

    DANISH_REPLY = json.dumps(
        {
            "reply": "Voff! Andrea har arbejdet med Django og PostgreSQL.",
            "interview_requested": False,
            "suggest_questions": False,
        }
    )
    ENGLISH_REPLY = json.dumps(
        {
            "reply": "Woof! Andrea has worked with Django and PostgreSQL.",
            "interview_requested": False,
            "suggest_questions": False,
        }
    )

    @override_settings(GROQ_API_KEY="test-key", AGENT_LANGUAGE_GUARD=True)
    @patch("chat.services._call_groq", side_effect=[ENGLISH_REPLY, DANISH_REPLY])
    def test_wrong_language_reply_is_retried_once(self, call):
        result = generate_reply("Hvilke erfaringer har Andrea med Django?")
        self.assertIn("Voff", result.reply)
        self.assertEqual(call.call_count, 2)
        # The retry prompt must explicitly ask for Danish. It is the last system
        # prompt argument; the model id comes after it.
        self.assertIn("Danish", call.call_args.args[-2])

    @override_settings(GROQ_API_KEY="test-key", AGENT_LANGUAGE_GUARD=True)
    @patch("chat.services._call_groq", side_effect=[ENGLISH_REPLY, ENGLISH_REPLY])
    def test_failed_retry_keeps_the_first_answer(self, call):
        result = generate_reply("Hvilke erfaringer har Andrea med Django?")
        self.assertIn("Woof", result.reply)
        self.assertEqual(call.call_count, 2)  # exactly one retry, never a loop

    @override_settings(GROQ_API_KEY="test-key", AGENT_LANGUAGE_GUARD=True)
    @patch("chat.services._call_groq", return_value=ENGLISH_REPLY)
    def test_matching_language_is_not_retried(self, call):
        generate_reply("What projects has Andrea built?")
        self.assertEqual(call.call_count, 1)

    @override_settings(GROQ_API_KEY="test-key", AGENT_LANGUAGE_GUARD=False)
    @patch("chat.services._call_groq", return_value=ENGLISH_REPLY)
    def test_guard_can_be_disabled(self, call):
        generate_reply("Hvilke erfaringer har Andrea med Django?")
        self.assertEqual(call.call_count, 1)

    @override_settings(GROQ_API_KEY="")
    def test_offline_danish_interview_hint_is_flagged_in_danish(self):
        result = generate_reply("Kan vi booke en samtale i næste uge?")
        self.assertTrue(result.interview_requested)
        self.assertEqual(result.barkley_state, "celebrating")
        self.assertIn("Vov", result.reply)  # the Danish fallback copy


class InterviewRequestTests(TestCase):
    """Capture rules for the durable InterviewRequest record."""

    def test_capture_creates_an_event_and_syncs_the_session(self):
        session = ChatSession.objects.create()
        request_obj = capture_interview_request(
            session,
            hr_name="Mette",
            hr_email="mette@firma.dk",
            company_name="Firma ApS",
            message="Kan vi mødes?",
            language="da",
        )
        self.assertEqual(session.interview_requests.count(), 1)
        self.assertEqual(request_obj.hr_email, "mette@firma.dk")
        self.assertEqual(request_obj.language, "da")
        self.assertFalse(request_obj.is_notified)

        session.refresh_from_db()
        self.assertTrue(session.interview_requested)
        self.assertEqual(session.hr_email, "mette@firma.dk")
        self.assertEqual(session.hr_name, "Mette")

    def test_pending_request_is_updated_not_duplicated(self):
        session = ChatSession.objects.create()
        first = capture_interview_request(session, hr_email="wrong@firma.dk")
        second = capture_interview_request(session, hr_email="right@firma.dk")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(session.interview_requests.count(), 1)
        self.assertEqual(second.hr_email, "right@firma.dk")

    def test_unchanged_email_after_notification_does_not_create_a_second_event(self):
        session = ChatSession.objects.create()
        first = capture_interview_request(session, hr_email="mette@firma.dk")
        mark_notified(first)
        second = capture_interview_request(session, hr_email="mette@firma.dk")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(session.interview_requests.count(), 1)

    def test_corrected_email_after_notification_creates_a_new_event(self):
        session = ChatSession.objects.create()
        first = capture_interview_request(session, hr_email="old@firma.dk")
        mark_notified(first)
        second = capture_interview_request(session, hr_email="new@firma.dk")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(session.interview_requests.count(), 2)

    def test_erasing_the_session_removes_its_requests(self):
        session = ChatSession.objects.create()
        capture_interview_request(session, hr_email="mette@firma.dk")
        session.delete()
        self.assertEqual(InterviewRequest.objects.count(), 0)


@override_settings(
    GROQ_API_KEY="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    INTERVIEW_NOTIFY_EMAIL="andrea@example.com",
    DEFAULT_FROM_EMAIL="BarkAI <noreply@barkai.test>",
)
class InterviewNotificationTests(TestCase):
    """The hand-off flow: details captured, Andrea emailed, never twice."""

    CONTACT_URL = "/api/chat/contact"

    def setUp(self):
        mail.outbox = []

    def _post_contact(self, session_id, **overrides):
        payload = {
            "session_id": str(session_id),
            "hr_name": "Mette Hansen",
            "hr_email": "mette@firma.dk",
            "company_name": "Firma ApS",
        }
        payload.update(overrides)
        return self.client.post(
            self.CONTACT_URL,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_contact_endpoint_stores_details_and_notifies(self):
        session_id = uuid4()
        response = self._post_contact(session_id)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["saved"])
        self.assertTrue(body["notified"])

        request_obj = InterviewRequest.objects.get(session__session_id=session_id)
        self.assertEqual(request_obj.hr_email, "mette@firma.dk")
        self.assertEqual(request_obj.company_name, "Firma ApS")
        self.assertTrue(request_obj.is_notified)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("mette@firma.dk", email.body)
        self.assertIn("Firma ApS", email.body)
        self.assertIn(str(session_id), email.body)

    def test_invalid_email_is_rejected(self):
        response = self._post_contact(uuid4(), hr_email="not-an-email")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(InterviewRequest.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_is_required(self):
        response = self._post_contact(uuid4(), hr_email="")
        self.assertEqual(response.status_code, 422)

    def test_resubmitting_the_same_details_does_not_notify_twice(self):
        session_id = uuid4()
        self._post_contact(session_id)
        self._post_contact(session_id, hr_name="Mette H.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(InterviewRequest.objects.count(), 1)

    @override_settings(INTERVIEW_NOTIFY_EMAIL="")
    def test_details_are_stored_even_when_notifications_are_disabled(self):
        session_id = uuid4()
        response = self._post_contact(session_id)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved"])
        self.assertFalse(response.json()["notified"])
        self.assertEqual(len(mail.outbox), 0)

        request_obj = InterviewRequest.objects.get(session__session_id=session_id)
        self.assertFalse(request_obj.is_notified)

    def test_send_persists_details_and_records_the_interview(self):
        session_id = uuid4()
        response = self.client.post(
            "/api/chat/send",
            data=json.dumps(
                {
                    "session_id": str(session_id),
                    "message": "I would like to schedule an interview",
                    "hr_name": "Mette",
                    "hr_email": "mette@firma.dk",
                    "company_name": "Firma ApS",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        session = ChatSession.objects.get(session_id=session_id)
        self.assertTrue(session.interview_requested)
        self.assertEqual(session.interview_requests.count(), 1)
        self.assertEqual(session.interview_requests.first().hr_name, "Mette")
        self.assertEqual(len(mail.outbox), 1)


class ChatGuardrailTests(TestCase):
    """Length cap and rate limiting on the public chat endpoint."""

    SEND_URL = "/api/chat/send"

    def setUp(self):
        cache.clear()  # Throttle counters live in the cache, not the database.

    @override_settings(GROQ_API_KEY="")
    def test_oversized_message_is_rejected(self):
        response = self.client.post(
            self.SEND_URL,
            data=json.dumps({"session_id": str(uuid4()), "message": "x" * 2001}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    @override_settings(
        GROQ_API_KEY="", CHAT_RATE_LIMIT_PER_SESSION=1, CHAT_RATE_LIMIT_PER_IP=1000
    )
    def test_rate_limit_returns_429_after_the_cap(self):
        payload = json.dumps({"session_id": str(uuid4()), "message": "hello"})
        first = self.client.post(
            self.SEND_URL, data=payload, content_type="application/json"
        )
        second = self.client.post(
            self.SEND_URL, data=payload, content_type="application/json"
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    @override_settings(
        GROQ_API_KEY="", CHAT_RATE_LIMIT_PER_SESSION=0, CHAT_RATE_LIMIT_PER_IP=0
    )
    def test_zero_limits_disable_the_throttle(self):
        payload = json.dumps({"session_id": str(uuid4()), "message": "hello"})
        for _ in range(3):
            response = self.client.post(
                self.SEND_URL, data=payload, content_type="application/json"
            )
            self.assertEqual(response.status_code, 200)


def _groq_json_error(failed_generation: str) -> Exception:
    """A ``groq.BadRequestError`` look-alike carrying a refused generation."""
    error = RuntimeError("Error code: 400 - json_validate_failed")
    error.response = Mock()
    error.response.json.return_value = {
        "error": {
            "code": "json_validate_failed",
            "failed_generation": failed_generation,
        }
    }
    return error


class JsonModeSalvageTests(TestCase):
    """A prose answer refused by JSON mode must never be thrown away."""

    @override_settings(GROQ_API_KEY="test-key")
    @patch("chat.services._call_groq")
    def test_refused_json_keeps_the_prose_answer(self, call):
        call.side_effect = _groq_json_error(
            "Woof! Andrea built Django projects.\nsources: []"
        )
        result = generate_reply("Which projects?")
        self.assertIn("Django projects", result.reply)
        self.assertNotIn("sources:", result.reply)
        self.assertEqual(result.sources, ())
        self.assertNotEqual(result.reply, FALLBACK_UNREACHABLE)

    @override_settings(GROQ_API_KEY="test-key")
    @patch("chat.services._call_groq")
    def test_salvaged_prose_still_flags_an_interview_request(self, call):
        call.side_effect = _groq_json_error("Woof! Sure, let's schedule a call.")
        result = generate_reply("Can we talk?")
        self.assertTrue(result.interview_requested)
        self.assertEqual(result.barkley_state, "celebrating")

    def test_other_errors_are_never_salvaged(self):
        from chat.services import _salvage_failed_generation

        # No HTTP response at all (network error).
        self.assertEqual(_salvage_failed_generation(RuntimeError("boom")), "")
        # A 400 that is not a JSON-mode refusal.
        error = Mock()
        error.response.json.return_value = {"error": {"code": "invalid_api_key"}}
        self.assertEqual(_salvage_failed_generation(error), "")

    def test_sources_lines_are_stripped_from_the_prose(self):
        from chat.services import _strip_sources_lines

        self.assertEqual(_strip_sources_lines("Woof!\nSources: [repo/a]\n"), "Woof!")
        self.assertEqual(_strip_sources_lines("Woof! No sources here."), "Woof! No sources here.")


class GoldenSetEvalTests(TestCase):
    """The golden-set file and its evaluator: offline, no model calls."""

    def test_golden_set_is_well_formed(self):
        self.assertEqual(validate_golden_set(load_golden_set()), [])

    def test_check_only_command_passes(self):
        call_command("eval_agent", "--check-only", verbosity=0)

    def test_check_only_rejects_a_broken_set(self):
        problems = validate_golden_set(
            {
                "cases": [
                    {"id": "x", "language": "en", "question": "Q"},
                    {"id": "x", "language": "fr", "question": ""},
                ]
            }
        )
        self.assertTrue(any("duplicate id" in problem for problem in problems))
        self.assertTrue(any("'language'" in problem for problem in problems))
        self.assertTrue(any("empty 'question'" in problem for problem in problems))
        self.assertTrue(
            any("needs at least one expectation" in problem for problem in problems)
        )
        self.assertTrue(any("no Danish case" in problem for problem in problems))

    def test_golden_set_covers_both_languages(self):
        languages = {case["language"] for case in load_golden_set()["cases"]}
        self.assertEqual(languages, {"en", "da"})

    def test_evaluator_flags_language_forbidden_words_and_the_flag(self):
        case = {
            "id": "t",
            "language": "da",
            "must_contain": ["django"],
            "must_contain_any": ["postgresql", "postgres"],
            "must_not_contain": ["cpr"],
            "interview_requested": False,
        }
        reasons = evaluate_case(
            case,
            reply="Sure, he used Django, PostgreSQL and his CPR number.",
            interview_requested=True,
            detected_language="en",
        )
        joined = " | ".join(reasons)
        self.assertIn("language", joined)
        self.assertIn("forbidden", joined)
        self.assertIn("interview_requested", joined)

    def test_evaluator_passes_a_good_reply(self):
        case = {
            "id": "t",
            "language": "da",
            "must_contain": ["django"],
            "must_contain_any": ["postgresql", "postgres"],
            "must_not_contain": ["cpr"],
            "interview_requested": False,
        }
        self.assertEqual(
            evaluate_case(
                case,
                reply="Voff! Andrea har arbejdet med Django og PostgreSQL.",
                interview_requested=False,
                detected_language="da",
            ),
            [],
        )

    def test_evaluator_reports_a_missing_required_fact(self):
        case = {"id": "t", "language": "en", "must_contain": ["bigquery"]}
        reasons = evaluate_case(
            case,
            reply="Woof! He worked with Django.",
            interview_requested=False,
            detected_language="en",
        )
        self.assertEqual(len(reasons), 1)
        self.assertIn("missing", reasons[0])


class SourceCitationTests(TestCase):
    """Citations: the model proposes labels, the server validates them."""

    def test_sanitizer_keeps_only_retrieved_labels(self):
        allowed = ["latorreandrea/barkAI", "latorreandrea/fiestapa"]
        kept = _sanitize_sources(
            ["latorreandrea/barkAI", "latorreandrea/invented", " LATORREANDREA/FIESTAPA "],
            allowed,
        )
        # The invented label is dropped, the case/whitespace difference is
        # normalised, and the canonical spelling of the allowed label is kept.
        self.assertEqual(kept, ("latorreandrea/barkAI", "latorreandrea/fiestapa"))

    def test_sanitizer_drops_everything_without_a_retrieved_list(self):
        self.assertEqual(_sanitize_sources(["latorreandrea/barkAI"], []), ())
        self.assertEqual(_sanitize_sources("not-a-list", ["repo/a"]), ())

    @override_settings(GROQ_API_KEY="test-key")
    @patch(
        "chat.services._knowledge_for_prompt",
        return_value=("ground truth", ["repo/a"]),
    )
    @patch(
        "chat.services._call_groq",
        return_value=json.dumps(
            {
                "reply": "Woof! Grounded facts.",
                "interview_requested": False,
                "suggest_questions": False,
                "sources": ["repo/a", "repo/invented"],
            }
        ),
    )
    def test_invented_citations_never_reach_the_caller(self, _call, _knowledge):
        result = generate_reply("Tell me about repo a")
        self.assertEqual(result.sources, ("repo/a",))

    def test_citable_sources_block_lists_the_labels(self):
        prompt = build_system_prompt("facts", "en", ["repo/a", "repo/b"])
        self.assertIn("CITABLE SOURCES", prompt)
        self.assertIn("- repo/a", prompt)
        self.assertIn("- repo/b", prompt)

    def test_no_sources_prompt_asks_for_an_empty_list(self):
        prompt = build_system_prompt("facts", "en", [])
        self.assertIn("none available", prompt)

    @override_settings(GROQ_API_KEY="")
    def test_api_returns_and_persists_the_citations(self):
        session_id = uuid4()
        with patch(
            "chat.api.router.generate_reply",
            return_value=BarkleyResponse(
                reply="Woof! Grounded answer.",
                barkley_state="speaking",
                interview_requested=False,
                sources=("latorreandrea/barkAI",),
            ),
        ):
            response = self.client.post(
                "/api/chat/send",
                data=json.dumps({"session_id": str(session_id), "message": "hi"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"], ["latorreandrea/barkAI"])

        session = ChatSession.objects.get(session_id=session_id)
        assistant = session.messages.get(sender=ChatMessage.Sender.ASSISTANT)
        self.assertEqual(assistant.sources, ["latorreandrea/barkAI"])

        history = self.client.get(f"/api/chat/history/{session_id}").json()
        self.assertEqual(history["messages"][-1]["sources"], ["latorreandrea/barkAI"])

    def test_user_turns_carry_no_sources(self):
        session = ChatSession.objects.create()
        ChatMessage.objects.create(
            session=session, sender=ChatMessage.Sender.USER, content="hi"
        )
        payload = self.client.get(f"/api/chat/history/{session.session_id}").json()
        self.assertEqual(payload["messages"][0]["sources"], [])


class KnowledgeStatusCommandTests(TestCase):
    """The knowledge-base freshness report a scheduled job runs."""

    def _document(self, **overrides):
        payload = {"kind": "profile", "source": "profile", "content": "x"}
        payload.update(overrides)
        return KnowledgeDocument.objects.create(**payload)

    def test_reports_counts_and_a_fresh_base(self):
        document = self._document()
        KnowledgeChunk.objects.create(
            document=document,
            ordinal=0,
            content="x",
            content_hash="h",
            embedding=[0.0] * 1024,
        )
        out = StringIO()
        call_command("knowledge_status", stdout=out)
        output = out.getvalue()
        self.assertIn("Documents: 1", output)
        self.assertIn("1 embedded, 100%", output)
        self.assertIn("Fresh: nothing to do.", output)

    def test_unembedded_chunks_are_flagged(self):
        document = self._document()
        KnowledgeChunk.objects.create(
            document=document, ordinal=0, content="x", content_hash="h"
        )
        out = StringIO()
        call_command("knowledge_status", stdout=out)
        self.assertIn("not embedded", out.getvalue())

        with self.assertRaises(CommandError):
            call_command("knowledge_status", "--fail-on-stale", stdout=StringIO())

    def test_stale_document_is_reported(self):
        document = self._document(source="o/r", kind="github_readme")
        KnowledgeDocument.objects.filter(pk=document.pk).update(
            fetched_at=timezone.now() - timedelta(days=90)
        )
        out = StringIO()
        call_command("knowledge_status", "--days", "30", stdout=out)
        output = out.getvalue()
        self.assertIn("Stale:", output)
        self.assertIn("sync_knowledge", output)

    def test_fail_on_stale_exits_non_zero(self):
        document = self._document()
        KnowledgeDocument.objects.filter(pk=document.pk).update(
            fetched_at=timezone.now() - timedelta(days=90)
        )
        with self.assertRaises(CommandError):
            call_command(
                "knowledge_status",
                "--days",
                "30",
                "--fail-on-stale",
                stdout=StringIO(),
            )

    def test_empty_knowledge_base_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("knowledge_status", stdout=StringIO())


class ModelFallbackTests(TestCase):
    """A decommissioned primary model must not take the whole chat down."""

    JSON_REPLY = json.dumps(
        {
            "reply": "Woof! Still here.",
            "interview_requested": False,
            "suggest_questions": False,
        }
    )

    @override_settings(
        GROQ_API_KEY="test-key",
        GROQ_MODEL="primary-model",
        GROQ_MODEL_FALLBACK="fallback-model",
    )
    @patch(
        "chat.services._call_groq",
        side_effect=[RuntimeError("model_not_found"), JSON_REPLY],
    )
    def test_fallback_model_answers_when_the_primary_fails(self, call):
        result = generate_reply("What projects has Andrea built?")
        self.assertEqual(result.reply, "Woof! Still here.")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args.args[-1], "fallback-model")

    @override_settings(
        GROQ_API_KEY="test-key",
        GROQ_MODEL="primary-model",
        GROQ_MODEL_FALLBACK="fallback-model",
    )
    @patch("chat.services._call_groq", return_value=JSON_REPLY)
    def test_no_fallback_when_the_primary_answers(self, call):
        generate_reply("What projects has Andrea built?")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[-1], "primary-model")

    @override_settings(
        GROQ_API_KEY="test-key",
        GROQ_MODEL="primary-model",
        GROQ_MODEL_FALLBACK="primary-model",
    )
    @patch("chat.services._call_groq", side_effect=RuntimeError("boom"))
    def test_identical_fallback_is_never_retried(self, call):
        result = generate_reply("anything")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result.reply, FALLBACK_UNREACHABLE)

    @override_settings(
        GROQ_API_KEY="test-key", GROQ_MODEL="primary-model", GROQ_MODEL_FALLBACK=""
    )
    @patch("chat.services._call_groq", side_effect=RuntimeError("boom"))
    def test_fallback_can_be_disabled(self, call):
        generate_reply("anything")
        self.assertEqual(call.call_count, 1)


class HealthzTests(TestCase):
    """The platform probe: cheap, boring, and honest about the database."""

    def test_healthz_reports_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["database"])
        self.assertEqual(payload["indexed_chunks"], 0)

    def test_healthz_reports_503_when_the_database_is_down(self):
        with patch("barkai.views.connection.cursor", side_effect=RuntimeError("no db")):
            response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["database"])


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
