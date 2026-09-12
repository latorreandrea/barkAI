"""
Root URL configuration for the barkAI project.

Each application owns its own URLconf (see chat/urls.py); this module only
mounts the Django admin, the Django Ninja REST API, and the app URLconfs.
"""
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from ninja import NinjaAPI

from chat.api.router import router as chat_router

# Central Django Ninja API instance (automatic OpenAPI docs under /api/docs).
api = NinjaAPI(
    title="barkAI API",
    version="1.0.0",
    description="REST API powering the BarklAI interactive career-agent chat.",
    docs_url="/docs/",
    openapi_url="/openapi.json",
)
api.add_router("/chat", chat_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),  # Ninja endpoints: /api/chat/*, /api/docs, /api/openapi.json
    # Language switch endpoint used by the navbar EN/DA toggle (set_language).
    path("i18n/", include("django.conf.urls.i18n")),
    # JavaScript catalog feeding chat.js's gettext() (djangojs domain).
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("chat.urls")),  # chat owns its URLconf (GET / renders the UI)
]
