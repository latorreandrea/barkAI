# BarkAI

> *"Woof! I'm BarklAI. Ask me anything about Andrea's experience with Python, cloud
> architectures, or RAG pipelines, or request an interview directly through the chat!"*

**BarkAI** is a self-hosted, interactive AI agent acting as a personal career assistant and technical interviewer. It replaces traditional cold emailing and static PDF resumes with a real-time, interactive chat interface for recruiters and hiring managers.

Powered by a Retrieval-Augmented Generation (RAG) pipeline, BarkAI indexes open-source GitHub repositories, architecture decisions, and professional background to answer recruiter inquiries, discuss technical implementations, and automatically flag interview opportunities. The project mascot is **BarklAI**, an AI-powered Cocker Spaniel developer who "fetches" accurate data about the tech stack, past projects, and code choices.

---

## Table of Contents

- [Project Overview](#project-overview)
- [UX/UI](#ux)
- [Objectives](#objectives)
- [Core Principles](#core-principles)
- [Features & Roadmap](#features--roadmap)
  - [Implemented Features](#implemented-features)
  - [Roadmap](#roadmap)
- [Architecture](#architecture)
  - [System Overview](#system-overview)
  - [Technology Stack](#technology-stack)
  - [Data Flow](#data-flow)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Developer Guide](#developer-guide)
  - [Project layout](#project-layout)
  - [Conventions](#conventions)
  - [Useful commands](#useful-commands)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Privacy & GDPR](#privacy--gdpr)
- [SEO](#seo)
- [Integrations](#integrations)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)
- [Bug Log](#bug-log)

---

## Project Overview

**BarkAI** is a self-hosted, interactive career agent for the candidate side of recruiting: instead of reading a static resume, the recruiter talks to **BarklAI**, who fetches accurate answers about Andrea's tech stack, past projects, and code choices, and can flag an interview request in real time.

| | |
| --- | --- |
| **Version** | v0.3 — RAG retrieval · Danish/English · GDPR-ready |
| **Status** | In development |
| **Backend** | Python · Django 5.2 · Django Ninja |
| **Frontend** | Django Templates · Tailwind CSS |
| **Database** | PostgreSQL + **pgvector** (Neon) · SQLite fallback for the test suite |
| **LLM Engine** | Groq API (`qwen/qwen3.8-27b`) — JSON mode, offline fallback |
| **Embeddings** | Cloudflare Workers AI (`@cf/baai/bge-m3`, multilingual, 1024-dim) |
| **Languages** | English (source) · Danish (`da`) — auto-detected + navbar toggle |
| **License** | MIT |

---

## UX

> To be populated: user stories, strategy, scope, structure, skeleton and surface for the recruiter chat experience.

### BarklAI — the mascot

BarklAI is the face of the agent: a curious **Cocker Spaniel** with a nose for great engineers.
The breed is a deliberate metaphor — a spaniel *sniffs out* and *fetches* things, exactly what the
retrieval layer does with Andrea's repositories and career docs. His name plays on **bark + AI**, and
his voice (playful, a little cheeky, never robotic) keeps a technical conversation light.

- **Why a mascot** — talking to a friendly dog is more memorable (and less intimidating) than a form.
- **Why a Cocker Spaniel** — a scent hound that "fetches" accurate data: a stand-in for retrieval.
- **The name** — *bark* + *AI* → **BarklAI**.
- **Traits** — amber/orange palette, a comic "pop-art" speech bubble, and one MP4 reaction per state.

<!-- TODO(Andrea): completare con le fattezze reali (look, colori, perché quel design). -->

### How the animations were made

Each reaction is a short, loop-friendly **MP4** under `static/mascot/`, swapped by the UI according
to BarklAI's state: `idle`, `sniffing`, `searching`, `typing`, `speaking`, `celebrating`. The clips
blend straight into the white page (no border, no circle) and are encoded H.264 + yuv420p for the web.

<!-- TODO(Andrea): descrivere il processo di creazione dei clip (tool/software, prompt o pipeline,
     tempistiche) e la logica delle "pose" per ogni stato. -->

### Languages (Danish & English)

The recruiter-facing copy ships in **English** (source) and **Danish**. The active
language is negotiated from the browser's `Accept-Language` header
(`LocaleMiddleware`); a compact **EN/DA toggle** in the navbar stores the choice in
the session and overrides the browser. Templates use `{% trans %}` while
`chat.js` uses `gettext()` fed by Django's `JavaScriptCatalog` (`/jsi18n/`), so
server- and client-side strings share a single catalogue. The agent is instructed
to **answer in the recruiter's language**, and the bilingual embedding model lets a
Danish question retrieve English project READMEs.

---

## Objectives

> To be populated: the project objectives behind the interactive career agent.

---

## Core Principles

> To be populated: core principles and design philosophy.

---

## Features & Roadmap

### Implemented Features

1. **Persistent, login-free sessions** — every conversation is identified by a UUID (`ChatSession.session_id`), so returning recruiters are recognized across days without friction or login walls.
2. **Django Ninja REST API** — `GET /api/chat/history/{session_id}` restores a conversation and `POST /api/chat/send` persists both turns and returns BarklAI's reply.
3. **Live LLM agent (Groq)** — `chat/services.py` asks Groq (`qwen/qwen3.8-27b`) in **JSON mode** for a structured reply (`reply`, `interview_requested`, `suggest_questions`), grounded in the knowledge base and the previous conversation turns. An empty `GROQ_API_KEY`, or any network hiccup, falls back to consistent, in-character messages (no stack traces for the recruiter).
4. **Knowledge base** — `KnowledgeDocument` stores the curated career profile plus the README of every configured GitHub repository, synced **idempotently** (content hash) by `python manage.py sync_knowledge`.
5. **Interview-intent detection** — decided by the agent (`interview_requested`); the session is flagged and BarklAI switches to the `celebrating` clip.
6. **On-demand question suggestions** — when the recruiter seems unsure (`suggest_questions`) or after a spell of inactivity, the UI offers quick-question chips inside the speech bubble.
7. **Interactive Web UI** — responsive single-page chat (compact sticky header on mobile; mascot panel + chat column on desktop) styled with a single **compiled, minified Tailwind stylesheet** (`static/css/barkai.css`) and **external deferred JS** — no runtime CDN, no inline `<style>`/`<script>`, so browsers cache the assets across pages.
8. **BarklAI reaction clips** — `idle`, `sniffing`, `searching`, `typing`, `speaking` and `celebrating` MP4s under `static/mascot/` drive the mascot animation, with an emoji fallback when a clip is missing.
9. **Custom error pages** — project-level `403`, `404` and `500` templates.
10. **Environment-driven settings** — values read from the environment only (python-dotenv is intentionally not used); blank values fall back to safe defaults, and `DEBUG` defaults to `True` for a frictionless local start.
11. **Automated tests** — index view, chat REST API, the agent service (Groq mocked, no network), the knowledge sync + indexing commands, the i18n switching and the GDPR surface (34 tests; the pgvector round-trip runs only on PostgreSQL).
12. **Retrieval-augmented answers (RAG)** — the knowledge base is chunked and embedded (`KnowledgeChunk` + **pgvector**). With `RAG_ENABLED=True` only the most relevant chunks (native `<=>` cosine distance on PostgreSQL) are sent to the model; otherwise the whole corpus is stuffed into the prompt as a fallback.
13. **Bilingual UI (EN/DA)** — Django i18n (`{% trans %}` + `JavaScriptCatalog`) with `Accept-Language` detection and a navbar toggle; the agent answers in the recruiter's language.
14. **GDPR-ready** — a plain-language privacy notice (EN/DA), one-click **erasure** of the conversation (`POST /session/delete/`), a retention job (`purge_old_sessions`) and processor documentation in `docs/privacy.md`.

### Roadmap

- Send real-time **email/push notifications** to Andrea when an interview is requested.
- **Stream** the model's tokens into the speech bubble (SSE) instead of waiting for the full reply.
- Add an **HNSW index** on `KnowledgeChunk.embedding` once the corpus grows.
- Replace the placeholder mascot MP4s with real BarklAI footage.
- Serve production static files via `collectstatic` + WhiteNoise/CDN (the frontend is already compiled and minified).
- Fine-tune the persona prompt and add more per-state reactions.

---

## Architecture

### System Overview

The repository is a Django project with a thin surface: `barkai/` holds the settings and the root URLconf, where a single Django Ninja `NinjaAPI` instance is mounted at `/api/` and the chat app is mounted at `/`. All chat logic lives in the `chat/` app: models, API package, service layer, templates and URLconf.

### Technology Stack

- **Backend:** Django 5.2 · Django Ninja 1.7 · django-cors-headers · Pydantic 2
- **Language:** Python 3.11+
- **Database:** PostgreSQL + **pgvector** via a single `DATABASE_URL` (Neon in dev and prod). Without that variable the app falls back to zero-config SQLite — handy for a quick look, but no vector search.
- **Frontend:** Django Templates + Tailwind CSS (compiled with the Tailwind CLI into one minified `barkai.css`; no runtime CDN)
- **i18n:** Django locales (`locale/da/…`) + `LocaleMiddleware` + `JavaScriptCatalog`, compiled by `scripts/compile_messages.py` (pure Python, no gettext required)
- **Mascot media:** MP4 reaction clips in `static/mascot/`
- **LLM Engine:** Groq API — `qwen/qwen3.8-27b`, via the `groq` SDK in JSON mode (structured output)
- **Embeddings:** Cloudflare Workers AI — `@cf/baai/bge-m3` (multilingual, 1024-dim) over REST via `httpx`
- **Knowledge ingestion:** `httpx` against the GitHub REST API (see the `sync_knowledge` command)

### Data Flow

1. The recruiter opens the chat; the browser creates a `session_id` (UUID) or reuses the `?session_id=` from a shared link.
2. On load the UI calls `GET /api/chat/history/{session_id}` and renders the persisted conversation (the session is created on first contact).
3. Sending a message issues a CSRF-protected `POST /api/chat/send`.
4. With **RAG enabled** the message is embedded (`chat/embeddings.py`) and the closest chunks are fetched from `KnowledgeChunk` (`chat/rag.py`); otherwise the whole `KnowledgeDocument` corpus is used. Either way the router persists the user turn, rebuilds the conversation history and delegates the reply to `chat.services.generate_reply()`, which asks **Groq** (JSON mode) for a structured answer.
5. The API responds with `{reply, barkley_state, interview_requested, suggest_questions}`; the UI switches BarklAI's reaction clip (`searching` while working, `speaking` for the answer, `celebrating` for interview requests) and, when `suggest_questions` is true, offers the quick-question chips inside the bubble.
6. The active language comes from `Accept-Language` (or the navbar toggle), so both the UI copy and the agent's answer follow the recruiter's language.

### Retrieval pipeline (RAG)

```
knowledge source           indexing (offline)           query time
────────────────           ──────────────────           ──────────
career profile ┐           sync_knowledge               embed(message)
GitHub READMEs ┘ ────────▶ build_index  ──▶ KnowledgeChunk ──▶ cosine search ──▶ top-K ──▶ prompt
                                           (+ embedding)      (pgvector `<=>`)
```

1. `sync_knowledge` stores each source as a `KnowledgeDocument` (curated profile + every README).
2. `build_index` splits them into **paragraph-aware chunks** and embeds only the new/changed ones
   (content hash) with the configured provider, storing 1024-dim vectors in `KnowledgeChunk` (pgvector).
3. At query time `chat/rag.py` embeds the question and retrieves the closest chunks
   (`CosineDistance` on PostgreSQL; a Python cosine fallback on other backends), which are injected
   into the system prompt.
4. `RAG_ENABLED=False` — or a missing embedding provider — gracefully falls back to stuffing the
   whole corpus into the prompt, so the agent never breaks.

Both indexing steps can run **from your laptop against the production database**: they only need the
database and the embedding credentials.

---

## Setup & Installation

Requirements: Python 3.11+ and Node.js 20+ (only for rebuilding the compiled Tailwind CSS).

```bash
# 1. Create & activate the virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies (pinned snapshot from pip freeze)
python -m pip install -r requirements.txt

# 3. Load environment variables (no python-dotenv is used on purpose)
set -a; source .env; set +a

# 4. Apply migrations (creates the pgvector extension on PostgreSQL)
python manage.py migrate

# 5. Load BarklAI's knowledge base (career profile + GitHub READMEs)
python manage.py sync_knowledge

# 6. Chunk + embed it (needs EMBEDDING_PROVIDER=cloudflare)
python manage.py build_index

# 7. Compile the translation catalogues (pure Python, no gettext needed)
python scripts/compile_messages.py

# 8. Start the dev server
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and start chatting with BarklAI.

#### Environment variables

All variables live in `.env` (gitignored) and are read with `os.getenv()`. A variable that is present
but **blank** falls back to its default, so you only set what you need.

| Variable | Purpose | Where to get the value |
| --- | --- | --- |
| `GROQ_API_KEY` | Groq key for the live agent. Leave empty to run the offline fallback. | <https://console.groq.com> → *API Keys* |
| `GROQ_MODEL` | Model id (default `qwen/qwen3.8-27b`). | Groq console → *Models* |
| `GROQ_TIMEOUT_SECONDS` | Per-request timeout (default `20`). | your choice |
| `GROQ_MAX_TOKENS` | Max answer tokens (default `512`; keep it ≤ 1000 on the free tier). | your choice |
| `GROQ_TEMPERATURE` | Sampling temperature (default `0.5`). | your choice |
| `AGENT_HISTORY_LIMIT` | Previous turns sent as context (default `20`). | your choice |
| `AGENT_KNOWLEDGE_MAX_CHARS` | Knowledge text injected into the prompt (default `12000`). | your choice |
| `GITHUB_USERNAME` | GitHub user whose repositories' READMEs are ingested. | `github.com/<username>` |
| `GITHUB_EXTRA_REPOS` | Extra repos under **other** accounts: comma-separated `owner/repo` (a full GitHub URL works too). | those repos' URLs |
| `GITHUB_TOKEN` | *(optional)* PAT for private repos / higher rate limits. | GitHub → *Settings → Developer settings → Personal access tokens* |
| `GITHUB_INCLUDE_FORKS` | Ingest forks too (default `false`). | your choice |
| `GITHUB_API_TIMEOUT_SECONDS` | GitHub API timeout (default `15`). | your choice |
| `GITHUB_README_MAX_CHARS` | Max characters stored per README (default `8000`). | your choice |
| `DATABASE_URL` | PostgreSQL connection string (Neon/Supabase). Needed for pgvector; blank → SQLite. | your database provider |
| `EMBEDDING_PROVIDER` | Embeddings backend: `cloudflare` or `none` (default). | your choice |
| `EMBEDDING_MODEL` | Embedding model id (default `@cf/baai/bge-m3`). | Cloudflare model catalogue |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account id for Workers AI. | Cloudflare dashboard → Workers AI → *Use REST API* |
| `CLOUDFLARE_API_TOKEN` | Workers AI API token. | same page → *Create a Workers AI API Token* |
| `EMBEDDING_DIMENSIONS` | Vector size (default `1024`). | must match the model |
| `EMBEDDING_BATCH_SIZE` | Texts per embedding request (default `32`). | your choice |
| `RAG_ENABLED` | Use retrieval instead of stuffing the whole corpus (default `false`). | your choice |
| `RAG_TOP_K` | Chunks injected into the prompt (default `5`). | your choice |
| `RAG_MIN_SCORE` | Minimum cosine similarity (default `0.25`). | your choice |
| `RAG_CHUNK_MAX_CHARS` | Max characters per chunk while indexing (default `1200`). | your choice |
| `SESSION_RETENTION_DAYS` | Conversation retention window (default `90`). | your choice |
| `PRIVACY_CONTACT_EMAIL` | Address shown in the privacy notice. | your choice |

> For the full experience set `GROQ_API_KEY`, `DATABASE_URL` (PostgreSQL + pgvector),
> `EMBEDDING_PROVIDER=cloudflare` with `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`,
> `RAG_ENABLED=True` and `GITHUB_USERNAME`. Everything else has a sensible default, and blank
> values never break the app.

> The compiled `static/css/barkai.css` is committed, so a fresh clone runs without Node.js. Only run the build below when you add/change Tailwind classes or the site-wide custom CSS.

> `DEBUG` defaults to `True` when unset. For production always export `DEBUG=False`, a strong `SECRET_KEY` and either `DATABASE_URL` or the `DB_*` credentials.

---

## Usage

Open the chat at <http://127.0.0.1:8000/> and ask BarklAI about Andrea's projects or tech stack — or write that you would like to schedule an interview: BarklAI flags the opportunity and celebrates. The conversation survives page reloads; share the URL with its `?session_id=` to continue the same session elsewhere.

Useful URLs:

* Web UI (chat with BarklAI): <http://127.0.0.1:8000/>
* Privacy notice: <http://127.0.0.1:8000/privacy/>
* Swagger/OpenAPI docs: <http://127.0.0.1:8000/api/docs>
* Django admin: <http://127.0.0.1:8000/admin/>

---

## API Reference

Interactive docs are served by Django Ninja at `/api/docs` (raw OpenAPI schema at `/api/openapi.json`).

### GET /api/chat/history/{session_id}

Returns the persisted conversation for the session, creating it if it does not exist yet.
Response: `{session_id, interview_requested, messages: [{id, sender, content, created_at}]}`.

### POST /api/chat/send

Persists the recruiter turn, generates BarklAI's reply and persists it too.
Request body: `{session_id, message, hr_name?, hr_email?, company_name?}`.
Response: `{session_id, reply, barkley_state, interview_requested, suggest_questions}` — `barkley_state` drives the mascot clip (e.g. `speaking`, `celebrating`, `searching`) and `suggest_questions` tells the UI to offer the quick-question chips.

### POST /session/delete/

Erases the requester's conversation (**GDPR** right to erasure). Body: `{session_id}`; returns
`{deleted: true}` (or `400` for a malformed id). CSRF-protected like the chat API.

### GET /privacy/

Renders the privacy notice (English or Danish, following the active language).

### Language endpoints

* `POST /i18n/setlang/` — Django's `set_language` view, used by the navbar EN/DA toggle.
* `GET /jsi18n/` — the JavaScript message catalogue (`djangojs` domain) consumed by `chat.js`.

---

## Developer Guide

### Project layout

```
barkai/                  # project settings + root URLconf (Ninja API mounted at /api/)
chat/                    # the chat application
├── api/                 # Django Ninja package (schemas.py + router.py)
├── management/commands/ # sync_knowledge · build_index · purge_old_sessions
├── knowledge/           # andrea_profile.md (curated career profile, versioned)
├── embeddings.py        # pluggable embedding providers (Cloudflare Workers AI)
├── rag.py               # retrieval: pgvector search / Python cosine fallback
├── models.py            # ChatSession + ChatMessage + KnowledgeDocument + KnowledgeChunk
├── prompts.py           # BarklAI persona + structured-output contract
├── services.py          # the agent: Groq call, tolerant JSON parsing, fallbacks
├── templates/chat/      # app-scoped templates (index.html, privacy.html)
└── urls.py              # chat owns its URLconf
templates/               # project-level templates (base.html, partials/, 403/404/500, includes/toasts)
static/css/              # source.css (Tailwind input) + compiled barkai.css + page CSS (chat.css)
static/js/               # shared navbar.js (base) + chat.js (chat page only)
static/mascot/           # BarklAI reaction MP4s (idle, searching, speaking, …)
locale/da/LC_MESSAGES/   # Danish .po/.mo catalogues (django + djangojs domains)
scripts/                 # compile_messages.py — pure-Python .mo compiler (no gettext)
docs/                    # privacy.md — GDPR notes: processors, retention, rights
package.json             # frontend build scripts (Tailwind CLI)
tailwind.config.js       # content globs + theme (fonts, brand palette)
.env                     # local env vars (gitignored) — load with `set -a; source .env; set +a`
```

### Conventions

- **Environment-driven settings** — read via `os.getenv()`; python-dotenv is intentionally not used. Export variables before running: `set -a; source .env; set +a`.
- **Apps own their pieces** — `chat/` ships its own `urls.py`, views, templates and API package; project-level `templates/` only covers the shared shell (`base.html`), the error pages and the toast includes.
- **Service seam** — `chat/services.py` owns the agent: it calls Groq (JSON mode) when `GROQ_API_KEY` is set and otherwise returns consistent, in-character fallbacks. The persona + output contract live in `chat/prompts.py`, and the facts come from `KnowledgeDocument`.
- **Structured output** — the model is asked for `{reply, interview_requested, suggest_questions}`; parsing is tolerant, so a malformed answer still yields a usable reply.
- **Contractual media names** — the UI switches the mascot `<video>` to `/static/mascot/<state>.mp4`, so the clip filenames must not change (details in `static/mascot/README.md`).
- **Internationalisation** — English is the source language; mark template strings with `{% trans %}`/`{% blocktrans %}`, Python strings with `gettext`, and JS strings with `gettext()` (served by `JavaScriptCatalog`). After editing a `.po`, compile with `python scripts/compile_messages.py` (works without gettext; `makemessages`/`compilemessages` also work where gettext is installed).
- **RAG seam** — `chat/embeddings.py` is the only place that talks to an embedding provider, and `chat/rag.py` is the only place that queries vectors. Swapping provider or storage never touches the agent.
- **Same model both sides** — documents and queries must be embedded with the same provider/model, otherwise the vectors are not comparable.
- **Performance-first frontend assets** — no inline `<style>`/`<script>` and no runtime CDN. Tailwind utilities + site-wide CSS compile from `static/css/source.css` into the single minified `static/css/barkai.css` loaded by `base.html`; page CSS/JS (`static/css/chat.css`, `static/js/chat.js`) load only on the pages that use them, both via `{% static %}` so the browser caches them. Shared JS is loaded with `defer` in `<head>` (download early, never render-blocking). Rebuild after touching any template or `source.css`:

```bash
npm install          # first time only
npm run css:build    # after adding/changing Tailwind classes or site-wide CSS
# npm run css:watch  # recompile automatically while editing
```

### Useful commands

```bash
python manage.py check              # sanity check
python manage.py migrate            # apply migrations (creates the pgvector extension)
python manage.py sync_knowledge     # (re)load the profile + GitHub READMEs into the DB
python manage.py build_index        # chunk + embed the knowledge base (RAG index)
python manage.py purge_old_sessions # delete conversations past SESSION_RETENTION_DAYS
python scripts/compile_messages.py  # rebuild the .mo translation catalogues
python manage.py runserver          # dev server
python manage.py test               # run the test suite
npm run css:build                   # rebuild static/css/barkai.css after template changes
```

---

## Testing

```bash
python manage.py test
```

The suite (`chat/tests.py`, **34 tests**) covers: the index view; the history endpoint; `send` persisting both turns; the interview flag; the agent service with the **Groq client mocked** (JSON parsing, friendly fallbacks, offline interview heuristic) so no network or key is required; the knowledge commands (`sync_knowledge`, `build_index` chunking + hash idempotency, `purge_old_sessions`); the i18n switching (browser detection, session toggle, JS catalogue); the GDPR surface (privacy notice, erasure endpoint); and the `403`/`404`/`500` pages.

Tests run against **SQLite** by default — fast, offline, no database server needed. The single **pgvector** round-trip test is skipped there and runs on PostgreSQL:

```bash
set -a; source .env; set +a
python manage.py test chat.tests.RagVectorTests --keepdb   # runs against Neon
```

> `--keepdb` keeps the test database around: Neon's connection pooler otherwise blocks the drop at teardown.

---

## Deployment

> Hosting and CI/CD are to be defined. The production checklist currently supported by the codebase:

* Export `DEBUG=False` and a strong `SECRET_KEY`.
* Point `DATABASE_URL` at a **PostgreSQL + pgvector** instance (Neon/Supabase free tiers work); `migrate` creates the `vector` extension automatically.
* Export `GROQ_API_KEY`, `EMBEDDING_PROVIDER=cloudflare` with `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`, `RAG_ENABLED=True`, `GITHUB_USERNAME` (and `GITHUB_TOKEN` for private repos).
* Pin `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
* Run `python manage.py migrate && python manage.py collectstatic --noinput` and serve `staticfiles/` (WhiteNoise or a CDN).
* Refresh the knowledge base on deploy or on a schedule: `python manage.py sync_knowledge && python manage.py build_index`.
* Schedule `python manage.py purge_old_sessions` so the retention promised in the privacy notice is real.
* The deployable artifact is kept small on purpose (target **< 60 MB**): no local ML model ships — embeddings are an HTTP call.

> Hosting suggestion: **Google Cloud Run** (scale-to-zero, generous free tier) + **Neon** for PostgreSQL — effectively free at portfolio traffic.

---

## Privacy & GDPR

BarkAI is built GDPR-aware (a Danish/EU audience), and the pieces are concrete rather than aspirational:

* **Transparency** — a plain-language **privacy notice** at `/privacy/` (English/Danish), linked from the footer and from the chat composer.
* **No training on your data** — Groq and Cloudflare Workers AI do **not** train on the content they process, so no consent checkbox is needed for the chat itself.
* **Right to erasure** — the *"Delete my conversation"* button calls `POST /session/delete/`; the session and its messages are deleted immediately.
* **Minimisation / retention** — `python manage.py purge_old_sessions` deletes conversations older than `SESSION_RETENTION_DAYS` (default 90).
* **Records** — processors, legal bases and an Art. 30 summary live in [`docs/privacy.md`](docs/privacy.md), including the DPA checklist.

> This is engineering documentation, not legal advice: have the notice reviewed before real production use.

---

## Security

* Secrets live in environment variables only (`.env` is gitignored and not parsed at runtime — no python-dotenv). This covers `SECRET_KEY`, `GROQ_API_KEY`, `CLOUDFLARE_API_TOKEN` and `GITHUB_TOKEN`.
* The Groq, Cloudflare and GitHub keys are used **server-side only** and are never sent to the browser (the client only talks to the Django API).
* JSON `POST`s are CSRF-protected: the UI sends the `X-CSRFToken` header together with the session cookie — this also protects `POST /session/delete/`.
* A conversation can be erased on demand (`POST /session/delete/`) and by age (`purge_old_sessions`), satisfying the GDPR rights to erasure and minimisation.
* `DEBUG` must be `False` in production and a strong `SECRET_KEY` exported.
* CORS trusts all origins only while `DEBUG=True` and `CORS_ALLOWED_ORIGINS` is empty; production must pin the allowed origins.

> To be populated: HTTPS, secrets manager and further production hardening notes.

---

## SEO

> To be populated: `sitemap.xml`, `robots.txt`, Open Graph / Twitter Card metadata. A base `<meta name="description">` and `<meta name="keywords">` are already emitted by `templates/base.html`.

---

## Integrations

* **Groq** (Qwen 3.8 27B) — the live agent, via the `groq` SDK in JSON mode. Key: `GROQ_API_KEY`.
* **Cloudflare Workers AI** — embeddings for retrieval (`@cf/baai/bge-m3`), via `httpx`. Config: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`.
* **GitHub REST API** — README ingestion for the knowledge base, via `httpx`. Config: `GITHUB_USERNAME`, `GITHUB_EXTRA_REPOS`, `GITHUB_TOKEN`.
* **Neon** — managed PostgreSQL providing the `pgvector` extension (`DATABASE_URL`).
* Planned: **email/push notifications** on interview requests and token streaming (see the Roadmap).

---

## Troubleshooting

> To be populated: common issues and their fixes.

---

## Credits

> To be populated. The current BarklAI reaction MP4s are small generated placeholder clips (see `static/mascot/README.md`) and the favicon is an inline dog-emoji SVG — both will be credited or replaced when real assets land.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

## Bug Log

Living log of known issues and their lifecycle. New bugs are added here as they are discovered; the status is updated when a fix lands.

**Status legend:** 🔴 Active — bug still present · 🔶 Known — documented, non-blocking (to be fixed later) · ✅ Fixed — resolved and verified.

| ID | Status | Bug | Discovered | Fixed | How it was fixed |
| --- | --- | --- | --- | --- | --- |

> When a new bug is found, add a row with status 🔴 **Active**, the discovery date and a short description, then fill in the **Fixed** date and the resolution once a fix is verified.
