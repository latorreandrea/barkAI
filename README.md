# barkAI
BarkAI — An interactive, RAG-powered AI agent acting as a personal career assistant and technical interviewer. Built with Django Ninja, Groq (Qwen 2.5), and Tailwind CSS.
A future mobile app version built with Flutter is under evaluation.

# 🐶 BarkAI — Interactive AI Career Agent & Technical Assistant

**BarkAI** is a self-hosted, interactive AI agent designed to replace traditional cold emailing and static PDF resumes with a real-time, interactive chat interface for recruiters and hiring managers.

Powered by a Retrieval-Augmented Generation (RAG) pipeline, BarkAI indexes my open-source GitHub repositories, architecture decisions, and professional background to answer recruiter inquiries, discuss technical implementations, and automatically flag interview opportunities.

---

## 🐾 Meet Barkley!
The project mascot is **Barkley**, an AI-powered Cocker Spaniel developer who "fetches" accurate data about my tech stack, past projects, and code choices.

> *"Woof! I'm Barkley. Ask me anything about Andrea's experience with Python, cloud architectures, or RAG pipelines, or request an interview directly through the chat!"*

---

## 🛠 Tech Stack & Architecture

* **Backend:** Django Ninja (Async REST API & ORM)
* **LLM Engine:** Groq API (`Qwen 2.5 32B`)
* **Knowledge Retrieval:** RAG pipeline (Indexing GitHub repos, Markdown career docs, and project architecture)
* **Frontend:** Interactive Web Chat (Django Templates + Tailwind CSS)
* **Human-in-the-Loop & Intent Detection:** Automatic intent classification for interview requests with real-time email/push notification triggers.

---

## 🚀 Key Features

1. **RAG-Powered Q&A:** Answers recruiter questions accurately using verified project documentation without hallucinating skills.
2. **Session Persistence:** Recognizes returning recruiters across days using persistent session UUIDs without friction or login walls.
3. **Interview Intent Detection:** Automatically flags when a recruiter requests a meeting or call and sends immediate notifications to the candidate.
4. **Data Privacy & Cost Optimization:** Designed with open-source models and self-hosted components to ensure data control and cost efficiency.

---

## 🚀 Getting Started (Local Development)

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

> `DEBUG` defaults to **True** when unset. For production always export
> `DEBUG=False` plus the `DB_*` credentials and a strong `SECRET_KEY`.

### Useful URLs

* Web UI (chat with Barkley): <http://127.0.0.1:8000/>
* Swagger/OpenAPI docs: <http://127.0.0.1:8000/api/docs>
* Django admin: <http://127.0.0.1:8000/admin/>
* REST endpoints: `GET /api/chat/history/{session_id}` and `POST /api/chat/send`

### Project layout

```
barkai/                  # project settings + root URLconf (Ninja API mounted at /api/)
chat/                    # the chat application
├── api/                 # Django Ninja package (schemas.py + router.py)
├── models.py            # ChatSession + ChatMessage
├── services.py          # mock agent replies (seam for the Groq/RAG pipeline)
├── templates/chat/      # app-scoped templates (index.html)
└── urls.py              # chat owns its URLconf
static/mascot/           # Barkley reaction MP4s (idle, searching, speaking, …)
.env                     # local env vars (gitignored) — load with `set -a; source .env; set +a`
```

### Tests

```bash
python manage.py test
```

### Production checklist

* Export `DEBUG=False` and set a strong `SECRET_KEY`.
* Configure the database via `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
  `DB_HOST`, `DB_PORT` (PostgreSQL is used by default when `DEBUG=False`).
* Pin `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`.
* Run `python manage.py collectstatic --noinput` and serve `staticfiles/`.
* Replace the Tailwind CDN `<script>` with a compiled Tailwind CLI stylesheet.
* Wire `chat/services.py` to the real Groq (Qwen 2.5) + RAG pipeline using
  `GROQ_API_KEY`.

---

## 📜 License
MIT License — feel free to explore, fork, and build your own interactive career agent!
