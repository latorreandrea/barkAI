"""Project-wide template context.

Only one value lives here for now: ``ASSET_VERSION``, the cache-buster appended
as ``?v=`` to the static assets. WhiteNoise serves ``static/`` with a one-year
``max-age`` header and the storage backend is the *non-Manifest* one, so an asset
URL never changes when its content does: without a versioned query string a
returning visitor would keep the previous ``barkai.css``/``chat.js``/mascot clip
for a year, and a deployed frontend fix would stay invisible to them.
"""

from django.conf import settings


def asset_version(request):
    """Expose the ASSET_VERSION setting to every template that cache-busts."""
    return {"ASSET_VERSION": settings.ASSET_VERSION}
