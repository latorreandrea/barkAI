"""Sync BarklAI's knowledge base into the database.

Sources:
  * the curated career profile in ``chat/knowledge/andrea_profile.md``
  * the README of every repository of ``GITHUB_USERNAME``
  * the README of every repository in ``GITHUB_EXTRA_REPOS`` (comma-separated
    ``owner/repo`` slugs or full GitHub URLs — handy for projects that live
    under a different GitHub account)

Run it whenever the sources change:

    python manage.py sync_knowledge
    python manage.py sync_knowledge --profile-only

The sync is idempotent: unchanged documents are skipped (content hash).
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

from chat.models import KnowledgeDocument

PROFILE_SOURCE = "profile"
PROFILE_FILE = "andrea_profile.md"
GITHUB_API = "https://api.github.com"


def normalize_repo(entry: str) -> str | None:
    """Accept ``owner/repo`` or a GitHub URL and normalise it to ``owner/repo``."""
    entry = (entry or "").strip().rstrip("/")
    if not entry:
        return None
    if "github.com" in entry:
        tail = entry.split("github.com/", 1)[1]
        parts = [part for part in tail.split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
        return None
    if entry.count("/") == 1:
        return entry.removesuffix(".git")
    return None


class Command(BaseCommand):
    help = "Sync BarklAI's knowledge base (career profile + GitHub READMEs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile-only",
            action="store_true",
            help="Only (re)load the local career profile; skip GitHub.",
        )

    def handle(self, *args, **options):
        tally = {"created": 0, "updated": 0, "unchanged": 0}
        self._tally(self._sync_profile(), tally)

        if not options["profile_only"]:
            self._sync_github(tally)

        self._report(tally)

    # -- GitHub ----------------------------------------------------------
    def _sync_github(self, tally: dict) -> None:
        username = settings.GITHUB_USERNAME
        extra = settings.GITHUB_EXTRA_REPOS
        if not username and not extra:
            self.stdout.write(
                self.style.WARNING(
                    "No GITHUB_USERNAME / GITHUB_EXTRA_REPOS set: skipping GitHub."
                )
            )
            return
        try:
            with httpx.Client(
                headers=self._headers(),
                timeout=settings.GITHUB_API_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                for full_name in self._collect_repos(username, extra, client):
                    self._tally(self._sync_readme(full_name, client), tally)
        except httpx.HTTPError as exc:
            self.stderr.write(self.style.ERROR(f"GitHub request failed: {exc}"))
            raise SystemExit(1)

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "barkAI-sync",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
        return headers

    def _collect_repos(self, username: str, extra: list[str], client) -> list[str]:
        repos = []
        if username:
            for repo in self._list_user_repos(username, client):
                if repo.get("fork") and not settings.GITHUB_INCLUDE_FORKS:
                    continue
                repos.append(repo["full_name"])
        for entry in extra:
            full_name = normalize_repo(entry)
            if not full_name:
                self.stderr.write(
                    self.style.WARNING(f"  ! skipped invalid repo: {entry!r}")
                )
                continue
            repos.append(full_name)
        return list(dict.fromkeys(repos))  # de-duplicate, keep order

    def _list_user_repos(self, username: str, client) -> list[dict]:
        repos = []
        url = f"{GITHUB_API}/users/{username}/repos"
        params = {"per_page": 100, "sort": "updated"}
        while url:
            response = client.get(url, params=params)
            response.raise_for_status()
            repos.extend(response.json())
            url = response.links.get("next", {}).get("url")
            params = None
        return repos

    def _sync_readme(self, full_name: str, client) -> str:
        response = client.get(f"{GITHUB_API}/repos/{full_name}/readme")
        if response.status_code == 404:
            self.stdout.write(f"  - {full_name}: no README (skipped)")
            return "unchanged"
        response.raise_for_status()
        data = response.json()
        if data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", "replace")
        elif data.get("download_url"):
            content = client.get(data["download_url"]).text
        else:
            self.stdout.write(f"  - {full_name}: empty README (skipped)")
            return "unchanged"
        return self._upsert(
            kind=KnowledgeDocument.Kind.GITHUB_README,
            source=full_name,
            title=data.get("name") or f"{full_name} README",
            url=data.get("html_url", ""),
            content=content[: settings.GITHUB_README_MAX_CHARS],
        )

    # -- Local profile ---------------------------------------------------
    def _sync_profile(self) -> str:
        path = Path(settings.BASE_DIR) / "chat" / "knowledge" / PROFILE_FILE
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"Profile file not found: {path}"))
            return "unchanged"
        return self._upsert(
            kind=KnowledgeDocument.Kind.PROFILE,
            source=PROFILE_SOURCE,
            title="Andrea Latorre — career profile",
            url="",
            content=path.read_text(encoding="utf-8"),
        )

    # -- Persistence -----------------------------------------------------
    def _upsert(self, *, kind: str, source: str, title: str, url: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = KnowledgeDocument.objects.filter(kind=kind, source=source).first()
        if existing is None:
            KnowledgeDocument.objects.create(
                kind=kind,
                source=source,
                title=title,
                url=url,
                content=content,
                content_hash=digest,
            )
            self.stdout.write(self.style.SUCCESS(f"  + {source}: created"))
            return "created"
        if existing.content_hash == digest:
            self.stdout.write(f"  = {source}: unchanged")
            return "unchanged"
        existing.title = title
        existing.url = url
        existing.content = content
        existing.content_hash = digest
        existing.save()
        self.stdout.write(self.style.WARNING(f"  ~ {source}: updated"))
        return "updated"

    def _tally(self, outcome: str, tally: dict) -> None:
        if outcome in tally:
            tally[outcome] += 1

    def _report(self, tally: dict) -> None:
        self.stdout.write(
            self.style.SUCCESS(
                "Knowledge sync complete: "
                f"{tally['created']} created, {tally['updated']} updated, "
                f"{tally['unchanged']} unchanged."
            )
        )
