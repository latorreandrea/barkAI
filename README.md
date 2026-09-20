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
- [Agent Quality (v0.4)](#agent-quality-v04)
  - [Evaluation suite (golden set)](#evaluation-suite-golden-set)
  - [Cited sources](#cited-sources)
  - [Knowledge freshness](#knowledge-freshness)
- [Production Readiness (v0.4)](#production-readiness-v04)
  - [Security flags and HTTPS](#security-flags-and-https)
  - [Health check](#health-check)
  - [Runtime: gunicorn + WhiteNoise](#runtime-gunicorn--whitenoise)
  - [Continuous integration](#continuous-integration)
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
  - [Container image](#container-image)
  - [Deploying to Cloud Run (Console)](#deploying-to-cloud-run-console)
  - [Deploying from GitHub (Cloud Build)](#deploying-from-github-cloud-build)
  - [Scheduled jobs](#scheduled-jobs)
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
blend straight into the white page (no border, no circle) and are H.264 + yuv420p at 24 fps. They are
the **vertical take at 472x720** (the shape the player crops to with `object-cover` inside a `472:720`
box), re-encoded from 1280x720 exports that pillarboxed it in black — geometry, numbers and the export
recipe live in `static/mascot/README.md`.

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
8. **BarklAI reaction clips** — `idle`, `sniffing`, `searching`, `typing`, `speaking` and `celebrating` MP4s under `static/mascot/` drive the mascot animation: the vertical 472x720 take, cropped in a `472:720` box (`object-cover`), with an emoji fallback when a clip is missing — see [the mascot notes](#how-the-animations-were-made).
9. **Custom error pages** — project-level `403`, `404` and `500` templates.
10. **Environment-driven settings** — values read from the environment only (python-dotenv is intentionally not used); blank values fall back to safe defaults, and `DEBUG` defaults to `True` for a frictionless local start.
11. **Automated tests** — index view, chat REST API, the agent service (Groq mocked, no network), the knowledge sync + indexing commands, the i18n switching, the interview hand-off + notifications, the guardrails, the citation plumbing, the golden-set evaluator, the scheduled-jobs chain and the GDPR surface (**101 tests**; the pgvector round-trip runs only on PostgreSQL).
12. **Retrieval-augmented answers (RAG)** — the knowledge base is chunked and embedded (`KnowledgeChunk` + **pgvector**). With `RAG_ENABLED=True` only the most relevant chunks (native `<=>` cosine distance on PostgreSQL) are sent to the model; the curated **career profile is always injected verbatim** and kept out of the similarity search (see below), so it cannot crowd the project chunks out of the prompt. Without RAG the whole corpus is stuffed into the prompt as a fallback.
13. **Bilingual UI and agent (EN/DA)** — Django i18n (`{% trans %}` + `JavaScriptCatalog`) with `Accept-Language` detection and a navbar toggle; the agent answers in the recruiter's language, enforced by a detect-and-retry **language guard** (see [Language parity](#language-parity-en-and-da)).
14. **GDPR-ready** — a plain-language privacy notice (EN/DA), one-click **erasure** of the conversation (`POST /session/delete/`), a retention job (`purge_old_sessions`) and the full processing register inline in [Privacy & GDPR](#privacy--gdpr).
15. **Durable interview records** — `InterviewRequest` models a request as an *event* (name, email, company, triggering message, language, `created_at`, `notified_at`), so a recruiter who corrects their address produces a second record instead of overwriting history. Rows cascade with the session, so erasure and retention remove them too.
16. **Interview notification email** — `chat/notifications.py` emails Andrea the recruiter's details (SMTP through `EMAIL_BACKEND`) and stamps `notified_at`. The send is **idempotent**, never raises into the request cycle, and `retry_interview_notifications` recovers whatever is still pending.
17. **Public-endpoint guardrails** — a message length cap plus fixed-window rate limiting per session and per IP (`chat/throttle.py`), so a public LLM endpoint cannot be trivially drained.
18. **SMTP self-check** — `python manage.py send_test_email` proves the mail configuration (e.g. a Gmail app password) before you trust the notifications.
19. **Golden-set evaluation** — a curated, versioned set of recruiter questions (EN + DA) is scored against the live agent by `python manage.py eval_agent`, which exits non-zero when a case fails (see [Evaluation suite](#evaluation-suite-golden-set)).
20. **Cited sources** — answers name the project READMEs they rely on (`SOURCES_RULES` + server-side validation), the citations are stored on the message and rendered as chips under the reply (see [Cited sources](#cited-sources)).
21. **Knowledge freshness** — `python manage.py knowledge_status` reports coverage and staleness (and can fail a scheduled job), so a README change cannot silently fail to reach the agent.
22. **Model fallback** — if the primary Groq model fails (a decommissioned *preview* model, a 400/404), the same request is retried once on `GROQ_MODEL_FALLBACK` (a production model) before giving up.
23. **Production security by default** — with `DEBUG=False` the app enforces HTTPS (`SECURE_SSL_REDIRECT`, HSTS, secure session/CSRF cookies) from environment-driven flags, and `python manage.py check --deploy` is clean (see [Production Readiness](#production-readiness-v04)).
24. **Deployable runtime** — a multi-stage **Docker image** (see [Container image](#container-image)) runs `gunicorn` + **WhiteNoise**, so a single container serves the app *and* the static files; `/healthz` is the platform probe, GitHub Actions runs the tests plus `check --deploy` on every push, and the same image backs the scheduled Cloud Run job.

### Roadmap

- **Deferred to after the first deploy** (agreed scope, tracked here so it is not lost):
  - **Stream** the model's tokens into the speech bubble (SSE) instead of waiting for the full reply.
  - Send the recruiter a **confirmation email** (and optionally a booking link) so the interview loop closes on both sides.
  - A `Makefile` for the long local commands (the **Dockerfile** landed in v0.4).
  - **SEO**: `sitemap.xml`, `robots.txt`, Open Graph / Twitter-card metadata and a real OG image.
- **Latency**: answers were measured between ~2 s and ~38 s (mean ~25 s) with the current *preview* reasoning model. Switch to a faster **production** model and/or lower `GROQ_MAX_TOKENS`; SSE then hides what remains.
- Add **push** (browser/Slack) notifications next to the email, and move the send to a background task queue so no interview turn ever waits on SMTP.
- Add an **HNSW index** on `KnowledgeChunk.embedding` once the corpus grows.
- `eval_agent --repeat N`: the persona is creative at `temperature=0.5`, so a wording-sensitive case can flake; repeating a case would make the score steadier.
- Re-export the six mascot clips at the content ratio (472x720) instead of the pillarboxed 1280x720
  files: the black bars are ~2.2x the pixels the player showed, i.e. most of the 7.5 MB the mascot set
  weighed. **Done** — the set is now 3.9 MB (`crop=472:720:404:0`, `-tune animation`, `-an`, crf 28;
  recipe in `static/mascot/README.md`), see B-008.
- Serve production static files via `collectstatic` + WhiteNoise/CDN (the frontend is already compiled and minified).
- Fine-tune the persona prompt and add more per-state reactions.

---

## Agent Hardening (v0.4)

> The v0.3 agent was tested live (real Groq + Neon + Cloudflare) instead of only through mocks. That
> probe exposed two real defects that made the Danish market and the interview hand-off unreliable —
> and one diagnosis of mine that turned out to be wrong. This section documents each one, how it was
> found and how it is fixed; all of it is tracked in the [Bug Log](#bug-log).

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

The persona's original "never invent facts" was too soft, so it became an explicit `GROUNDING_RULES`
block:

* mention only skills, services, employers and numbers that appear in the ground truth;
* never add a plausible-sounding extra — say what is missing and offer the closest fact that *is* there;
* never quote or allude to personal identifiers.

The rules were added after a *misdiagnosis* worth recording: I first flagged the agent for naming
**Firestore, Cloud Build and Secret Manager**, having grepped only the local files — but those services
are real project technology from the `aura-visual` and `django-cloud-ecommerce` READMEs, i.e. inside
the knowledge base. The withdrawal is tracked as B-003 in the [Bug Log](#bug-log), and it is why the
[evaluation suite](#evaluation-suite-golden-set) now insists that a `must_not_contain` term be verified
**absent from the corpus** before it is trusted.

The one real leak the rules did fix was the **CPR reference** (B-004): the curated profile itself
claimed "resident with CPR" while instructing the agent never to share identifiers. Fixing the prompt
was not enough — the ground truth had to stop volunteering it, so the profile now states only that
Andrea is eligible to work in Denmark, and three golden-set cases assert that `cpr` never appears.

The honest-answer behaviour is regression-tested: *"Does Andrea have experience with Kubernetes,
Terraform and Rust?"* gets a clear, grounded **no**.

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

### Model fallback

The primary model is a Groq **preview** model (`qwen/qwen3.8-27b` at the time of writing), and Groq explicitly
warns that preview models "may be discontinued at short notice". A deprecation would have turned every answer into
"I lost the scent of my Groq brain", so `generate_reply()` now walks a short model list:

```
GROQ_MODEL (preview)  ──fails──▶  GROQ_MODEL_FALLBACK (production: llama-3.3-70b-versatile)  ──▶ friendly copy
        │
        └── succeeds ▶ answer
```

* Exactly **one** retry, and never on the same model twice (setting both variables to the same value disables it).
* A `json_validate_failed` refusal is *not* retried on the fallback: the prose is salvaged instead, because the
  answer itself is fine (see B-005 in the [Bug Log](#bug-log)).
* The language guard still runs per attempt, so a fallback model gets the same correction chance.

---

## Agent Quality (v0.4)

> The hardening above stopped the agent being *wrong*. This section is about knowing whether it is
> *still right*: a scored evaluation set, citations the recruiter can sanity-check, and a freshness
> report for the corpus it answers from. It exists because two of my own earlier diagnoses turned out
> to be wrong (see the [Bug Log](#bug-log)) — a handful of manual probes is not evidence.

### Evaluation suite (golden set)

`chat/evals/golden_set.json` is a curated, versioned set of **19 recruiter questions (10 English,
9 Danish)** carrying the facts each answer must contain, the claims it must never make, the expected
language and the expected interview flag.

```bash
python manage.py eval_agent --check-only   # validate the file: no model, no API key
python manage.py eval_agent                # score a live run (needs GROQ_API_KEY)
python manage.py eval_agent --only da-     # subset by id prefix
python manage.py eval_agent --verbose      # print every reply next to its result
```

The command prints PASS/FAIL per case with the reason and a final score, then **exits non-zero when
anything failed** — so it can gate a release the way the test suite gates a commit. Expectation
fields (matching is case-insensitive):

| Field | Meaning |
| --- | --- |
| `must_contain` | every string must appear |
| `must_contain_any` | at least one alternative must appear |
| `must_not_contain` | none may appear — for claims that must never be made (personal identifiers, invented technologies, off-topic content) |
| `language` | the reply must be detected in this language |
| `interview_requested` | the structured flag must match |

The first scored run came out at **14/19**, and the failures were worth more than the score: three
were real (the agent echoed a CPR reference the profile should never have contained) and two were
**my expectations being wrong**. A `must_not_contain` term must be genuinely **absent from the
corpus**, not merely suspicious — `firestore`, `cloud build` and `secret manager` are real project
technology (from the `aura-visual` and `django-cloud-ecommerce` READMEs), so asserting their absence
flagged a correct answer as a bug. After that cleanup the same set scored **18/19**, the last case
being a wording-sensitive refusal that the suite now asserts by *property* (stays on topic, never
produces the poem) instead of by exact phrase.

### Cited sources

Every answer can name the project READMEs it leaned on, and the recruiter sees them as small chips
under the reply — in the history too, because `ChatMessage.sources` is persisted:

```
retrieval ──▶ CITABLE SOURCES block ──▶ model proposes ["repo/a", "repo/x"]
                                                  │
                                                  ▼
                          _sanitize_sources() keeps only the labels retrieval
                          actually returned ──▶ message row + API response
```

* `SOURCES_RULES` asks for the exact labels and forbids inventing one; the allowed list is injected
  as a `CITABLE SOURCES` block (or an explicit "none available", so the model returns `[]`).
* **The server decides**: `chat/services.py:_sanitize_sources()` drops any label retrieval did not
  return, so a fabricated citation can never reach a recruiter — the same *model proposes, server
  decides* idea as the language guard.
* The prompt section and the labels come from **one** call to
  `build_retrieved_context_with_sources()`: a second `retrieve()` would double the embedding cost
  and the latency.
* With `RAG_ENABLED=False` no per-chunk retrieval happens, so there are no citable labels and the
  chips stay empty.
* The citation label is translated (`Sources` / `Kilder`) and passed to `chat.js` through a
  `data-label` attribute, so it lives in the Django catalogue like every other string.

### Knowledge freshness

BarklAI is only as good as the corpus behind him, and a README that changes on GitHub reaches him
**only** when `sync_knowledge` + `build_index` run:

```bash
python manage.py knowledge_status                  # human-readable report
python manage.py knowledge_status --days 7         # tighter window
python manage.py knowledge_status --fail-on-stale  # exit 1, so a cron job can alert
```

Real output on the current corpus:

```
Documents: 22
  Career profile: 1
  GitHub README: 21
Chunks:    204 (204 embedded, 100%)
Fetched:   newest 2026-09-14, oldest 2026-09-12 (stale after 30 day(s))
Fresh: nothing to do.
```

It also flags chunks that exist **without an embedding** (i.e. `build_index` never finished), which
is the state that silently degrades retrieval to the Python cosine fallback. `KNOWLEDGE_STALE_DAYS`
(default `30`) sets the window.

---

## Production Readiness (v0.4)

> Everything below was verified locally: `check --deploy` is clean with `DEBUG=False`, `/healthz` and the static
> files answer `200` under `gunicorn`, and CI runs both on every push.

### Security flags and HTTPS

With `DEBUG=False` the app enforces HTTPS on its own. Every flag is environment-driven, so nothing is hard-coded
and local development stays plain HTTP on localhost:

| Setting | Default when `DEBUG=False` | Env variable |
| --- | --- | --- |
| `SECURE_SSL_REDIRECT` | `True` | `SECURE_SSL_REDIRECT` |
| `SESSION_COOKIE_SECURE` · `CSRF_COOKIE_SECURE` | `True` | same names |
| `SECURE_HSTS_SECONDS` | `31536000` (one year) | `SECURE_HSTS_SECONDS` |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` · `SECURE_HSTS_PRELOAD` | `True` | same names |
| `SECURE_REFERRER_POLICY` | `same-origin` | `SECURE_REFERRER_POLICY` |
| `SECURE_PROXY_SSL_HEADER` | *unset* | `TRUST_PROXY_SSL_HEADER=True` |
| `CSRF_TRUSTED_ORIGINS` | *empty* | `CSRF_TRUSTED_ORIGINS` (comma-separated) |

Two details matter on a managed platform:

* **Cloud Run / Heroku / Fly terminate TLS** and forward the scheme, so set `TRUST_PROXY_SSL_HEADER=True`. Without
  it Django never sees HTTPS and an unconditional `SECURE_SSL_REDIRECT` turns into a redirect loop.
* `SECURE_HSTS_PRELOAD` only adds the directive to the header — a domain is preloaded only if you submit it at
  [hstspreload.org](https://hstspreload.org) — so enabling it is harmless; set it to `False` to opt out.

The gate is one command:

```bash
DEBUG=False SECRET_KEY=… ALLOWED_HOSTS=… DATABASE_URL=… python manage.py check --deploy
# System check identified no issues (0 silenced).
```

### Health check

`GET /healthz` (no trailing slash, so no `APPEND_SLASH` redirect) is the platform probe. It is deliberately cheap
and never touches the LLM providers, so a Groq or Cloudflare outage cannot make the container look dead:

```json
{"status": "ok", "database": true, "indexed_chunks": 204}
```

It answers `503` with `{"status": "degraded", "database": false, …}` when the database is unreachable, and it
exposes no personal data — the chunk count doubles as a smoke test that the RAG index is still loaded.

### Runtime: gunicorn + WhiteNoise

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python -m gunicorn barkai.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120
```

The last line is `python -m gunicorn`, not the bare `gunicorn` command. That is not a style choice: the
production image installs its dependencies with `pip install --target`, so no console script ever lands on
the runtime `PATH` — the bare command does not exist in the container (see
[Container image](#container-image) and B-006).

* **WhiteNoise** serves the collected files from the app process, so a single Cloud Run service is enough (no
  bucket or CDN required). It sits directly after `SecurityMiddleware`.
* The storage backend is `whitenoise.storage.CompressedStaticFilesStorage` — deliberately **not** the *Manifest*
  variant: without a manifest `{% static %}` keeps resolving before `collectstatic` has ever run, which keeps local
  development and the test suite working.
* `--timeout 120` matters: a reasoning-model answer can take tens of seconds (see the [Roadmap](#roadmap)).

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request, with **no secrets** required:

| Job | What it does |
| --- | --- |
| `test` | installs requirements, compiles the `.mo` catalogues, validates the golden set offline (`eval_agent --check-only`), runs the **101 tests** on SQLite, then `check --deploy` with `DEBUG=False` and a dummy `DATABASE_URL` |
| `static` | `npm ci` + `npm run css:build` + `git diff --exit-code static/css/barkai.css`, so a new Tailwind class can never be missing from the committed stylesheet |

> The live evaluation (`eval_agent`) is **not** in CI on purpose: it costs real Groq calls and takes ~10 minutes.
> Run it before a release or from a scheduled job.

---

## Architecture

### System Overview

The repository is a Django project with a thin surface: `barkai/` holds the settings and the root URLconf, where a single Django Ninja `NinjaAPI` instance is mounted at `/api/` and the chat app is mounted at `/`. All chat logic lives in the `chat/` app: models, API package, service layer, templates and URLconf.

### Technology Stack

- **Backend:** Django 5.2 · Django Ninja 1.7 · django-cors-headers · Pydantic 2
- **Language:** Python 3.11+
- **Database:** PostgreSQL + **pgvector** via a single `DATABASE_URL` (Neon in dev and prod) — the only supported database configuration. With `DEBUG=True` and no URL the app falls back to zero-config SQLite (handy for a quick look, but no vector search); with `DEBUG=False` it refuses to boot rather than guessing credentials.
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
| `GROQ_MODEL_FALLBACK` | Model retried once when the primary one fails (default `llama-3.3-70b-versatile`, a production model). Set it equal to `GROQ_MODEL` to disable. | Groq console → *Models* |
| `GITHUB_USERNAME` | GitHub user whose repositories' READMEs are ingested. | `github.com/<username>` |
| `GITHUB_EXTRA_REPOS` | Extra repos under **other** accounts: comma-separated `owner/repo` (a full GitHub URL works too). | those repos' URLs |
| `GITHUB_TOKEN` | *(optional locally, **recommended on the maintenance job**)* PAT for private repos and for GitHub's authenticated limit of 5000 requests/hour instead of 60 anonymous ones. | GitHub → *Settings → Developer settings → Personal access tokens* |
| `GITHUB_EXCLUDE_REPOS` | Repos to keep **out** of the knowledge base (template/boilerplate READMEs, abandoned projects): comma-separated `owner/repo`, a full GitHub URL, or just the bare repo name. | your choice |
| `GITHUB_INCLUDE_FORKS` | Ingest forks too (default `false`). | your choice |
| `GITHUB_API_TIMEOUT_SECONDS` | GitHub API timeout (default `15`). | your choice |
| `GITHUB_README_MAX_CHARS` | Max characters stored per README (default `14000`). | your choice |
| `DATABASE_URL` | PostgreSQL connection string (Neon/Supabase) — **the only supported database configuration**. Required for pgvector; with `DEBUG=True` a missing URL falls back to SQLite, with `DEBUG=False` the app raises `ImproperlyConfigured` instead of starting. | your database provider |
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
| `KNOWLEDGE_STALE_DAYS` | Age at which `knowledge_status --fail-on-stale` starts complaining (default `30`). | your choice |
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
| `SECURE_SSL_REDIRECT` · `SESSION_COOKIE_SECURE` · `CSRF_COOKIE_SECURE` | HTTPS and cookie hardening. Default: **on** when `DEBUG=False`. | your choice |
| `SECURE_HSTS_SECONDS` · `SECURE_HSTS_INCLUDE_SUBDOMAINS` · `SECURE_HSTS_PRELOAD` | HSTS headers (default when `DEBUG=False`: one year, subdomains, preload directive). | your choice |
| `SECURE_REFERRER_POLICY` | `Referrer-Policy` header (default `same-origin`). | your choice |
| `TRUST_PROXY_SSL_HEADER` | Trust `X-Forwarded-Proto` — **required behind Cloud Run/Heroku TLS termination** (default `false`). | your choice |
| `CSRF_TRUSTED_ORIGINS` | Extra origins allowed to POST, comma-separated (e.g. `https://barkai.example.com`). | your deployment URL |
| `WHITENOISE_MAX_AGE` | Cache lifetime for the WhiteNoise-served static files (default `31536000`). | your choice |
| `ASSET_VERSION` | Cache-buster appended as `?v=` to every static asset (CSS, JS, mascot clips). Derived from the assets' mtimes by default, so a deploy that rebuilds them gets a fresh token on its own; export it only to pin one (e.g. the commit SHA). Without it the one-year cache would hide the change. | your choice |

> For the full experience set `GROQ_API_KEY`, `DATABASE_URL` (PostgreSQL + pgvector),
> `EMBEDDING_PROVIDER=cloudflare` with `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`,
> `RAG_ENABLED=True` and `GITHUB_USERNAME`. Everything else has a sensible default, and blank
> values never break the app.

> The compiled `static/css/barkai.css` is committed, so a fresh clone runs without Node.js. Only run the build below when you add/change Tailwind classes or the site-wide custom CSS.

> `DEBUG` defaults to `True` when unset. For production always export `DEBUG=False`, a strong `SECRET_KEY` and `DATABASE_URL` (the only supported database configuration — the app refuses to boot without it when `DEBUG=False`).

---

## Usage

Open the chat at <http://127.0.0.1:8000/> and ask BarklAI about Andrea's projects or tech stack — or write that you would like to schedule an interview: BarklAI flags the opportunity and celebrates. The conversation survives page reloads; share the URL with its `?session_id=` to continue the same session elsewhere.

Useful URLs:

* Web UI (chat with BarklAI): <http://127.0.0.1:8000/>
* Privacy notice: <http://127.0.0.1:8000/privacy/>
* Swagger/OpenAPI docs: <http://127.0.0.1:8000/api/docs>
* Health probe: <http://127.0.0.1:8000/healthz>
* Django admin: <http://127.0.0.1:8000/admin/>

---

## API Reference

Interactive docs are served by Django Ninja at `/api/docs` (raw OpenAPI schema at `/api/openapi.json`).

### GET /api/chat/history/{session_id}

Returns the persisted conversation for the session, creating it if it does not exist yet.
Response: `{session_id, interview_requested, messages: [{id, sender, content, sources, created_at}]}` — `sources` are the citations stored with each BarklAI reply (always `[]` on a recruiter turn).

### POST /api/chat/send

Persists the recruiter turn, generates BarklAI's reply and persists it too.
Request body: `{session_id, message, hr_name?, hr_email?, company_name?}`.
Response: `{session_id, reply, barkley_state, interview_requested, suggest_questions, sources}` — `barkley_state` drives the mascot clip (e.g. `speaking`, `celebrating`, `searching`) and `suggest_questions` tells the UI to offer the quick-question chips. `sources` lists the knowledge-base labels the reply is grounded in, already validated against the retrieved chunks (see [Cited sources](#cited-sources)), and is persisted with the assistant message. Validation: `message` is capped at 2000 characters (`422` when exceeded) and the endpoint is rate-limited (`429`) per session and per IP. When `interview_requested` is true the session also gets an `InterviewRequest` row, and the notification goes out immediately if the payload already carried an email.

### POST /api/chat/contact

Stores the recruiter's details for an interview request — this is the hand-off form the UI reveals. It does **not** call the LLM, so leaving the details is free.
Request body: `{session_id, hr_email (required), hr_name?, company_name?}`.
Response: `{session_id, saved, notified}` — `notified` is `false` when `INTERVIEW_NOTIFY_EMAIL` is blank or the SMTP send failed (the details are stored either way). An invalid email is a `422`; the endpoint is rate-limited like `/send`.

### POST /session/delete/

Erases the requester's conversation (**GDPR** right to erasure). Body: `{session_id}`; returns
`{deleted: true}` (or `400` for a malformed id). CSRF-protected like the chat API.

### GET /privacy/

Renders the privacy notice (English or Danish, following the active language).

### GET /healthz

Liveness/readiness probe (no trailing slash, so no redirect). Returns `{status, database, indexed_chunks}` with
`200`, or `503` with `"status": "degraded"` when the database is unreachable. It never calls the LLM providers and
exposes no personal data — see [Health check](#health-check).

### Language endpoints

* `POST /i18n/setlang/` — Django's `set_language` view, used by the navbar EN/DA toggle.
* `GET /jsi18n/` — the JavaScript message catalogue (`djangojs` domain) consumed by `chat.js`.

---

## Developer Guide

### Project layout

```
barkai/                  # settings + root URLconf (Ninja API at /api/) + views.py (the /healthz probe)
chat/                    # the chat application
├── api/                 # Django Ninja package (schemas.py + router.py)
├── management/commands/ # sync_knowledge · build_index · knowledge_status · purge_old_sessions · eval_agent · run_scheduled_jobs · send_test_email · retry_interview_notifications
├── knowledge/           # andrea_profile.md (curated career profile, versioned)
├── embeddings.py        # pluggable embedding providers (Cloudflare Workers AI)
├── rag.py               # retrieval: pgvector search / Python cosine fallback
├── models.py            # ChatSession + ChatMessage + KnowledgeDocument + KnowledgeChunk + InterviewRequest
├── prompts.py           # BarklAI persona + language/grounding/sources rules + JSON contract
├── services.py          # the agent: Groq call, language guard, citation validation, salvaging
├── interviews.py        # InterviewRequest capture rules (one event per contact capture)
├── notifications.py     # interview email: idempotent, never raises, stamps notified_at
├── throttle.py          # fixed-window rate limiting for the public chat endpoints
├── evals/               # golden_set.json (EN/DA cases) + the evaluator (stdlib only)
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
.github/workflows/       # ci.yml — tests + check --deploy + the compiled-CSS guard
cloudbuild.yaml          # GitHub trigger: tests → build → deploy service + jobs
Dockerfile               # multi-stage production image (web service + scheduled job)
.dockerignore            # build context: keeps .env, .venv, node_modules and staticfiles out
```

### Conventions

- **Environment-driven settings** — read via `os.getenv()`; python-dotenv is intentionally not used. Export variables before running: `set -a; source .env; set +a`.
- **One database configuration** — a single `DATABASE_URL` (there is no `DB_*` fallback). SQLite is only a `DEBUG` convenience for a quick look: it has no pgvector, so retrieval drops to the Python cosine scan and an empty `db.sqlite3` looks like a broken index. With `DEBUG=False` a missing URL raises `ImproperlyConfigured` at boot instead of connecting with guessed credentials.
- **Apps own their pieces** — `chat/` ships its own `urls.py`, views, templates and API package; project-level `templates/` only covers the shared shell (`base.html`), the error pages and the toast includes.
- **Service seam** — `chat/services.py` owns the agent: it calls Groq (JSON mode) when `GROQ_API_KEY` is set and otherwise returns consistent, in-character fallbacks. The persona + output contract live in `chat/prompts.py`, and the facts come from `KnowledgeDocument`.
- **Structured output** — the model is asked for `{reply, interview_requested, suggest_questions, sources}`; parsing is tolerant, and a **prose answer that JSON mode refuses** (`json_validate_failed`) is salvaged rather than dropped (see [Agent Quality](#agent-quality-v04)).
- **Evaluation is data, not code** — the golden set lives in `chat/evals/golden_set.json` and the matching logic in `chat/evals/__init__.py` (stdlib only). Extend the JSON whenever a new promise is made to the agent, and keep every `must_not_contain` term genuinely **absent from the corpus**.
- **Citations are validated server-side** — the model may only name labels retrieval returned (`_sanitize_sources`); never trust a generated label, and never let it reach a recruiter unvalidated.
- **Freshness is a job** — `knowledge_status --fail-on-stale` is what makes the corpus's age visible; schedule it next to `sync_knowledge`/`build_index`.
- **Contractual media names** — the UI switches the mascot `<video>` to `/static/mascot/<state>.mp4`, so the clip filenames must not change (details in `static/mascot/README.md`). The clips are the vertical take at 472x720 and the player keeps a `472:720` box with `object-cover`; the ratio is measured, not guessed (see B-008).
- **Cache-bust the assets, they are cached for a year** — WhiteNoise serves `static/` with `max-age=31536000` and the non-Manifest storage keeps every URL stable, so a plain CSS/JS/clip change would reach nobody who had already visited. Every static URL therefore carries `?v={{ ASSET_VERSION }}` (`barkai.context_processors.asset_version`), a token derived from the assets themselves (`_asset_version_default` in `barkai/settings.py`), so a rebuild moves it automatically and a deploy that changes nothing keeps the cache warm. Export `ASSET_VERSION` only to pin it by hand.
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
python manage.py knowledge_status   # report coverage/freshness of the knowledge base
python manage.py eval_agent --check-only  # validate the golden set (no model call)
python manage.py eval_agent         # score the live agent against the golden set
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

The suite (`chat/tests.py`, **101 tests**) covers: the index view; the history endpoint; `send` persisting both turns; the interview flag; the agent service with the **Groq client mocked** (JSON parsing, friendly fallbacks, the bilingual offline heuristics, the **language guard** — retry once, keep the first answer if the retry also fails, skip the retry when the languages match, honour `AGENT_LANGUAGE_GUARD=False` — and the **JSON-mode salvage** of a refused prose answer); `detect_language()` itself; the citation plumbing (a fabricated label is dropped, the API returns and persists `sources`, user turns carry none); the golden-set evaluator (file shape, both languages, PASS/FAIL reasons); retrieval (profile always injected, profile never searched, per-source diversity cap); the interview hand-off (capture rules including the corrected-email case, the `/api/chat/contact` endpoint, the notification email in a locmem outbox, "never notified twice", details stored even with notifications disabled, cascade on erasure); the guardrails (2000-character cap → `422`, throttle → `429`, `0` disables it); the knowledge commands (`sync_knowledge` incl. the `GITHUB_EXCLUDE_REPOS` filter and `--prune`, `build_index` chunking + hash idempotency, `knowledge_status` coverage/staleness/exit codes, `purge_old_sessions`); the i18n switching (browser detection, session toggle, JS catalogue); the scheduled-jobs chain (step order, failure aggregation, the `SystemExit` case, warning markers, `--no-prune`, `--dry-run`); the GDPR surface (privacy notice, erasure endpoint); and the `403`/`404`/`500` pages.

### Evaluation (live, on demand)

The unit tests prove the plumbing with the model mocked; the **golden set** proves the agent still tells the truth. It costs real Groq calls, so it is opt-in:

```bash
python manage.py eval_agent --check-only   # CI-safe: validates the file only
python manage.py eval_agent                # live score; non-zero exit on failure
python manage.py eval_agent --only da-     # fast subset while iterating
```

> Do not run the full live set while iterating on the prompt: 19 cases take ~8-10 minutes because every answer goes through a reasoning model (~25 s each). `--only <prefix>` is the fast loop; the full run is a release gate. See [Agent Quality](#agent-quality-v04).

> The i18n tests assert Danish copy, so run `python scripts/compile_messages.py` first — `*.mo` is gitignored and therefore absent from a fresh clone.

Tests run against **SQLite** by default — fast, offline, no database server needed. The single **pgvector** round-trip test is skipped there and runs on PostgreSQL:

```bash
set -a; source .env; set +a
python manage.py test chat.tests.RagVectorTests --keepdb   # runs against Neon
```

> `--keepdb` keeps the test database around: Neon's connection pooler otherwise blocks the drop at teardown.

---

## Deployment

> CI runs in GitHub Actions on every push (see [Continuous integration](#continuous-integration)); what follows is the production checklist the codebase supports.

* Export `DEBUG=False` and a strong `SECRET_KEY`.
* Point `DATABASE_URL` at a **PostgreSQL + pgvector** instance (Neon/Supabase free tiers work); `migrate` creates the `vector` extension automatically. It is mandatory: with `DEBUG=False` the app refuses to boot without it.
* Export `GROQ_API_KEY`, `EMBEDDING_PROVIDER=cloudflare` with `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`, `RAG_ENABLED=True`, `GITHUB_USERNAME` (and `GITHUB_TOKEN` for private repos).
* Pin `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
* Run `python manage.py migrate`, `python manage.py collectstatic --noinput`, then serve with **gunicorn**: WhiteNoise is already in `MIDDLEWARE`, so the same container serves the app and the static files (see [Runtime](#runtime-gunicorn--whitenoise)). Point the platform's health probe at `/healthz`.
* Refresh the knowledge base on deploy or on a schedule: `python manage.py sync_knowledge && python manage.py build_index`.
* Compile the translations on deploy: `python scripts/compile_messages.py` (`*.mo` is gitignored, so a fresh checkout has none).
* Export the SMTP variables plus `INTERVIEW_NOTIFY_EMAIL` and `SITE_BASE_URL`, then verify with `python manage.py send_test_email` before relying on the notifications.
* Schedule `python manage.py purge_old_sessions` so the retention promised in the privacy notice is real.
* No local ML model ships — embeddings are an HTTP call. The image comes from the repo's `Dockerfile` and is realistically **~60-75 MB compressed** (what Artifact Registry stores and Cloud Run pulls), see [Container image](#container-image).

#### Container image

```dockerfile
FROM python:3.11-slim AS builder   # pip install --target=/install
FROM python:3.11-slim AS runtime   # copy /install, drop pip/setuptools, copy the app,
                                   # then run the build-time steps: a smoke test, then
                                   # compile_messages + collectstatic
CMD python -m gunicorn barkai.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120
```

Four decisions worth knowing:

* **A build-time smoke test, not hope**: before the slow steps, the image must prove it can *start* —
  `python -m gunicorn --check-config barkai.wsgi:application` (which parses the gunicorn flags *and*
  imports the app) plus an import of `barkai.wsgi`. Either would have caught B-006, where the image built
  and pushed perfectly and then died at startup because the `CMD` called a `gunicorn` executable the
  runtime stage never received (`pip install --target` puts console scripts off `PATH`); `--check-config`
  also catches a *flag* typo that a plain `--version` would let through. A container that cannot start is
  now a failed **build**, one click from its log, instead of a Cloud Run mystery about a port.
* **No `--no-compile`**: the `.pyc` files cost a few MB but avoid compiling ~100 packages on the first
  request. Cloud Run bills startup time, so paying in MB beats paying in seconds.
* **`DEBUG` is scoped to a single `RUN`**, never an `ENV`: as an `ENV` it would be baked into the image,
  and a variable missing on Cloud Run would silently start the app in debug mode.
* **`.dockerignore` excludes `.env`** (plus `.venv`, `node_modules`, `staticfiles`). It deliberately
  does **not** exclude `*.md` as a whole: `chat/knowledge/andrea_profile.md` is markdown that the
  scheduled job really reads, so documentation is excluded by exact path (`/README.md`, `/LICENSE`).

The same image runs both workloads: the service (default `CMD`) and the maintenance job (command
overridden in Cloud Run Jobs).

#### Deploying to Cloud Run (Console)

Console-first, so no secret ever passes through a shell history. Everything below uses `<PLACEHOLDERS>`;
**this file contains no secret by design**.

1. **Project** — create it, attach billing, then enable the APIs in *APIs & Services → Library*:
   Cloud Run Admin, Artifact Registry, Cloud Build, Cloud Scheduler.
2. **Image** — the build produces it, so first make sure the registry can receive it: *Artifact Registry →
   Create repository*, name **`barkai`**, format **Docker**, region `europe-west1` — the same `_REPOSITORY`
   and `_REGION` as `cloudbuild.yaml`, which is where the trigger pushes. The pipeline's `prepare-registry`
   step creates this repository for you and is a no-op once it exists, so doing it by hand is only needed
   when that step lacks the permission. Beware of the alternative: the *Continuously deploy from a
   repository* wizard creates a repository called `cloud-run-source-deploy`, a different name this pipeline
   never uses. Then connect the repository once with a trigger (see
   [Deploying from GitHub](#deploying-from-github-cloud-build)), and every push to `main` rebuilds and
   redeploys — nothing runs from a laptop.
3. **Service settings** — region `europe-west1` or `europe-north1`, **Allow unauthenticated** (the chat
   is public), container port `8080`, memory `512 MiB`, **request timeout 300 s** (an LLM answer can take
   tens of seconds), **max concurrent requests 4** (80 concurrent 40 s calls would drain the Groq rate
   limit), autoscaling **min 0 / max 3**, health check on **`/healthz`**.
4. **Environment variables** (*Container → Variables and secrets*, plain variables): `DEBUG=False`,
   `TRUST_PROXY_SSL_HEADER=True`, `ALLOWED_HOSTS=.run.app,<DOMAIN>`,
   `CSRF_TRUSTED_ORIGINS=https://*.run.app,https://<DOMAIN>`, `SITE_BASE_URL=https://<DOMAIN>`,
   `SECRET_KEY`, `DATABASE_URL`, the Groq and Cloudflare variables, `RAG_ENABLED`, `GITHUB_USERNAME`,
   `GITHUB_EXCLUDE_REPOS`, and the SMTP block (`EMAIL_*`, `INTERVIEW_NOTIFY_EMAIL`,
   `DEFAULT_FROM_EMAIL` — **quote it** when it carries a display name).

   > Three gotchas. `TRUST_PROXY_SSL_HEADER=True` is mandatory because Cloud Run terminates TLS (without
   > it `SECURE_SSL_REDIRECT` redirects in a loop). `CSRF_TRUSTED_ORIGINS` uses the wildcard
   > `https://*.run.app` on purpose: the real origin is `https://<SERVICE>-<PROJECT_NUMBER>.<REGION>.run.app`
   > and contains the **project number**, which you cannot know before the service exists — the wildcard
   > covers both URL formats Cloud Run hands out, so the field can be filled at creation time. And plain
   > variables are readable by anyone with the Viewer role on the project — the accepted trade-off of not
   > using Secret Manager.
5. **Verify** — `https://<SERVICE>-<PROJECT_NUMBER>.<REGION>.run.app/healthz` must answer
   `{"status":"ok","database":true,…}`, then
   try the chat in both languages and an interview request.

#### Deploying from GitHub (Cloud Build)

The build is triggered by a push to `main`; nothing is built on a laptop. What matters is which kind of
trigger you create:

| | Inline trigger (Console wizard) | **`cloudbuild.yaml`** (what this repo uses) |
| --- | --- | --- |
| Set-up | *Cloud Run → Create service → Continuously deploy from a repository* → build type **Dockerfile** | *Cloud Build → Triggers → Connect repository* (Cloud Build GitHub App) → **Cloud Build configuration file** → `cloudbuild.yaml` |
| Rebuilds the web service | ✅ | ✅ |
| **Updates the scheduled jobs** | ❌ (by hand, every deploy) | ✅ |
| Runs the tests before deploying | ❌ | ✅ |

The job step is the whole point. A Cloud Run trigger redeploys **only the service**: without it the two jobs
keep running the **previous** image, so a maintenance run would execute stale code against a newer database —
a mismatch you notice weeks later, in the logs, with no obvious cause. `cloudbuild.yaml` builds one image and
points both workloads at it.

The pipeline is five steps: **test** (the real deploy gate — a red GitHub Actions run does *not* stop this
trigger), **prepare-registry** (creates the Artifact Registry repository if it is missing), **build** (one
image, tagged with the commit and pushed *right there*), **deploy the service**, **update both jobs**. It
carries no secret by design: `gcloud run deploy` and `gcloud run jobs update` change only the image, so
everything configured in the console (environment variables, scaling, probes) is preserved.

> The push lives **inside** the `build` step, and not in an `images:` block at the end of the file. Cloud
> Build publishes those artifacts only after the whole build has succeeded, which is too late for a deploy
> step that runs *during* the build — and because that step then fails, the push never happens either, so a
> fresh tag could never be deployed. That deadlock is B-007.

Grant these once, or the deploy steps fail with `PERMISSION_DENIED`:

* the **Cloud Build service account** (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`) needs
  **Cloud Run Admin** and **Service Account User** — for the last two steps;
* **Artifact Registry Admin**, for `prepare-registry`, the only step that *creates* something. The push itself
  only needs write access, already included in the default build role. Without this role the step fails: grant
  it, or create the repository once by hand (step 2 above) and let the step report it as existing.

Trigger settings worth checking: branch `^main$`, build config `cloudbuild.yaml`, and a generous timeout —
the file sets `timeout: 1200s` because a cold build installs the dependencies, runs the suite and builds the
image.

> There is deliberately no `.gcloudignore`: with a GitHub trigger the source comes from the repository
> archive, and for the local `gcloud builds submit` fallback `.gitignore` already covers `.env`, `.venv`,
> `node_modules`, `db.sqlite3` and `staticfiles`.

On the **first run** nothing is deployed yet: `prepare-registry` creates the Artifact Registry repository, the
image is built and pushed, and the two deploy steps skip with a message instead of doing harm. That is
deliberate — a trigger that creates the service itself would produce one with **no environment variables**
(`DEBUG=True` on SQLite) and, without `--allow-unauthenticated`, unreachable. So the service and the two jobs
are created once from the console (see above), and from the next push the pipeline updates them.

| Step | First run | Later runs |
| --- | --- | --- |
| `test` | runs the suite | runs the suite |
| `prepare-registry` | creates the repository | `'barkai' already exists` |
| `build` | builds and pushes the image | same |
| `deploy-service` | `SKIP: the service 'barkai' does not exist yet` — still green | updates the revision |
| `update-jobs` | `SKIP: the job '…' does not exist yet` — still green | updates both jobs |

> `_REGION` in `cloudbuild.yaml` must match the Artifact Registry repository and the Cloud Run service:
> change that one line when deploying to another region.

**One rule to remember when editing the file**: Cloud Build applies substitutions to every value *before*
anything runs, so a literal `$` is written **`$$`** — `$$IMAGE`, never `$IMAGE`. A stray `$NAME` that is not a
built-in or a declared `_…` substitution fails the whole build with *"key in the template … is not a valid
built-in substitution"*, and that error only ever appears in Cloud Build. `scripts/check_cloudbuild.py`
reproduces the check in a second, and CI runs it first (after its own `--self-test`, so a validator that
stopped matching cannot pass the file by accident); comments are ignored, exactly as Cloud Build does.

#### Scheduled jobs

One Cloud Run Job runs the whole maintenance chain, so the scheduler has a single target to trust:

| Cadence | Job | Command | Why |
| --- | --- | --- | --- |
| Daily | `barkai-maintenance` | `python manage.py run_scheduled_jobs` | refreshes the corpus, recovers lost notifications and fails loudly when it went stale |
| Weekly | `barkai-retention` | `python manage.py purge_old_sessions --days 90` | enforces the retention window advertised in the privacy notice |

`run_scheduled_jobs` is a command rather than a shell `&&` chain on purpose: every step runs even when an
earlier one fails, each outcome is reported, **`SystemExit` is caught explicitly** (that is how
`sync_knowledge` signals a GitHub error, and it derives from `BaseException`, so a plain
`except Exception` would let the process die before printing the summary) and the job exits non-zero when
anything failed — which is what turns the Cloud Scheduler execution red.

⚠️ **A Cloud Run job does not inherit the service's environment variables.** Set them again on the job
(*Jobs → the job → Edit and deploy new revision → Container → Variables and secrets*), or the app refuses
to start without `DATABASE_URL`.

The **maintenance** job also wants its own `GITHUB_TOKEN`, and this is not cosmetic: without one the GitHub
calls are anonymous, i.e. capped at **60 requests per hour and per IP** — and Cloud Run egress IPs are shared,
so part of that budget can already be spent by other tenants. A `403` there makes `sync_knowledge` fail and
the job exit non-zero, which is what turns the Cloud Scheduler execution red. The corpus is never at risk:
`--prune` deletes only *after* a fully successful fetch, so a rate-limited run is a loud failure, not a
silent data loss.

Then create one schedule per job from **Cloud Scheduler → Create job**:

| Field | Value |
| --- | --- |
| Frequency | `0 3 * * *` (daily) · `30 3 * * 0` (weekly) |
| Timezone | `Europe/Copenhagen` |
| Target · Method | **HTTP** · **POST** |
| URL | `https://run.googleapis.com/v2/projects/<PROJECT_ID>/locations/<REGION>/jobs/<JOB>:run` |
| Body | `{}` with header `Content-Type: application/json` |
| Auth header | **OAuth token**, with a dedicated service account |

Grant that service account permission to run **that specific job** (*Jobs → Permissions*, role *Cloud Run
Developer* at job level) rather than a project-wide role.

> Cost: Cloud Scheduler bills **per job**, not per execution — 3 jobs are free per billing account, then
> $0.10/job/month. These two fit inside the free allowance, and the job compute is far inside the Cloud
> Run monthly free tier (~2.3k vCPU-seconds against 240k).

Before a release, the two gates are the test suite and the live evaluation:

```bash
python manage.py test                 # 101 tests, offline
python manage.py eval_agent           # live score, non-zero exit on failure
```

> Hosting: **Google Cloud Run** (scale-to-zero) + **Neon** for PostgreSQL — effectively free at portfolio
> traffic. Set a **budget alert** in Billing as the safety net.

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
* **HTTPS is enforced by configuration, not hope**: with `DEBUG=False` the app sets `SECURE_SSL_REDIRECT`, a one-year `SECURE_HSTS_SECONDS`, secure session/CSRF cookies and `SECURE_REFERRER_POLICY`; `SECURE_PROXY_SSL_HEADER` is enabled with `TRUST_PROXY_SSL_HEADER=True` behind Cloud Run's TLS terminator. `python manage.py check --deploy` is the gate and is clean (details in [Production Readiness](#security-flags-and-https)).
* **A probe never leaks**: `GET /healthz` reports only `status`, a database boolean and a chunk count.
* **CI enforces the above**: every push runs the test suite *and* `check --deploy`, so a security regression is caught before deploy.

> Not covered yet: a managed **secrets manager** (Google Secret Manager / Doppler) instead of a `.env` file on the
> host, and **admin hardening** (2FA on `/admin/`, a non-default admin path). Both are sensible next steps once the
> app is live.

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

> To be populated. The BarklAI reaction MP4s are generated footage (see `static/mascot/README.md`) and the favicon is an inline dog-emoji SVG — both will be credited or replaced when the final assets land.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

## Bug Log

Living log of known issues and their lifecycle. New bugs are added here as they are discovered; the status is updated when a fix lands.

**Status legend:** 🔴 Active — bug still present · 🔶 Known — documented, non-blocking (to be fixed later) · ✅ Fixed — resolved and verified · ❌ Withdrawn — the diagnosis was wrong (kept for the record).

| ID | Status | Bug | Discovered | Fixed | How it was fixed |
| --- | --- | --- | --- | --- | --- |
| B-001 | ✅ Fixed | **Danish questions answered in English** (2 of 3 in a live probe): the JSON contract demanded an English `reply` while the persona demanded the recruiter's language, and the offline interview heuristics were English-only. | 2026-09-13 | 2026-09-13 | Dropped the hard-coded language from the contract, added `LANGUAGE_RULES` + the interface-language fallback, and a one-shot `detect_language()` retry guard (`AGENT_LANGUAGE_GUARD`). Offline fallbacks now follow the message language and the Danish interview hints were added. See [Language parity](#language-parity-en-and-da). |
| B-002 | ✅ Fixed | **Interview requests were not actionable**: the session was flagged, but no contact details were ever collected (`chat.js` never sent `hr_*` and no form existed), and nobody was notified. | 2026-09-13 | 2026-09-13 | Added the `InterviewRequest` model (event per capture), the hand-off form, `POST /api/chat/contact` (no LLM call) and the idempotent email notification with `retry_interview_notifications`. See [Interview hand-off](#interview-hand-off). |
| B-003 | ❌ Withdrawn | **"Invented facts" — false alarm.** I claimed the agent added Firestore, Cloud Build and Secret Manager to Andrea's Google Cloud stack as hallucinations. They are real project technology: those services appear in the `aura-visual` and `django-cloud-ecommerce` READMEs, i.e. **inside the knowledge base**. The original check only grepped the local files, never the 21 READMEs stored in the database. | 2026-09-13 | 2026-09-13 | Diagnosis withdrawn. The `GROUNDING_RULES` block added for it is still valuable (it is what makes the "not in the ground truth" answer reliable), and the golden set now carries guards that were **verified absent from the corpus** (`vertex ai`, `azure`, `kubernetes`, `terraform`). See [Grounded answers](#grounded-answers). |
| B-004 | ✅ Fixed | **The agent echoed a personal identifier.** Asked about work authorisation, BarklAI answered "he is a resident with a CPR number". Root cause: the curated profile *itself* claimed "eligible to work — **resident with CPR**" twice, contradicting its own rule at the bottom of the file ("never share personal identifiers"). The prompt rule alone could not beat a ground truth that volunteered the identifier. | 2026-09-13 | 2026-09-14 | Redacted the profile (now simply "eligible to work in Denmark"), re-ran `sync_knowledge` + `build_index` so the stored text matches, and kept the prompt rule as defence in depth. Three golden-set cases (`en-authorisation`, `en-availability`, `da-arbejdstilladelse`) now assert that `cpr` never appears. |
| B-005 | ✅ Fixed | **Adding the `sources` field broke whole answers.** With the richer contract the model sometimes replied in prose (`… sources: []`) instead of JSON; Groq rejected it with `400 json_validate_failed` and the code treated that as a total failure, so the recruiter got "I lost the scent of my Groq brain" instead of a perfectly good answer. Caught by a live citation check, not by the mocked unit tests. | 2026-09-14 | 2026-09-14 | `_salvage_failed_generation()` recovers the refused text from `error.failed_generation`, strips the stray `sources:` line and keeps the answer (citations stay empty); the offline interview heuristic still flags intent on the salvaged prose. Covered by `JsonModeSalvageTests`. |
| B-006 | 🔴 Active | **The first Cloud Run deploy could never start.** The container's stderr said `sh: 1: exec: gunicorn: not found`, and one second later the platform's default startup TCP probe reported `The instance was not started`. The builder installs with `pip install --target=/install`, which puts the console scripts in a subdirectory of that target, while the runtime stage copied only `site-packages` — so no `gunicorn` executable ever reached the runtime `PATH`. The image built and pushed happily because every build-time step runs as `python manage.py …`, which needs no console script, and Django was never imported, so not one environment variable was ever read. | 2026-09-19 | — | The `CMD` now runs `python -m gunicorn`, which needs no `PATH` entry at all (gunicorn's `__main__` calls the same entry point as the console script), and the build ends with a smoke test — `DEBUG=True python -m gunicorn --check-config barkai.wsgi:application`, which parses the flags *and* imports the app — so an image that cannot start fails the **build** instead of the deploy. Neither the unit suite nor `check --deploy` could have caught it: the bug lives between the build and the boot. Awaiting the rebuild that proves the container starts. |
| B-007 | 🔴 Active | **A fresh tag could never be deployed: `Image '…:e6a55cc' not found`.** The pipeline built the image with `docker build` and published it through the `images:` block at the end of `cloudbuild.yaml` — but Cloud Build pushes those artifacts only *after* the whole build succeeds, while `deploy-service` runs *during* the build and needs the tag to be in the registry already. So the deploy step always looked for something that did not exist yet; it failed, the build failed with it, and that is precisely why the push never ran. The deadlock meant the commit that fixed B-006 could never reach Cloud Run: the service kept running the previous image. | 2026-09-19 | — | The `build` step now runs `docker build` **and** `docker push` for both tags, so the image is published before anything consumes it, and the `images:` block is gone with a comment recording why it must not come back. Verified before pushing: the extracted step script passes `bash -n` and produces both `docker push` calls with the right image reference against a stub `docker`. Awaiting the build that finally deploys the tag. |
| B-008 | ✅ Fixed | **A black pillarbox (and a grey hairline) around the mascot.** The reaction MP4s are 1280x720 files whose real content is the vertical take in the middle, pillarboxed in black ~401 px per side — so the player painted a black rectangle around the dog on the white page. Cropping the bars with `object-cover` removed the black but left a grey column at each end of the content (x=401 ≈ 172/255, x=878 ≈ 171/255: the H.264 ringing on the black→white transition), which showed as a hairline down both sides of the player. | 2026-09-20 | 2026-09-20 | The `<video>` now sits in a `472:720` box with `object-cover object-center`, which crops to source columns x=404..875. That width is **measured**, per column, on all six clips (Chrome + `<canvas>`; no ffmpeg was available locally) instead of guessed from the 476 clean pixels: the extra 4 px are what removes both grey hairline columns, and the edge columns now read 253-255 — white on a white page. `chat.css` adds a 1 px white fade on `.js-video-shell::before/::after` as a safety net for future clips. The `ASSET_VERSION` cache-buster (`?v=` on every static asset) shipped with it, because WhiteNoise's one-year `max-age` would otherwise have kept the old stylesheet for every returning visitor. **Phase B** then re-encoded all six clips at that same measured window (`crop=472:720:404:0`, `-an`, crf 28, `-tune animation` — checked frame by frame against the source at 3x zoom), so the files now *are* the 472x720 take: the mascot payload went from 7.5 MB to 3.9 MB (−48%, `searching` 3.3 MB → 1.8 MB) with no visible loss. |

> When a new bug is found, add a row with status 🔴 **Active**, the discovery date and a short description, then fill in the **Fixed** date and the resolution once a fix is verified.


