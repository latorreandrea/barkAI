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
- [Agent Hardening (v0.4)](#agent-hardening-v04)
  - [Language parity (EN and DA)](#language-parity-en-and-da)
  - [Grounded answers](#grounded-answers)
  - [Interview hand-off](#interview-hand-off)
  - [Abuse protection](#abuse-protection)
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
  - [Roles](#roles)
  - [What is processed](#what-is-processed)
  - [Legal bases](#legal-bases)
  - [Processors and data usage](#processors-and-data-usage)
  - [Retention](#retention)
  - [Data-subject rights](#data-subject-rights)
  - [Transfers outside the EU](#transfers-outside-the-eu)
  - [Cookies and local storage](#cookies-and-local-storage)
  - [Art. 30 record (summary)](#art-30-record-summary)
  - [Contact](#contact)
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
| **Version** | v0.4 — language guard · interview hand-off · hardened grounding |
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
to **answer in the recruiter's language** (now enforced by a detect-and-retry guard — see
[Language parity](#language-parity-en-and-da)), and the bilingual embedding model lets a
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
4. **Knowledge base** — `KnowledgeDocument` stores the curated career profile plus the README of every configured GitHub repository, synced **idempotently** (content hash) by `python manage.py sync_knowledge`. Repositories listed in `GITHUB_EXCLUDE_REPOS` are skipped, and `--prune` deletes whatever is no longer sourced.
5. **Interview-intent detection + hand-off** — decided by the agent (`interview_requested`); the session is flagged, BarklAI switches to the `celebrating` clip, a **contact form** appears in the composer, and every capture becomes an `InterviewRequest` row (who, how to reply, when) with an **email notification** to Andrea — see [Agent Hardening](#agent-hardening-v04).
6. **On-demand question suggestions** — when the recruiter seems unsure (`suggest_questions`) or after a spell of inactivity, the UI offers quick-question chips inside the speech bubble.
7. **Interactive Web UI** — responsive single-page chat (compact sticky header on mobile; mascot panel + chat column on desktop) styled with a single **compiled, minified Tailwind stylesheet** (`static/css/barkai.css`) and **external deferred JS** — no runtime CDN, no inline `<style>`/`<script>`, so browsers cache the assets across pages.
8. **BarklAI reaction clips** — `idle`, `sniffing`, `searching`, `typing`, `speaking` and `celebrating` MP4s under `static/mascot/` drive the mascot animation, with an emoji fallback when a clip is missing.
9. **Custom error pages** — project-level `403`, `404` and `500` templates.
10. **Environment-driven settings** — values read from the environment only (python-dotenv is intentionally not used); blank values fall back to safe defaults, and `DEBUG` defaults to `True` for a frictionless local start.
11. **Automated tests** — index view, chat REST API, the agent service (Groq mocked, no network), the knowledge sync + indexing commands, the i18n switching, the interview hand-off + notifications, the guardrails and the GDPR surface (**65 tests**; the pgvector round-trip runs only on PostgreSQL).
12. **Retrieval-augmented answers (RAG)** — the knowledge base is chunked and embedded (`KnowledgeChunk` + **pgvector**). With `RAG_ENABLED=True` only the most relevant chunks (native `<=>` cosine distance on PostgreSQL) are sent to the model; the curated **career profile is always injected verbatim** and kept out of the similarity search (see below), so it cannot crowd the project chunks out of the prompt. Without RAG the whole corpus is stuffed into the prompt as a fallback.
13. **Bilingual UI and agent (EN/DA)** — Django i18n (`{% trans %}` + `JavaScriptCatalog`) with `Accept-Language` detection and a navbar toggle; the agent answers in the recruiter's language, enforced by a detect-and-retry **language guard** (see [Language parity](#language-parity-en-and-da)).
14. **GDPR-ready** — a plain-language privacy notice (EN/DA), one-click **erasure** of the conversation (`POST /session/delete/`), a retention job (`purge_old_sessions`) and the full processing register inline in [Privacy & GDPR](#privacy--gdpr).
15. **Durable interview records** — `InterviewRequest` models a request as an *event* (name, email, company, triggering message, language, `created_at`, `notified_at`), so a recruiter who corrects their address produces a second record instead of overwriting history. Rows cascade with the session, so erasure and retention remove them too.
16. **Interview notification email** — `chat/notifications.py` emails Andrea the recruiter's details (SMTP through `EMAIL_BACKEND`) and stamps `notified_at`. The send is **idempotent**, never raises into the request cycle, and `retry_interview_notifications` recovers whatever is still pending.
17. **Public-endpoint guardrails** — a message length cap plus fixed-window rate limiting per session and per IP (`chat/throttle.py`), so a public LLM endpoint cannot be trivially drained.
18. **SMTP self-check** — `python manage.py send_test_email` proves the mail configuration (e.g. a Gmail app password) before you trust the notifications.

### Roadmap

- Add **push** (browser/Slack) notifications next to the email, and move the send to a background task queue so no interview turn ever waits on SMTP.
- **Stream** the model's tokens into the speech bubble (SSE) instead of waiting for the full reply.
- Add an **HNSW index** on `KnowledgeChunk.embedding` once the corpus grows.
- Replace the placeholder mascot MP4s with real BarklAI footage.
- Serve production static files via `collectstatic` + WhiteNoise/CDN (the frontend is already compiled and minified).
- Fine-tune the persona prompt and add more per-state reactions.

---

## Agent Hardening (v0.4)

> The v0.3 agent was tested live (real Groq + Neon + Cloudflare) instead of only through mocks. That
> probe exposed three defects that made the Danish market and the interview hand-off unreliable. This
> section documents each one, how it was found and how it is fixed — the same three are tracked as
> ✅ rows in the [Bug Log](#bug-log).

### Language parity (EN and DA)

**The bug.** The structured-output contract asked the model for a `reply` **"in English"**, while the
persona asked it to mirror the recruiter's language. The contract won: in the live probe **2 of 3
Danish questions came back in English**, including a Danish interview request.

**The fix.** Three layers, all covered by tests:

1. the contract no longer names a language — the `LANGUAGE` rule does;
2. `build_system_prompt(knowledge, language)` carries the *active interface language* as the fallback
   for one-word messages, so an ambiguous "Ok" cannot flip an answer;
3. `chat/services.py` detects the language of the message (`detect_language()` — Danish letters and
   stopwords, no ML dependency) and, when the reply is *confidently* in the wrong language, asks the
   model **once more** with an explicit "rewrite it in Danish" correction. `AGENT_LANGUAGE_GUARD`
   (default `true`) turns the retry off, and a failed retry keeps the first answer, so a bad guard can
   never lose a reply.

The offline fallback follows the message language too (`translation.override`), and the Danish
interview heuristics (`samtale`, `møde`, `booke`, `aftale`, `ringe`, `opkald`…) were missing entirely —
with Groq down, a Danish recruiter was never flagged.

| Live probe | v0.3 | v0.4 |
| --- | --- | --- |
| `Hvilke erfaringer har Andrea med Django?` | ✅ DA | ✅ DA |
| `Har Andrea erfaring med Kubernetes og Rust?` | ❌ EN | ✅ DA |
| `Kan vi booke et interview…?` | ❌ EN | ✅ DA — and asks for name/email |
| `What Google Cloud services…?` | ✅ EN | ✅ EN |

### Grounded answers

A live probe showed the agent adding **Firestore, Cloud Build and Secret Manager** to Andrea's Google
Cloud experience — none of which appear anywhere in the knowledge base (verified with `grep` across
`chat/knowledge/` and all 21 synced READMEs). The persona's "never invent facts" was too soft, so it
became an explicit `GROUNDING_RULES` block:

* mention only skills, services, employers and numbers that appear in the ground truth;
* never add a plausible-sounding extra — say what is missing and offer the closest fact that *is* there;
* never quote or allude to personal identifiers. The CPR number appears in the profile only as
  authorisation, and the model used to echo it ("resident with CPR"); it may now state only that Andrea
  is eligible to work in Denmark.

The honest-answer behaviour was already good and is now regression-tested: *"Does Andrea have
experience with Kubernetes, Terraform and Rust?"* gets a clear, grounded **no**.

### Interview hand-off

**The gap.** The `hr_name` / `hr_email` / `company_name` columns existed and `POST /api/chat/send`
already accepted them, but **nothing ever sent them** — `chat.js` had zero references, and no form
existed. Andrea saw `interview_requested = True` with no way to reply. That is the most valuable flow
in the product, so it is now a first-class record instead of a flag:

```
recruiter asks for an interview
        │
        ▼
POST /api/chat/send ─────▶ InterviewRequest (event) ─────▶ email to Andrea (notified_at)
        │                            ▲
        ▼                            │
contact form revealed ───▶ POST /api/chat/contact   (no LLM call, so it is free)
```

* **`InterviewRequest`** (`chat/models.py`) — `session` (cascade), `hr_name`, `hr_email`,
  `company_name`, `message` (what triggered it), `language`, `created_at`, `notified_at`,
  `notification_error`. A request is an *event*, so the history stays auditable.
* **Capture rule** (`chat/interviews.py`) — a *pending* request is updated in place; an already
  notified one is reused while the email is unchanged; a **different** email creates a new event (a
  correction Andrea must hear about). `ChatSession.hr_*` stays in sync as the denormalised "latest
  contact" cache that the admin list and its search box use.
* **`POST /api/chat/contact`** — validates the email (`validate_email`, no new dependency), captures
  and notifies. It deliberately does **not** call the model, so leaving the details costs nothing and
  needs no further chat message.
* **Notification** (`chat/notifications.py`) — `send_mail` to `INTERVIEW_NOTIFY_EMAIL` with the
  recruiter's details, the triggering message and an admin deep link; the outcome is stamped on the
  row. It is idempotent, never raises into the request cycle, and
  `python manage.py retry_interview_notifications` re-sends whatever is still `notified_at IS NULL`.
* **Admin** — `InterviewRequest` has its own list (filter by notified/created) plus an inline inside
  the session page, so "who, how to reply, already notified?" is one click away.

**Gmail (or any SMTP).** Set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` and the host
variables, then prove the configuration before trusting it:

```bash
python manage.py send_test_email          # uses INTERVIEW_NOTIFY_EMAIL as the recipient
python manage.py retry_interview_notifications --dry-run
```

> Gmail requires an **App Password** (16 characters, and 2-Step Verification must be on): Google no
> longer accepts the account password for apps. Keep it in `.env` (gitignored) and remember it is
> revoked if you change your Google password. Resend, Brevo or Mailgun work with the same variables.

> Trade-off: the send is synchronous, so the interview turn can take ~1s longer. `EMAIL_TIMEOUT=10`
> plus the exception guard mean a dead SMTP server can never hang the recruiter's chat; moving it to a
> task queue is on the [Roadmap](#roadmap).

### Abuse protection

`/api/chat/send` is public and every call costs a Groq completion plus a Cloudflare embedding, so:

* `message` is capped at **2000 characters** (the composer's `maxlength` matches) — oversized input is
  a `422`;
* `chat/throttle.py` applies a fixed-window counter (Django cache) per **session** and per **IP**
  (`CHAT_RATE_LIMIT_PER_SESSION`, `CHAT_RATE_LIMIT_PER_IP`, `CHAT_RATE_LIMIT_WINDOW_SECONDS`); over the
  cap returns `429`. A limit set to `0` disables the check.

> Best-effort by design: without a shared cache the window is per worker. It stops a script, not a
> botnet — a Cloudflare/WAF rule is the next step in production.

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
6. The active language comes from `Accept-Language` (or the navbar toggle), so both the UI copy and the agent's answer follow the recruiter's language — and the reply is guarded against language drift (see [Language parity](#language-parity-en-and-da)).
7. When an interview is requested, the session gets an `InterviewRequest` event and the contact form is revealed; submitting it calls `POST /api/chat/contact`, which stores the details and emails Andrea (see [Interview hand-off](#interview-hand-off)).

### Retrieval pipeline (RAG)

```
knowledge source           indexing (offline)           query time
────────────────           ──────────────────           ──────────
career profile ┐           sync_knowledge               embed(message)
GitHub READMEs ┘ ────────▶ build_index  ──▶ KnowledgeChunk ──▶ cosine search ──▶ top-K ──▶ prompt
                                           (+ embedding)      (pgvector `<=>`)
```

1. `sync_knowledge` stores each source as a `KnowledgeDocument` (curated profile + every README,
   minus `GITHUB_EXCLUDE_REPOS`; `--prune` removes the documents that are no longer sourced).
2. `build_index` splits them into **paragraph-aware chunks** and embeds only the new/changed ones
   (content hash) with the configured provider, storing 1024-dim vectors in `KnowledgeChunk` (pgvector).
3. At query time `chat/rag.py` embeds the question and retrieves the closest chunks
   (`CosineDistance` on PostgreSQL; a Python cosine fallback on other backends), which are injected
   into the system prompt.
4. The **career profile is always injected verbatim** and is deliberately **excluded from the
   similarity search**: it is short, it applies to every question, and it used to match even the
   vaguest query — stealing the top slots from the project chunks.
5. `RAG_ENABLED=False` — or a missing embedding provider — gracefully falls back to stuffing the
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
python manage.py sync_knowledge --prune   # --prune also drops stale documents

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
| `AGENT_LANGUAGE_GUARD` | Re-ask the model exactly once when it answers in the wrong language (default `true`). | your choice |
| `GITHUB_USERNAME` | GitHub user whose repositories' READMEs are ingested. | `github.com/<username>` |
| `GITHUB_EXTRA_REPOS` | Extra repos under **other** accounts: comma-separated `owner/repo` (a full GitHub URL works too). | those repos' URLs |
| `GITHUB_TOKEN` | *(optional)* PAT for private repos / higher rate limits. | GitHub → *Settings → Developer settings → Personal access tokens* |
| `GITHUB_EXCLUDE_REPOS` | Repos to keep **out** of the knowledge base (template/boilerplate READMEs, abandoned projects): comma-separated `owner/repo`, a full GitHub URL, or just the bare repo name. | your choice |
| `GITHUB_INCLUDE_FORKS` | Ingest forks too (default `false`). | your choice |
| `GITHUB_API_TIMEOUT_SECONDS` | GitHub API timeout (default `15`). | your choice |
| `GITHUB_README_MAX_CHARS` | Max characters stored per README (default `14000`). | your choice |
| `DATABASE_URL` | PostgreSQL connection string (Neon/Supabase). Needed for pgvector; blank → SQLite. | your database provider |
| `EMBEDDING_PROVIDER` | Embeddings backend: `cloudflare` or `none` (default). | your choice |
| `EMBEDDING_MODEL` | Embedding model id (default `@cf/baai/bge-m3`). | Cloudflare model catalogue |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account id for Workers AI. | Cloudflare dashboard → Workers AI → *Use REST API* |
| `CLOUDFLARE_API_TOKEN` | Workers AI API token. | same page → *Create a Workers AI API Token* |
| `EMBEDDING_DIMENSIONS` | Vector size (default `1024`). | must match the model |
| `EMBEDDING_BATCH_SIZE` | Texts per embedding request (default `32`). | your choice |
| `RAG_ENABLED` | Use retrieval instead of stuffing the whole corpus (default `false`). | your choice |
| `RAG_TOP_K` | Chunks injected into the prompt (default `5`). | your choice |
| `RAG_MAX_PER_SOURCE` | Max chunks per document in one prompt (default `2`), so a long generic README cannot fill every slot. | your choice |
| `RAG_MIN_SCORE` | Minimum cosine similarity for a retrieved chunk (default `0.35`; the profile is excluded from the search and always injected instead). | your choice |
| `RAG_CHUNK_MAX_CHARS` | Max characters per chunk while indexing (default `1200`). | your choice |
| `SESSION_RETENTION_DAYS` | Conversation retention window (default `90`). | your choice |
| `PRIVACY_CONTACT_EMAIL` | Address shown in the privacy notice. | your choice |
| `INTERVIEW_NOTIFY_EMAIL` | Andrea's inbox for interview requests. Blank disables the notification (requests are still stored and visible in the admin). | your choice |
| `EMAIL_BACKEND` | Delivery backend. Default is the **console** backend (local runs need no SMTP); production sets `django.core.mail.backends.smtp.EmailBackend`. | your choice |
| `EMAIL_HOST` · `EMAIL_PORT` · `EMAIL_USE_TLS` · `EMAIL_USE_SSL` | SMTP endpoint. Gmail: `smtp.gmail.com`, port `587`, TLS `true`. | your mail provider |
| `EMAIL_HOST_USER` · `EMAIL_HOST_PASSWORD` | SMTP credentials. For Gmail use a **16-character App Password** (2-Step Verification required), never the account password. | Google Account → *Security → App passwords* |
| `DEFAULT_FROM_EMAIL` | `From:` header of the notifications. Quote it in `.env` when it carries a display name: `'BarkAI <you@gmail.com>'`. | your choice |
| `EMAIL_TIMEOUT` | Seconds before a mail send is abandoned (default `10`), so a dead SMTP server can never hang a chat request. | your choice |
| `SITE_BASE_URL` | Public base URL used to build the admin deep link inside the notification (blank = no link). | your deployment URL |
| `CHAT_RATE_LIMIT_PER_SESSION` | Messages allowed per session within the window (default `20`; `0` disables the check). | your choice |
| `CHAT_RATE_LIMIT_PER_IP` | Messages allowed per IP within the window (default `60`; `0` disables the check). | your choice |
| `CHAT_RATE_LIMIT_WINDOW_SECONDS` | Length of the rate-limit window (default `300`). | your choice |

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
Response: `{session_id, reply, barkley_state, interview_requested, suggest_questions}` — `barkley_state` drives the mascot clip (e.g. `speaking`, `celebrating`, `searching`) and `suggest_questions` tells the UI to offer the quick-question chips. Validation: `message` is capped at 2000 characters (`422` when exceeded) and the endpoint is rate-limited (`429`) per session and per IP. When `interview_requested` is true the session also gets an `InterviewRequest` row, and the notification goes out immediately if the payload already carried an email.

### POST /api/chat/contact

Stores the recruiter's details for an interview request — this is the hand-off form the UI reveals. It does **not** call the LLM, so leaving the details is free.
Request body: `{session_id, hr_email (required), hr_name?, company_name?}`.
Response: `{session_id, saved, notified}` — `notified` is `false` when `INTERVIEW_NOTIFY_EMAIL` is blank or the SMTP send failed (the details are stored either way). An invalid email is a `422`; the endpoint is rate-limited like `/send`.

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
├── management/commands/ # sync_knowledge · build_index · purge_old_sessions · send_test_email · retry_interview_notifications
├── knowledge/           # andrea_profile.md (curated career profile, versioned)
├── embeddings.py        # pluggable embedding providers (Cloudflare Workers AI)
├── rag.py               # retrieval: pgvector search / Python cosine fallback
├── models.py            # ChatSession + ChatMessage + KnowledgeDocument + KnowledgeChunk + InterviewRequest
├── prompts.py           # BarklAI persona + language rules + grounding rules + JSON contract
├── services.py          # the agent: Groq call, language guard, tolerant JSON parsing, fallbacks
├── interviews.py        # InterviewRequest capture rules (one event per contact capture)
├── notifications.py     # interview email: idempotent, never raises, stamps notified_at
├── throttle.py          # fixed-window rate limiting for the public chat endpoints
├── templates/chat/      # app-scoped templates (index.html, privacy.html)
└── urls.py              # chat owns its URLconf
templates/               # project-level templates (base.html, partials/, 403/404/500, includes/toasts)
static/css/              # source.css (Tailwind input) + compiled barkai.css + page CSS (chat.css)
static/js/               # shared navbar.js (base) + chat.js (chat page only)
static/mascot/           # BarklAI reaction MP4s (idle, searching, speaking, …)
locale/da/LC_MESSAGES/   # Danish .po/.mo catalogues (django + djangojs domains)
scripts/                 # compile_messages.py — pure-Python .mo compiler (no gettext)
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
- **Prompt rules live apart on purpose** — `chat/prompts.py` exposes `PERSONA`, `LANGUAGE_RULES`, `GROUNDING_RULES` and `OUTPUT_CONTRACT` as separate blocks, so the language and grounding fixes stay individually testable instead of dissolving into the persona text.
- **Language guard budget** — `chat/services.py:detect_language()` plus `AGENT_LANGUAGE_GUARD` re-ask the model **exactly once** when a reply is confidently in the wrong language. Never turn this into a retry loop: each attempt costs a Groq call.
- **Hand-off seams** — `chat/interviews.py` owns capture (which row, and when a new event starts) and `chat/notifications.py` owns delivery. Delivery must stay idempotent and must never raise into the request cycle: record the failure on `InterviewRequest.notification_error` and let `retry_interview_notifications` recover it.
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
python manage.py sync_knowledge --prune  # + delete the documents no longer sourced
python manage.py build_index        # chunk + embed the knowledge base (RAG index)
python manage.py purge_old_sessions # delete conversations past SESSION_RETENTION_DAYS
python manage.py send_test_email    # verify the SMTP settings (sends one real email)
python manage.py retry_interview_notifications  # re-send pending interview notifications
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

The suite (`chat/tests.py`, **65 tests**) covers: the index view; the history endpoint; `send` persisting both turns; the interview flag; the agent service with the **Groq client mocked** (JSON parsing, friendly fallbacks, the bilingual offline heuristics and the **language guard** — retry once, keep the first answer if the retry also fails, skip the retry when the languages match, honour `AGENT_LANGUAGE_GUARD=False`); `detect_language()` itself; retrieval (profile always injected, profile never searched, per-source diversity cap); the interview hand-off (capture rules including the corrected-email case, the `/api/chat/contact` endpoint, the notification email in a locmem outbox, "never notified twice", details stored even with notifications disabled, cascade on erasure); the guardrails (2000-character cap → `422`, throttle → `429`, `0` disables it); the knowledge commands (`sync_knowledge` incl. the `GITHUB_EXCLUDE_REPOS` filter and `--prune`, `build_index` chunking + hash idempotency, `purge_old_sessions`); the i18n switching (browser detection, session toggle, JS catalogue); the GDPR surface (privacy notice, erasure endpoint); and the `403`/`404`/`500` pages.

> The i18n tests assert Danish copy, so run `python scripts/compile_messages.py` first — `*.mo` is gitignored and therefore absent from a fresh clone.

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
* Compile the translations on deploy: `python scripts/compile_messages.py` (`*.mo` is gitignored, so a fresh checkout has none).
* Export the SMTP variables plus `INTERVIEW_NOTIFY_EMAIL` and `SITE_BASE_URL`, then verify with `python manage.py send_test_email` before relying on the notifications.
* Schedule `python manage.py purge_old_sessions` so the retention promised in the privacy notice is real.
* The deployable artifact is kept small on purpose (target **< 60 MB**): no local ML model ships — embeddings are an HTTP call.

> Hosting suggestion: **Google Cloud Run** (scale-to-zero, generous free tier) + **Neon** for PostgreSQL — effectively free at portfolio traffic.

---

## Privacy & GDPR

BarkAI is built GDPR-aware (a Danish/EU audience), and the pieces are concrete rather than aspirational:

* **Transparency** — a plain-language **privacy notice** at `/privacy/` (English/Danish), linked from the footer and from the chat composer.
* **No training on your data** — Groq and Cloudflare Workers AI do **not** train on the content they process, so no consent checkbox is needed for the chat itself.
* **Right to erasure** — the *"Delete my conversation"* button calls `POST /session/delete/`; the session, its messages and its `InterviewRequest` records (which cascade) are deleted immediately.
* **Minimisation / retention** — `python manage.py purge_old_sessions` deletes conversations older than `SESSION_RETENTION_DAYS` (default 90).

> Plain-language engineering notes, **not legal advice**: have the notice and the processing register reviewed before real production use.

### Roles

| Who | Role |
| --- | --- |
| Andrea Latorre (site owner) | **Data controller** |
| Groq | Processor — generates the chat replies |
| Cloudflare (Workers AI) | Processor — computes the embeddings for retrieval |
| GitHub | Source of the public READMEs ingested into the knowledge base |
| Hosting provider | Processor — runs the Django app |
| Neon (PostgreSQL) | Processor — stores conversations and the knowledge base |
| Mail provider (Google/Gmail SMTP by default) | Processor — delivers the interview notification to Andrea |

### What is processed

* the **messages** a recruiter sends (and the replies);
* a random **session UUID** kept in the browser (`localStorage`), the login-free identity;
* optionally a **name / email / company** if the recruiter shares them;
* when an interview is requested, those **contact details** plus the triggering message and the timestamp, stored as an `InterviewRequest` and **emailed to Andrea** through the configured mail provider;
* a flag remembering the introduction was already shown.

### Legal bases

| Purpose | Basis |
| --- | --- |
| Answering the recruiter / providing the chat | **Contract** (or pre-contractual steps) |
| Flagging an interview request | **Legitimate interest** |
| Securing the service (logs, abuse prevention) | **Legitimate interest** |

No marketing, no profiling, no selling of data. Because no processor trains on the data (see below), **no consent checkbox is required** for the chat itself.

### Processors and data usage

* **Groq** — the message text is sent to generate the answer. API data is not used to train models.
* **Cloudflare Workers AI** — the text is sent to compute embeddings. Cloudflare states it neither creates nor trains the models on Workers AI and does **not** use customer content to train/improve services without explicit consent. Models are Cloudflare-hosted (no third-party routing).
* **GitHub** — only **public** repository READMEs are read (no personal data of recruiters).
* **Mail provider (Google/Gmail by default)** — when a recruiter asks for an interview, the details they submitted are delivered to Andrea's own inbox through the configured SMTP provider. The other processors are unaffected.
* A **DPA (art. 28)** must be in place with every processor. Cloudflare and OpenAI/Google publish standard DPAs; Groq's terms apply to the API.

### Retention

Conversations are deleted automatically after `SESSION_RETENTION_DAYS` (default **90**) of inactivity. Interview requests (`InterviewRequest`) cascade from the session, so they disappear with it:

```bash
python manage.py purge_old_sessions            # uses SESSION_RETENTION_DAYS
python manage.py purge_old_sessions --days 30 --dry-run
```

Schedule it (cron / Cloud Scheduler) so reality matches the privacy notice.

### Data-subject rights

* **Access** — the conversation is visible in the chat (and in the Django admin).
* **Erasure** — the *"Delete my conversation"* button on the chat page calls `POST /session/delete/` with the session UUID and deletes the session (and its messages) immediately. `purge_old_sessions` handles the rest by age.
* **Rectification / portability / objection** — handled manually via the contact address below.

### Transfers outside the EU

Groq, Cloudflare, GitHub, Google and Neon are US-based companies: transfers rely on the **SCCs** included in their DPAs. Cloudflare additionally offers EU data localisation on enterprise plans.

### Cookies and local storage

No tracking or advertising cookies. The browser stores only:

* `barkai.session_id` — the conversation identifier (strictly necessary);
* `barkai_visited` — remembers that the introduction was already shown;
* Django's session cookie, used only to remember the chosen language (EN/DA).

Because these are strictly necessary, no cookie banner is required; they must still be described in the notice (they are).

### Art. 30 record (summary)

| Field | Value |
| --- | --- |
| Processing | Interactive recruiter chat about Andrea's career |
| Data subjects | Recruiters / hiring managers |
| Categories | Messages, session UUID, optional contact details |
| Recipients | Groq, Cloudflare, GitHub, hosting, Neon, mail provider |
| Retention | `SESSION_RETENTION_DAYS` (default 90) |
| Transfers | US processors under SCCs (DPA) |
| Security | TLS, secrets in env, CSRF-protected POSTs, rate limiting, minimal access |

### Contact

`PRIVACY_CONTACT_EMAIL` (default `latorre.andrea.93@gmail.com`).

---

## Security

* Secrets live in environment variables only (`.env` is gitignored and not parsed at runtime — no python-dotenv). This covers `SECRET_KEY`, `GROQ_API_KEY`, `CLOUDFLARE_API_TOKEN` and `GITHUB_TOKEN`.
* The Groq, Cloudflare and GitHub keys are used **server-side only** and are never sent to the browser (the client only talks to the Django API).
* JSON `POST`s are CSRF-protected: the UI sends the `X-CSRFToken` header together with the session cookie — this also protects `POST /session/delete/`.
* A conversation can be erased on demand (`POST /session/delete/`) and by age (`purge_old_sessions`), satisfying the GDPR rights to erasure and minimisation.
* `DEBUG` must be `False` in production and a strong `SECRET_KEY` exported.
* CORS trusts all origins only while `DEBUG=True` and `CORS_ALLOWED_ORIGINS` is empty; production must pin the allowed origins.
* The public chat endpoints are **rate-limited per session and per IP** and reject messages longer than 2000 characters, so a single client cannot drain the Groq/Cloudflare quota (see [Abuse protection](#abuse-protection)). Use a shared cache and a WAF rule in production.
* Mail credentials (`EMAIL_HOST_PASSWORD`, e.g. a Gmail app password) live in the environment only and are used server-side. Rotate and revoke them if they leak: an app password grants send **and** read access to that mailbox.

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
* **SMTP (provider of your choice)** — interview notifications to Andrea (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `INTERVIEW_NOTIFY_EMAIL`). Gmail works with an **app password** and `python manage.py send_test_email` verifies the setup; Resend/Brevo/Mailgun use the same variables.
* Planned: **push** notifications and token streaming (see the Roadmap).

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
| B-001 | ✅ Fixed | **Danish questions answered in English** (2 of 3 in a live probe): the JSON contract demanded an English `reply` while the persona demanded the recruiter's language, and the offline interview heuristics were English-only. | 2026-09-13 | 2026-09-13 | Dropped the hard-coded language from the contract, added `LANGUAGE_RULES` + the interface-language fallback, and a one-shot `detect_language()` retry guard (`AGENT_LANGUAGE_GUARD`). Offline fallbacks now follow the message language and the Danish interview hints were added. See [Language parity](#language-parity-en-and-da). |
| B-002 | ✅ Fixed | **Interview requests were not actionable**: the session was flagged, but no contact details were ever collected (`chat.js` never sent `hr_*` and no form existed), and nobody was notified. | 2026-09-13 | 2026-09-13 | Added the `InterviewRequest` model (event per capture), the hand-off form, `POST /api/chat/contact` (no LLM call) and the idempotent email notification with `retry_interview_notifications`. See [Interview hand-off](#interview-hand-off). |
| B-003 | ✅ Fixed | **Invented facts**: the agent added Firestore, Cloud Build and Secret Manager to Andrea's Google Cloud stack (absent from the whole knowledge base) and echoed the CPR mention. | 2026-09-13 | 2026-09-13 | Added an explicit `GROUNDING_RULES` block (facts only from the injected ground truth, no personal identifiers) plus a regression test for the "unknown technology" answer. See [Grounded answers](#grounded-answers). |

> When a new bug is found, add a row with status 🔴 **Active**, the discovery date and a short description, then fill in the **Fixed** date and the resolution once a fix is verified.
