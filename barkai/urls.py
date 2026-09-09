"""
Root URL configuration for the barkAI project.

Each application owns its own URLconf (see chat/urls.py); this module only
mounts the Django admin, the Django Ninja REST API, and the app URLconfs.
"""
from django.contrib import admin
from django.urls import include, path

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
    path("", include("chat.urls")),  # chat owns its URLconf (GET / renders the UI)
]
