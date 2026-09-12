# Privacy & GDPR — BarkAI

> Plain-language engineering notes. **Not legal advice** — have the notice and
> the processing register reviewed before real production use.

## Roles

| Who | Role |
| --- | --- |
| Andrea Latorre (site owner) | **Data controller** |
| Groq | Processor — generates the chat replies |
| Cloudflare (Workers AI) | Processor — computes the embeddings for retrieval |
| GitHub | Source of the public READMEs ingested into the knowledge base |
| Hosting provider | Processor — runs the Django app |
| Neon (PostgreSQL) | Processor — stores conversations and the knowledge base |

## What is processed

* the **messages** a recruiter sends (and the replies);
* a random **session UUID** kept in the browser (`localStorage`), the login-free identity;
* optionally a **name / email / company** if the recruiter shares them;
* a flag remembering the introduction was already shown.

## Legal bases

| Purpose | Basis |
| --- | --- |
| Answering the recruiter / providing the chat | **Contract** (or pre-contractual steps) |
| Flagging an interview request | **Legitimate interest** |
| Securing the service (logs, abuse prevention) | **Legitimate interest** |

No marketing, no profiling, no selling of data. Because no processor trains on
the data (see below), **no consent checkbox is required** for the chat itself.

## Processors and data usage

* **Groq** — the message text is sent to generate the answer. API data is not
  used to train models.
* **Cloudflare Workers AI** — the text is sent to compute embeddings. Cloudflare
  states it neither creates nor trains the models on Workers AI and does **not**
  use customer content to train/improve services without explicit consent.
  Models are Cloudflare-hosted (no third-party routing).
* **GitHub** — only **public** repository READMEs are read (no personal data of
  recruiters).
* A **DPA (art. 28)** must be in place with every processor. Cloudflare and
  OpenAI/Google publish standard DPAs; Groq's terms apply to the API.

## Retention

Conversations are deleted automatically after `SESSION_RETENTION_DAYS`
(default **90**) of inactivity:

```bash
python manage.py purge_old_sessions            # uses SESSION_RETENTION_DAYS
python manage.py purge_old_sessions --days 30 --dry-run
```

Schedule it (cron / Cloud Scheduler) so reality matches the privacy notice.

## Data-subject rights

* **Access** — the conversation is visible in the chat (and in the Django admin).
* **Erasure** — the *"Delete my conversation"* button on the chat page calls
  `POST /session/delete/` with the session UUID and deletes the session (and its
  messages) immediately. `purge_old_sessions` handles the rest by age.
* **Rectification / portability / objection** — handled manually via the contact
  address below.

## Transfers outside the EU

Groq, Cloudflare, GitHub and Neon are US-based companies: transfers rely on the
**SCCs** included in their DPAs. Cloudflare additionally offers EU data
localisation on enterprise plans.

## Cookies and local storage

No tracking or advertising cookies. The browser stores only:

* `barkai.session_id` — the conversation identifier (strictly necessary);
* `barkai_visited` — remembers that the introduction was already shown;
* Django's session cookie, used only to remember the chosen language (EN/DA).

Because these are strictly necessary, no cookie banner is required; they must
still be described in the notice (they are).

## Art. 30 record (summary)

| Field | Value |
| --- | --- |
| Processing | Interactive recruiter chat about Andrea's career |
| Data subjects | Recruiters / hiring managers |
| Categories | Messages, session UUID, optional contact details |
| Recipients | Groq, Cloudflare, hosting, Neon |
| Retention | `SESSION_RETENTION_DAYS` (default 90) |
| Transfers | US processors under SCCs (DPA) |
| Security | TLS, secrets in env, CSRF-protected POSTs, minimal access |

## Contact

`PRIVACY_CONTACT_EMAIL` (default `latorre.andrea.93@gmail.com`).
