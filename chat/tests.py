"""Smoke tests for the barkAI index view and the chat REST API."""
import base64
import json
from datetime import timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.conf import settings
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

from barkai.context_processors import asset_version
from chat.embeddings import EmbeddingError
from chat.evals import (
    evaluate_case,
    format_reasons,
    load_golden_set,
    validate_golden_set,
)
from chat.interviews import capture_interview_request, extract_contact, mark_notified
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
    _resolve_citations,
    _strip_sources_lines,
    detect_language,
    generate_reply,
    get_knowledge_text,
    mentions_interview,
)


class IndexViewTests(TestCase):
    def test_index_renders_app_template(self):
        response = self.client.get(reverse("chat:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat/index.html")

    def test_mobile_layout_keeps_the_bubble_readable(self):
        # The phone layout used to clip the quick-question nudge: the bubble grew
        # upwards out of `main` (which is `overflow: hidden`) and the floating
        # history toggle landed on top of it. Two decisions came out of that and
        # this test locks both: the height caps are viewport-aware, and the toggle
        # stays exactly where the desktop shows it (top-right, floating).
        response = self.client.get(reverse("chat:index"))
        body = response.content.decode()
        self.assertContains(response, 'id="history-toggle"')
        self.assertContains(response, "absolute right-3 top-3")
        self.assertContains(response, "max-h-[30svh]")
        self.assertContains(response, "sm:max-h-[38vh]")
        # The nudge lives INSIDE the scrollable bubble, between its container and
        # the mascot video — never beside the bubble where it could be cut off.
        self.assertLess(
            body.index('id="speech-bubble-scroll"'), body.index('id="idle-suggestions"')
        )
        self.assertLess(
            body.index('id="idle-suggestions"'), body.index("js-video-shell")
        )

    def test_chat_css_keeps_the_viewport_aware_caps(self):
        # The caps live in the page stylesheet, not in the template: a fixed rem
        # value is what clipped the bubble on short phones (see the test above).
        css = (settings.BASE_DIR / "static" / "css" / "chat.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("max-height: min(8rem, 26svh)", css)
        self.assertIn("max-height: min(14rem, 32svh)", css)
        # `safe end` is what makes the surplus scrollable instead of unreachable.
        self.assertIn("justify-content: safe end", css)

    def test_the_hand_off_form_can_be_dismissed(self):
        # The ✕ must not submit the form: a bare <button> inside a <form> does,
        # which would save the (empty) details on a dismissal.
        response = self.client.get(reverse("chat:index"))
        body = response.content.decode()
        self.assertIn('id="interview-contact-close"', body)
        self.assertIn('type="button"', body)
        self.assertIn('aria-label="Close the interview form"', body)

    def test_the_dismiss_button_is_translated(self):
        response = self.client.get(reverse("chat:index"), HTTP_ACCEPT_LANGUAGE="da")
        self.assertContains(response, "Luk interviewformularen")

    def test_static_assets_are_cache_busted(self):
        # WhiteNoise serves these files with a one-year `max-age` and the storage
        # is not fingerprinted, so the `?v=` token is the only thing that lets a
        # deploy replace them for a visitor who already cached them
        # (see ASSET_VERSION in settings).
        response = self.client.get(reverse("chat:index"))
        token = settings.ASSET_VERSION
        self.assertContains(response, f"/static/css/barkai.css?v={token}")
        self.assertContains(response, f"/static/css/chat.css?v={token}")
        self.assertContains(response, f"/static/js/chat.js?v={token}")
        self.assertContains(response, f'data-asset-version="{token}"')

    def test_the_erasure_button_is_rendered_once(self):
        # One button, in the footer: the composer keeps its clutter out of the
        # way, and a duplicated id would make the JS bind the wrong element.
        response = self.client.get(reverse("chat:index"))
        self.assertEqual(response.content.decode().count('id="delete-session"'), 1)

    def test_the_hand_off_button_offers_both_labels(self):
        # chat.js swaps the label: "Save" while the visitor is typing the details,
        # "Confirm" when the form opens prefilled with what the chat collected.
        # Both strings live in the Django catalogue so both are translated.
        response = self.client.get(reverse("chat:index"))
        self.assertContains(response, 'data-save-label="Save my details"')
        self.assertContains(response, 'data-confirm-label="Confirm my details"')


class AssetVersionTests(TestCase):
    def test_context_processor_exposes_the_setting(self):
        context = asset_version(RequestFactory().get("/"))
        self.assertEqual(context, {"ASSET_VERSION": settings.ASSET_VERSION})

    def test_token_is_never_empty(self):
        # The token is derived from the assets themselves when ASSET_VERSION is
        # not exported, and it must never come out empty: a bare `?v=` would stop
        # busting the cache exactly where it matters.
        self.assertTrue(settings.ASSET_VERSION)


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

    def test_an_address_typed_in_the_chat_is_collected_and_echoed(self):
        # The agent asks for name/email/company when it flags an interview, so
        # recruiters often just *write* the address: it is remembered without an
        # LLM call and handed back so the form can be shown prefilled.
        session_id = uuid4()
        response = self.client.post(
            self.SEND_URL,
            data={
                "session_id": str(session_id),
                "message": "I'm Mette, write to mette@firma.dk please",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["contact"]["hr_email"], "mette@firma.dk")
        session = ChatSession.objects.get(session_id=session_id)
        self.assertEqual(session.hr_email, "mette@firma.dk")

    def test_history_reports_the_contact_it_already_knows(self):
        # A page reload must not lose what the conversation collected: the form
        # opens prefilled from the history response.
        session = ChatSession.objects.create(hr_name="Mette", hr_email="mette@firma.dk")
        response = self.client.get(self.HISTORY_URL.format(session.session_id))
        self.assertEqual(
            response.json()["contact"],
            {"hr_name": "Mette", "hr_email": "mette@firma.dk", "company_name": ""},
        )

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

    def test_chunk_line_spans_point_at_the_source_lines(self):
        from chat.management.commands.build_index import iter_chunk_spans

        text = "# Title\n\npara one\n\npara two"
        spans = iter_chunk_spans(text, 10)
        self.assertEqual(
            list(spans), [("# Title", 1, 1), ("para one", 3, 3), ("para two", 5, 5)]
        )

    def test_hard_split_chunks_keep_their_own_line_span(self):
        from chat.management.commands.build_index import iter_chunk_spans

        spans = iter_chunk_spans("aaaa\nbbbb\ncccc", 5)  # no blank line to split on
        self.assertEqual([piece for piece, _s, _e in spans], ["aaaa\n", "bbbb\n", "cccc"])
        self.assertEqual(
            [(start, end) for _piece, start, end in spans], [(1, 1), (2, 2), (3, 3)]
        )

    def test_build_index_stores_the_line_span_of_each_chunk(self):
        KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README,
            source="o/r",
            content="para one\n\npara two",
        )
        with override_settings(RAG_CHUNK_MAX_CHARS=10):
            call_command("build_index", "--no-embed", verbosity=0)
        spans = list(
            KnowledgeChunk.objects.order_by("ordinal").values_list(
                "start_line", "end_line"
            )
        )
        self.assertEqual(spans, [(1, 1), (3, 3)])

    def test_a_moved_chunk_refreshes_its_span_without_re_embedding(self):
        document = KnowledgeDocument.objects.create(
            kind=KnowledgeDocument.Kind.GITHUB_README,
            source="o/r",
            content="aaaa\n\npara two",
        )
        with override_settings(RAG_CHUNK_MAX_CHARS=10):
            call_command("build_index", "--no-embed", verbosity=0)
            digest = KnowledgeChunk.objects.get(ordinal=1).content_hash
            # Two blank lines above the second paragraph: its text is untouched, so
            # only the line span has to move (and no embedding call is needed).
            document.content = "aaaa\n\n\n\npara two"
            document.save(update_fields=["content"])
            call_command("build_index", "--no-embed", verbosity=0)

        moved = KnowledgeChunk.objects.get(ordinal=1)
        self.assertEqual(moved.content, "para two")
        self.assertEqual(moved.content_hash, digest)
        self.assertEqual((moved.start_line, moved.end_line), (5, 5))

    def test_line_range_labels(self):
        from chat.rag import line_range_label

        self.assertEqual(line_range_label(120, 148), "120-148")
        self.assertEqual(line_range_label(120, 120), "120")
        # 0 means "indexed before the spans were tracked": link the file only.
        self.assertEqual(line_range_label(0, 0), "")

    def test_chunk_title_reads_the_markdown_section(self):
        from chat.rag import chunk_title

        self.assertEqual(chunk_title("## Deployment\n\nCloud Run deploys."), "Deployment")
        self.assertEqual(chunk_title("just prose, no heading"), "")

    def test_a_retrieved_chunk_carries_its_citation_metadata(self):
        from chat.rag import _candidate

        chunk = KnowledgeChunk(
            document=KnowledgeDocument(
                kind=KnowledgeDocument.Kind.GITHUB_README,
                source="o/r",
                url="https://github.com/o/r/blob/main/README.md",
            ),
            ordinal=0,
            content="## Deployment\n\nCloud Run deploys.",
            start_line=120,
            end_line=148,
        )
        candidate = _candidate(chunk, 0.87)
        self.assertEqual(candidate["source"], "o/r")
        self.assertEqual(candidate["title"], "Deployment")
        self.assertEqual(candidate["url"], "https://github.com/o/r/blob/main/README.md")
        self.assertEqual(candidate["lines"], "120-148")
        self.assertAlmostEqual(candidate["score"], 0.87)

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
        # The erasure sentence points at the footer now, so the Danish catalogue
        # has to follow the English string (locale/da/LC_MESSAGES/django.po).
        self.assertContains(response, "i footeren")

    def test_the_erasure_button_is_in_the_footer_of_every_page(self):
        # It used to sit in the chat composer: it belongs to the shared footer,
        # where a visitor who came to read the notice can also use it. navbar.js
        # (not chat.js, which the privacy page never loads) wires it.
        for url in (reverse("chat:index"), reverse("chat:privacy")):
            response = self.client.get(url)
            self.assertContains(response, 'id="delete-session"')
            self.assertContains(response, "data-confirm-message=")

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


class ContactExtractionTests(TestCase):
    """What the chat itself collects about the recruiter (chat/interviews.py)."""

    def test_email_in_a_sentence_is_found(self):
        found = extract_contact("Hi! I'm Mette from Firma ApS — mette@firma.dk, thanks!")
        self.assertEqual(found["hr_email"], "mette@firma.dk")

    def test_surrounding_punctuation_is_not_part_of_the_address(self):
        self.assertEqual(extract_contact("Reach me at mette@firma.dk.")["hr_email"], "mette@firma.dk")
        self.assertEqual(extract_contact("(mette@firma.dk)")["hr_email"], "mette@firma.dk")

    def test_a_multi_part_domain_is_kept_whole(self):
        self.assertEqual(extract_contact("jane.doe+hr@acme.co.uk")["hr_email"], "jane.doe+hr@acme.co.uk")

    def test_prose_without_an_address_yields_nothing(self):
        # A name or a company written in prose is left to the form: guessing it
        # would prefill the recruiter's confirmation form with a wrong value,
        # and only the address is needed to answer them.
        self.assertEqual(extract_contact("I'm Mette from Firma ApS"), {})
        self.assertEqual(extract_contact("mette@firma"), {})
        self.assertEqual(extract_contact(""), {})


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


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InterviewIntentTests(TestCase):
    """When may the hand-off form come back after the visitor dismissed it?

    The API answers with a **per-turn** `interview_intent` (the model's flag for
    this message, or the message itself asking for an interview in plain words),
    while `interview_requested` stays the sticky session flag that drives the
    notification. The keyword backstop is what makes the form reliable in both
    languages even when the model misses the phrasing.
    """

    SEND_URL = "/api/chat/send"

    def _send(self, message, **reply):
        """POST a message with the model stubbed, returning the JSON payload."""
        payload = {
            "reply": "Woof! Sure.",
            "barkley_state": "speaking",
            "interview_requested": False,
        }
        payload.update(reply)
        with patch(
            "chat.api.router.generate_reply",
            return_value=BarkleyResponse(**payload),
        ):
            response = self.client.post(
                self.SEND_URL,
                data=json.dumps({"session_id": str(uuid4()), "message": message}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_heuristic_reads_both_languages(self):
        asked = [
            "Can we schedule a call with Andrea next week?",
            "How can I set up an appointment for an interview?",
            "I would like to get in touch with Andrea about a role.",
            "Could you reach out to arrange a meeting?",
            "Kan vi booke et interview med Andrea i næste uge?",
            "Hvordan kan jeg komme i kontakt med Andrea om et interview?",
            "Kan vi aftale et møde i næste uge?",
            "Jeg vil gerne tale med Andrea om en stilling.",
            "Kan jeg få fat i Andrea for en samtale?",
            "Har Andrea tid til et kort opkald?",
        ]
        for message in asked:
            self.assertTrue(mentions_interview(message), message)

    def test_the_heuristic_ignores_ordinary_questions(self):
        quiet = [
            "Hvilke projekter har Andrea bygget?",
            "Fortæl mig om hans erfaring med Django.",
            "Kan du tale om dine projekter?",
            "Hvad laver BarkAI egentlig?",
            "Which Google Cloud services has Andrea used?",
            "Tell me about the RAG pipeline.",
        ]
        for message in quiet:
            self.assertFalse(mentions_interview(message), message)

    def test_a_danish_request_arms_the_form_when_the_model_misses_it(self):
        # The agent said "no interview" — the message says otherwise, and the
        # visitor must still get the form (that is the whole point of the backstop).
        payload = self._send("Hvordan kan jeg komme i kontakt med Andrea om et interview?")
        self.assertTrue(payload["interview_intent"])
        # The session flag stays the model's call: nothing was captured.
        self.assertFalse(payload["interview_requested"])

    def test_an_english_request_arms_the_form_when_the_model_misses_it(self):
        payload = self._send("How can I set up an appointment for an interview?")
        self.assertTrue(payload["interview_intent"])
        self.assertFalse(payload["interview_requested"])

    def test_an_ordinary_message_never_arms_the_form(self):
        payload = self._send("Fortæl mig om Andreas projekter.")
        self.assertFalse(payload["interview_intent"])

    def test_the_model_flag_is_enough_on_its_own(self):
        payload = self._send(
            "Hello", barkley_state="celebrating", interview_requested=True
        )
        self.assertTrue(payload["interview_intent"])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    INTERVIEW_NOTIFY_EMAIL="andrea@example.com",
    DEFAULT_FROM_EMAIL="BarkAI <noreply@barkai.test>",
)
class RetryInterviewNotificationsCommandTests(TestCase):
    """The recovery command: what is still pending, what is sent, what is not."""

    def setUp(self):
        mail.outbox = []

    def _pending_request(self, **overrides):
        """A request whose notification never went out (capture sends nothing)."""
        payload = {"hr_name": "Mette", "hr_email": "mette@firma.dk"}
        payload.update(overrides)
        return capture_interview_request(ChatSession.objects.create(), **payload)

    def test_sends_every_pending_request_and_stamps_it(self):
        first = self._pending_request()
        second = self._pending_request(hr_email="jonas@firma.dk")

        out = StringIO()
        call_command("retry_interview_notifications", stdout=out)

        self.assertEqual(len(mail.outbox), 2)
        # The notification goes to Andrea; the recruiter's address is in the body.
        self.assertEqual(
            sorted(email.to[0] for email in mail.outbox),
            ["andrea@example.com", "andrea@example.com"],
        )
        bodies = "\n".join(email.body for email in mail.outbox)
        self.assertIn("mette@firma.dk", bodies)
        self.assertIn("jonas@firma.dk", bodies)
        self.assertIn("a recruiter requested an interview", mail.outbox[0].subject)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_notified)
        self.assertTrue(second.is_notified)
        self.assertIn("Done: 2/2 notification(s) sent.", out.getvalue())

    def test_already_notified_requests_are_left_alone(self):
        mark_notified(self._pending_request())

        out = StringIO()
        call_command("retry_interview_notifications", stdout=out)

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Nothing pending", out.getvalue())

    def test_requests_without_a_reply_address_are_never_sent(self):
        # Captured with no email: there is nobody to notify.
        self._pending_request(hr_email="")

        out = StringIO()
        call_command("retry_interview_notifications", stdout=out)

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Nothing pending", out.getvalue())

    def test_dry_run_lists_what_would_be_sent_and_keeps_it_pending(self):
        request_obj = self._pending_request()

        out = StringIO()
        call_command("retry_interview_notifications", "--dry-run", stdout=out)

        self.assertEqual(len(mail.outbox), 0)
        request_obj.refresh_from_db()
        self.assertFalse(request_obj.is_notified)
        self.assertIn("[dry-run] would notify mette@firma.dk", out.getvalue())

    @override_settings(INTERVIEW_NOTIFY_EMAIL="")
    def test_disabled_notifications_are_reported_and_stay_pending(self):
        request_obj = self._pending_request()

        out = StringIO()
        call_command("retry_interview_notifications", stdout=out)

        self.assertEqual(len(mail.outbox), 0)
        request_obj.refresh_from_db()
        self.assertFalse(request_obj.is_notified)
        self.assertIn("Still pending", out.getvalue())
        self.assertIn("notifications disabled", out.getvalue())
        self.assertIn("Done: 0/1 notification(s) sent.", out.getvalue())

    def test_an_smtp_failure_is_reported_with_its_reason(self):
        request_obj = self._pending_request()

        out = StringIO()
        with patch(
            "chat.notifications.send_mail",
            side_effect=RuntimeError("smtp is down"),
        ):
            call_command("retry_interview_notifications", stdout=out)

        request_obj.refresh_from_db()
        self.assertFalse(request_obj.is_notified)
        self.assertIn("Still pending", out.getvalue())
        self.assertIn("smtp is down", out.getvalue())
        # The reason is recorded so the admin shows why it is still waiting.
        self.assertIn("smtp is down", request_obj.notification_error)


class SendTestEmailCommandTests(TestCase):
    """The SMTP self-check: it reports the configuration and never fails silently."""

    def setUp(self):
        mail.outbox = []

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="barkley@example.test",
        INTERVIEW_NOTIFY_EMAIL="andrea@example.test",
    )
    def test_reports_the_configuration_and_sends_the_test_message(self):
        out = StringIO()
        call_command("send_test_email", "--to", "hr@example.test", stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hr@example.test"])
        self.assertEqual(mail.outbox[0].from_email, "barkley@example.test")
        self.assertIn("BarkAI test email", mail.outbox[0].subject)
        output = out.getvalue()
        self.assertIn("Backend: django.core.mail.backends.locmem.EmailBackend", output)
        self.assertIn("Sent 1 message(s).", output)

        # Without --to the configured interview address is the recipient.
        call_command("send_test_email", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["andrea@example.test"])

    @override_settings(INTERVIEW_NOTIFY_EMAIL="")
    def test_without_a_recipient_it_fails_cleanly(self):
        with self.assertRaisesMessage(
            CommandError, "No recipient: pass --to or set INTERVIEW_NOTIFY_EMAIL."
        ):
            call_command("send_test_email", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)


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

    def test_the_citation_list_never_stays_in_the_prose(self):
        # Every shape the model has actually produced: the prompt forbids a
        # citation list in `reply` and the sanitiser makes sure of it, in both
        # languages.
        labels = {"latorreandrea/barkAI", "latorreandrea/fiestapa"}
        cases = {
            "Woof!\nSources: [repo/a]\n": "Woof!",
            "Woof!\nsources: ['latorreandrea/barkAI', 'latorreandrea/fiestapa']": "Woof!",
            "Woof!\nKilder: latorreandrea/barkAI": "Woof!",
            "Woof!\nReferencer: profile": "Woof!",
            "Woof!\n[2, 3]": "Woof!",
            "Woof!\n- latorreandrea/barkAI\n- latorreandrea/fiestapa": "Woof!",
            "Woof!\n['latorreandrea/barkAI']": "Woof!",
        }
        for prose, expected in cases.items():
            self.assertEqual(_strip_sources_lines(prose, labels), expected)

    def test_real_sentences_survive_the_prose_sanitiser(self):
        labels = {"latorreandrea/barkAI", "latorreandrea/fiestapa"}
        for prose in (
            "Woof! No sources here.",
            "Woof!\n- Andrea built the pipeline end to end.",
            "Woof!\nSniff, sniff.",
            "Woof!\nSniff! I used Django, PostgreSQL and Cloud Run.",
        ):
            self.assertEqual(_strip_sources_lines(prose, labels), prose)


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

    def test_every_case_asserts_the_prose_contract(self):
        leaked = "Woof!\nSources: ['repo/a']\n- repo/b"
        joined = " | ".join(format_reasons(leaked))
        self.assertIn("citation list", joined)
        self.assertIn("bullet points", joined)
        self.assertEqual(format_reasons("Woof! Andrea deployed on Cloud Run."), [])

    def test_evaluator_flags_a_leaked_citation_list_without_any_expectation(self):
        case = {"id": "t", "language": "en", "must_contain": ["django"]}
        reasons = evaluate_case(
            case,
            reply="Woof! He used Django.\n[1, 2]",
            interview_requested=False,
            detected_language="en",
        )
        self.assertEqual(len(reasons), 1)
        self.assertIn("prose", reasons[0])

    def test_evaluator_checks_the_citations(self):
        case = {
            "id": "t",
            "language": "en",
            "cites_any": ["profile"],
            "cites_something": True,
        }
        self.assertEqual(
            evaluate_case(
                case,
                reply="Woof! Sure.",
                interview_requested=False,
                detected_language="en",
                sources=[_citation(label="profile", title="Career profile", lines="")],
            ),
            [],
        )
        # No citation at all: both citation expectations fail.
        missing = evaluate_case(
            case,
            reply="Woof! Sure.",
            interview_requested=False,
            detected_language="en",
            sources=[],
        )
        self.assertEqual(len(missing), 2)
        # The legacy shape (a bare label per citation) still counts.
        legacy = evaluate_case(
            case,
            reply="Woof! Sure.",
            interview_requested=False,
            detected_language="en",
            sources=["latorreandrea/fiestapa"],
        )
        self.assertEqual(len(legacy), 1)
        self.assertIn("cites: expected one of", legacy[0])

    def test_validation_rejects_a_malformed_citation_expectation(self):
        problems = validate_golden_set(
            {
                "cases": [
                    {"id": "x", "language": "en", "question": "Q", "cites_any": "profile"},
                    {"id": "y", "language": "da", "question": "Q", "cites_something": "yes"},
                ]
            }
        )
        self.assertTrue(
            any("'cites_any' must be a list of strings" in item for item in problems)
        )
        self.assertTrue(
            any("'cites_something' must be a boolean" in item for item in problems)
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


_BARKAI_README_URL = "https://github.com/latorreandrea/barkAI/blob/main/README.md"


def _passages() -> list[dict]:
    """The numbered passages a retrieval run hands to the model (see chat.rag)."""
    return [
        {
            "id": 1,
            "label": "profile",
            "title": "Andrea Latorre — career profile",
            "url": "https://example.test/andrea_profile.md",
            "lines": "",
        },
        {
            "id": 2,
            "label": "latorreandrea/barkAI",
            "title": "Deployment",
            "url": _BARKAI_README_URL,
            "lines": "120-148",
        },
    ]


def _citation(**overrides) -> dict:
    """A stored/API citation: the shape ``_resolve_citations`` returns."""
    payload = {
        "label": "latorreandrea/barkAI",
        "title": "Deployment",
        "url": _BARKAI_README_URL,
        "lines": "120-148",
    }
    payload.update(overrides)
    return payload


class SourceCitationTests(TestCase):
    """Citations: the model proposes passage numbers, the server resolves them."""

    def test_numbers_resolve_to_the_retrieved_passages(self):
        kept = _resolve_citations([2, 1], _passages())
        self.assertEqual(
            [item["label"] for item in kept], ["latorreandrea/barkAI", "profile"]
        )
        # The link and the line range come from the index, never from the model.
        self.assertEqual(kept[0]["url"], _BARKAI_README_URL)
        self.assertEqual(kept[0]["lines"], "120-148")
        self.assertEqual(kept[0]["title"], "Deployment")
        self.assertEqual(kept[1]["lines"], "")

    def test_invented_numbers_and_duplicates_are_dropped(self):
        kept = _resolve_citations([2, 99, 2, True, None, "1"], _passages())
        self.assertEqual(
            [item["label"] for item in kept], ["latorreandrea/barkAI", "profile"]
        )

    def test_legacy_labels_still_resolve(self):
        # The prompt used to ask for labels, and a stored answer may still cite one.
        kept = _resolve_citations(
            [" LATORREANDREA/BARKAI#L120-L148 ", "invented/repo"], _passages()
        )
        self.assertEqual([item["label"] for item in kept], ["latorreandrea/barkAI"])

    def test_everything_is_dropped_without_a_retrieved_passage(self):
        self.assertEqual(_resolve_citations([1], []), ())
        self.assertEqual(_resolve_citations("not-a-list", _passages()), ())

    @override_settings(GROQ_API_KEY="test-key")
    @patch(
        "chat.services._knowledge_for_prompt",
        return_value=("ground truth", _passages()),
    )
    @patch(
        "chat.services._call_groq",
        return_value=json.dumps(
            {
                "reply": "Woof! Grounded facts.",
                "interview_requested": False,
                "suggest_questions": False,
                "sources": [2, 99],
            }
        ),
    )
    def test_invented_citations_never_reach_the_caller(self, _call, _knowledge):
        result = generate_reply("Tell me about barkAI")
        self.assertEqual(
            [item["label"] for item in result.sources], ["latorreandrea/barkAI"]
        )
        self.assertEqual(result.sources[0]["lines"], "120-148")

    def test_citable_passages_block_lists_the_numbers(self):
        prompt = build_system_prompt("facts", "en", _passages())
        self.assertIn("CITABLE PASSAGES", prompt)
        self.assertIn("[1] profile · Andrea Latorre — career profile", prompt)
        self.assertIn("[2] latorreandrea/barkAI · Deployment · lines 120-148", prompt)

    def test_no_passages_prompt_asks_for_an_empty_list(self):
        prompt = build_system_prompt("facts", "en", [])
        self.assertIn("none available", prompt)

    @override_settings(GROQ_API_KEY="")
    def test_api_returns_and_persists_the_citations(self):
        session_id = uuid4()
        citation = _citation()
        with patch(
            "chat.api.router.generate_reply",
            return_value=BarkleyResponse(
                reply="Woof! Grounded answer.",
                barkley_state="speaking",
                interview_requested=False,
                sources=(citation,),
            ),
        ):
            response = self.client.post(
                "/api/chat/send",
                data=json.dumps({"session_id": str(session_id), "message": "hi"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"], [citation])

        session = ChatSession.objects.get(session_id=session_id)
        assistant = session.messages.get(sender=ChatMessage.Sender.ASSISTANT)
        self.assertEqual(assistant.sources, [citation])

        history = self.client.get(f"/api/chat/history/{session_id}").json()
        self.assertEqual(history["messages"][-1]["sources"], [citation])

    def test_legacy_label_citations_still_serialize(self):
        # A row written when a citation was a bare label must still render.
        session = ChatSession.objects.create()
        ChatMessage.objects.create(
            session=session,
            sender=ChatMessage.Sender.ASSISTANT,
            content="Woof!",
            sources=["latorreandrea/barkAI"],
        )
        payload = self.client.get(f"/api/chat/history/{session.session_id}").json()
        self.assertEqual(
            payload["messages"][0]["sources"],
            [{"label": "latorreandrea/barkAI", "title": "", "url": "", "lines": ""}],
        )

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


class RunScheduledJobsTests(TestCase):
    """The maintenance chain that the Cloud Run job runs."""

    TARGET = "chat.management.commands.run_scheduled_jobs.call_command"

    def test_dry_run_lists_the_steps_without_running_them(self):
        out = StringIO()
        with patch(self.TARGET) as call:
            call_command("run_scheduled_jobs", "--dry-run", stdout=out)
        self.assertFalse(call.called)
        output = out.getvalue()
        self.assertIn("sync_knowledge --prune", output)
        self.assertIn("knowledge_status --fail-on-stale", output)

    def test_every_step_runs_in_order(self):
        out = StringIO()
        with patch(self.TARGET) as call:
            call_command("run_scheduled_jobs", stdout=out)
        names = [args[0] for args, _kwargs in call.call_args_list]
        self.assertEqual(
            names,
            [
                "sync_knowledge",
                "build_index",
                "retry_interview_notifications",
                "knowledge_status",
            ],
        )
        self.assertIn("Maintenance chain completed.", out.getvalue())

    def test_a_failing_step_does_not_stop_the_chain(self):
        out, err = StringIO(), StringIO()
        with patch(
            self.TARGET, side_effect=[None, CommandError("index exploded"), None, None]
        ) as call:
            with self.assertRaises(CommandError):
                call_command("run_scheduled_jobs", stdout=out, stderr=err)
        self.assertEqual(call.call_count, 4)  # the chain kept going
        self.assertIn("build_index", err.getvalue())  # and reported the failure

    def test_system_exit_from_a_step_is_caught(self):
        """sync_knowledge raises SystemExit on GitHub errors (a BaseException)."""
        out, err = StringIO(), StringIO()
        with patch(self.TARGET, side_effect=SystemExit(1)):
            with self.assertRaises(CommandError):
                call_command(
                    "run_scheduled_jobs",
                    "--only",
                    "sync_knowledge",
                    stdout=out,
                    stderr=err,
                )
        self.assertIn("exited with status 1", err.getvalue())

    def test_missing_github_username_is_surfaced_as_a_warning(self):
        out, err = StringIO(), StringIO()

        def writer(*args, **kwargs):
            kwargs["stdout"].write(
                "No GITHUB_USERNAME / GITHUB_EXTRA_REPOS set: skipping GitHub."
            )

        with patch(self.TARGET, side_effect=writer):
            call_command(
                "run_scheduled_jobs",
                "--only",
                "sync_knowledge",
                stdout=out,
                stderr=err,
            )
        self.assertIn("Warnings: sync_knowledge", out.getvalue())
        self.assertIn("skipping github", err.getvalue().lower())

    def test_unknown_step_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("run_scheduled_jobs", "--only", "nope", stdout=StringIO())

    def test_no_prune_drops_the_prune_flag(self):
        out = StringIO()
        with patch(self.TARGET) as call:
            call_command(
                "run_scheduled_jobs",
                "--only",
                "sync_knowledge",
                "--no-prune",
                stdout=out,
            )
        self.assertNotIn("prune", call.call_args.kwargs)


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
