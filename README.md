# BarkAI

> *"Woof! I'm Barkley. Ask me anything about Andrea's experience with Python, cloud
> architectures, or RAG pipelines, or request an interview directly through the chat!"*

**BarkAI** is a self-hosted, interactive AI agent acting as a personal career assistant and technical interviewer. It replaces traditional cold emailing and static PDF resumes with a real-time, interactive chat interface for recruiters and hiring managers.

Powered by a Retrieval-Augmented Generation (RAG) pipeline, BarkAI indexes open-source GitHub repositories, architecture decisions, and professional background to answer recruiter inquiries, discuss technical implementations, and automatically flag interview opportunities. The project mascot is **Barkley**, an AI-powered Cocker Spaniel developer who "fetches" accurate data about the tech stack, past projects, and code choices.

A future mobile app version built with Flutter is under evaluation.

---

## Table of Contents

- [Project Overview](#project-overview)
- [UX](#ux)
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
- [SEO](#seo)
- [Integrations](#integrations)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)
- [Bug Log](#bug-log)

---

## Project Overview

**BarkAI** is a self-hosted, interactive career agent for the candidate side of recruiting: instead of reading a static resume, the recruiter talks to **Barkley**, who fetches accurate answers about Andrea's tech stack, past projects, and code choices, and can flag an interview request in real time.

| | |
| --- | --- |
| **Version** | v0.1 — Foundation (Django chat + REST API, mock agent) |
| **Status** | In development |
| **Backend** | Python · Django 5.2 · Django Ninja |
| **Frontend** | Django Templates · Tailwind CSS |
| **Database** | SQLite (dev) · PostgreSQL (prod) |
| **LLM Engine** | Groq API (Qwen 2.5) — planned, mock replies today |
| **License** | MIT |

---

## UX

> To be populated: user stories, strategy, scope, structure, skeleton and surface for the recruiter chat experience.

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
2. **Django Ninja REST API** — `GET /api/chat/history/{session_id}` restores a conversation and `POST /api/chat/send` persists both turns and returns Barkley's reply.
3. **Interview-intent detection** — keyword heuristics in `chat/services.py` detect when a recruiter asks to schedule a call; the session is flagged (`interview_requested`) and Barkley celebrates.
4. **Interactive Web UI** — responsive single-page chat (compact sticky header on mobile; mascot panel + chat column on desktop) styled with Tailwind CSS.
5. **Barkley reaction clips** — `idle`, `searching`, `typing`, `speaking` and `celebrating` MP4s under `static/mascot/` drive the mascot animation, with an emoji fallback when a clip is missing.
6. **Custom error pages** — project-level `403`, `404` and `500` templates.
7. **Environment-driven settings** — values come from `os.getenv()` only (python-dotenv is intentionally not used); `DEBUG` defaults to `True` for a frictionless local start.
8. **Automated tests** — index view, chat REST API, interview flag and error pages.

### Roadmap

- Wire `chat/services.py` to the real **Groq (Qwen 2.5) + RAG** pipeline (`GROQ_API_KEY` is already read by `barkai/settings.py`).
- Index the GitHub repositories, Markdown career docs and architecture notes into the knowledge base.
- Send real-time **email/push notifications** to Andrea when an interview is requested.
- Replace the placeholder mascot MP4s with real Barkley footage.
- Compile Tailwind to a static stylesheet and run `collectstatic` for production.
- **Flutter mobile app** version (under evaluation).

---

## Architecture

### System Overview

The repository is a Django project with a thin surface: `barkai/` holds the settings and the root URLconf, where a single Django Ninja `NinjaAPI` instance is mounted at `/api/` and the chat app is mounted at `/`. All chat logic lives in the `chat/` app: models, API package, service layer, templates and URLconf.

### Technology Stack

- **Backend:** Django 5.2 · Django Ninja 1.7 · django-cors-headers · Pydantic 2
- **Language:** Python 3.11+
- **Database:** SQLite by default in development; PostgreSQL in production via `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- **Frontend:** Django Templates + Tailwind CSS (Play CDN during development)
- **Mascot media:** MP4 reaction clips in `static/mascot/`
- **LLM Engine (planned):** Groq API — Qwen 2.5, exposed as `GROQ_API_KEY` but not wired yet

### Data Flow

1. The recruiter opens the chat; the browser creates a `session_id` (UUID) or reuses the `?session_id=` from a shared link.
2. On load the UI calls `GET /api/chat/history/{session_id}` and renders the persisted conversation (the session is created on first contact).
3. Sending a message issues a CSRF-protected `POST /api/chat/send`.
4. The router persists the user turn, delegates the reply to `chat.services.generate_reply()` (deterministic mock — the seam for the future Groq/RAG pipeline), persists Barkley's answer and flags the session when an interview is requested.
5. The API responds with `{reply, barkley_state, interview_requested}` and the UI switches Barkley's reaction clip accordingly (`searching` while working, `speaking` for the answer, `celebrating` for interview requests).

---

## Setup & Installation

Requirements: Python 3.11+.

```bash
# 1. Create & activate the virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies (pinned snapshot from pip freeze)
python -m pip install -r requirements.txt

# 3. Load environment variables (no python-dotenv is used on purpose)
set -a; source .env; set +a

# 4. Apply migrations and start the dev server
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and start chatting with Barkley.

> `DEBUG` defaults to `True` when unset. For production always export `DEBUG=False` plus the `DB_*` credentials and a strong `SECRET_KEY`.

---

## Usage

Open the chat at <http://127.0.0.1:8000/> and ask Barkley about Andrea's projects or tech stack — or write that you would like to schedule an interview: Barkley flags the opportunity and celebrates. The conversation survives page reloads; share the URL with its `?session_id=` to continue the same session elsewhere.

Useful URLs:

* Web UI (chat with Barkley): <http://127.0.0.1:8000/>
* Swagger/OpenAPI docs: <http://127.0.0.1:8000/api/docs>
* Django admin: <http://127.0.0.1:8000/admin/>

---

## API Reference

Interactive docs are served by Django Ninja at `/api/docs` (raw OpenAPI schema at `/api/openapi.json`).

### GET /api/chat/history/{session_id}

Returns the persisted conversation for the session, creating it if it does not exist yet.
Response: `{session_id, interview_requested, messages: [{id, sender, content, created_at}]}`.

### POST /api/chat/send

Persists the recruiter turn, generates Barkley's reply and persists it too.
Request body: `{session_id, message, hr_name?, hr_email?, company_name?}`.
Response: `{session_id, reply, barkley_state, interview_requested}` — `barkley_state` drives the mascot clip (e.g. `speaking`, `celebrating`, `searching`).

---

## Developer Guide

### Project layout

```
barkai/                  # project settings + root URLconf (Ninja API mounted at /api/)
chat/                    # the chat application
├── api/                 # Django Ninja package (schemas.py + router.py)
├── models.py            # ChatSession + ChatMessage
├── services.py          # mock agent replies (seam for the Groq/RAG pipeline)
├── templates/chat/      # app-scoped templates (index.html)
└── urls.py              # chat owns its URLconf
templates/               # project-level templates (base.html, 403/404/500, includes/toasts)
static/mascot/           # Barkley reaction MP4s (idle, searching, speaking, …)
.env                     # local env vars (gitignored) — load with `set -a; source .env; set +a`
```

### Conventions

- **Environment-driven settings** — read via `os.getenv()`; python-dotenv is intentionally not used. Export variables before running: `set -a; source .env; set +a`.
- **Apps own their pieces** — `chat/` ships its own `urls.py`, views, templates and API package; project-level `templates/` only covers the shared shell (`base.html`), the error pages and the toast includes.
- **Service seam** — `chat/services.py` is the plug-in point for the real Groq/RAG agent and returns deterministic mock replies today.
- **Contractual media names** — the UI switches the mascot `<video>` to `/static/mascot/<state>.mp4`, so the clip filenames must not change (details in `static/mascot/README.md`).

### Useful commands

```bash
python manage.py check          # sanity check
python manage.py migrate        # apply migrations
python manage.py runserver      # dev server
python manage.py test           # run the test suite
```

---

## Testing

```bash
python manage.py test
```

The suite (`chat/tests.py`) covers: the index view rendering `chat/index.html`; the history endpoint creating a session on first contact and returning persisted messages; `send` persisting both turns; the interview intent flagging the session and switching Barkley to `celebrating`; the `403`/`404`/`500` error pages rendering.

---

## Deployment

> Hosting and CI/CD are to be defined. The production checklist currently supported by the codebase:

* Export `DEBUG=False` and set a strong `SECRET_KEY`.
* Configure the database via `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (PostgreSQL is the default engine when `DEBUG=False`).
* Pin `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
* Run `python manage.py collectstatic --noinput` and serve `staticfiles/`.
* Replace the Tailwind CDN `<script>` with a compiled Tailwind CLI stylesheet.
* Set `GROQ_API_KEY` once the real Groq (Qwen 2.5) + RAG pipeline is wired in.

---

## Security

* Secrets live in environment variables only (`.env` is gitignored and not parsed at runtime — no python-dotenv).
* JSON `POST`s are CSRF-protected: the UI sends the `X-CSRFToken` header together with the session cookie.
* `DEBUG` must be `False` in production and a strong `SECRET_KEY` exported.
* CORS trusts all origins only while `DEBUG=True` and `CORS_ALLOWED_ORIGINS` is empty; production must pin the allowed origins.

> To be populated: HTTPS, secrets manager and further production hardening notes.

---

## SEO

> To be populated: `sitemap.xml`, `robots.txt`, Open Graph / Twitter Card metadata. A base `<meta name="description">` and `<meta name="keywords">` are already emitted by `templates/base.html`.

---

## Integrations

> To be populated: external services. The planned integrations (Groq Qwen 2.5 + RAG, email/push notifications, Flutter mobile app) are tracked in the Roadmap above.

---

## Troubleshooting

> To be populated: common issues and their fixes.

---

## Credits

> To be populated. The current Barkley reaction MP4s are small generated placeholder clips (see `static/mascot/README.md`) and the favicon is an inline dog-emoji SVG — both will be credited or replaced when real assets land.

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
