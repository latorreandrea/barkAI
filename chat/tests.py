"""Smoke tests for the barkAI index view and the chat REST API."""
from uuid import uuid4

from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views import defaults

from chat.models import ChatMessage, ChatSession


class IndexViewTests(TestCase):
    def test_index_renders_app_template(self):
        response = self.client.get(reverse("chat:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "chat/index.html")


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
