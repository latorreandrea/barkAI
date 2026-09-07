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

## 📜 License
MIT License — feel free to explore, fork, and build your own interactive career agent!
