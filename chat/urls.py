"""URL configuration owned by the chat application."""
from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("privacy/", views.privacy, name="privacy"),
    path("session/delete/", views.delete_session, name="delete_session"),
]