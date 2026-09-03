# ScreenAI

A screen-reading assistant. It captures your screen, sends the frames to a
vision model, and answers questions about what is on it — either typed, or
spoken through a live voice channel. Answers can be tailored to a CV and job
description you supply.

React + Vite frontend, FastAPI backend, Supabase for auth and history.

> **Status: local development only.** The backend has no authentication and no
> rate limiting, and every service URL is hard-coded to `localhost`. Read
> [Before deploying](#before-deploying) before putting this anywhere reachable.

---

## How it works

```
Browser ──getDisplayMedia──▶ React (Vite)
                              │
                    screenshots│  base64 JPEG
                              ▼
                        FastAPI backend ──▶ OpenAI vision  ──▶ SSE token stream
                              │
                    mic audio │  WebSocket
                              ▼
                     Silero VAD ─▶ Groq whisper-large-v3 ─▶ LLM ─▶ spoken answer
                              
React ──▶ Supabase (auth, analysis history, usage counts)
```

Screenshots are compressed before they leave the browser's round trip: context
frames at 800 px and quality 40, the current frame at 1280 px and quality 60.
Context images are compressed once at storage time and reused, so a long session
does not re-encode the same frames on every question.

Session state — stored screenshots plus the last 10 conversation messages — lives
in memory in the backend process, keyed by a session UUID, and idle sessions are
dropped hourly.

## Requirements

- **Python 3.10+** and **Node 18+**
- **Windows.** `PyAudioWPatch` is Windows-only, so the voice feature — and
  therefore `pip install -r requirements.txt` — will not work on macOS or Linux.
  Screen analysis itself is platform-independent; the dependency is not.
- An **OpenAI API key** (vision, and the voice LLM)
- A **Groq API key** (speech-to-text) — only for the voice feature
- A **Supabase project** (auth, history)

## Setup

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt

cp .env.example .env             # then fill in your keys
python -m uvicorn main:app --reload --port 8000
```

`torch`, `torchaudio` and `silero-vad` are pulled in for voice activity
detection and are a ~2 GB download.

Check it came up: <http://localhost:8000/health> reports whether the OpenAI key
was found.

### Frontend

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

### Supabase

Create a project, then create two tables:

| Table | Columns |
| :--- | :--- |
| `analysis_history` | `id`, `user_id`, `question`, `answer`, `created_at` |
| `usage_tracking` | `id`, `user_id`, `date`, `api_calls` |

**Enable Row Level Security on both, with policies restricting rows to
`auth.uid() = user_id`.** The anon key is shipped to the browser by design — RLS
is the only thing preventing any visitor from reading and writing every row.

The Supabase URL and anon key are currently hard-coded in
`frontend/src/lib/supabase.js`. Edit them there for now; see
[Before deploying](#before-deploying).

## Configuration

All backend settings live in `backend/.env` — see
[`backend/.env.example`](backend/.env.example) for the full list with notes.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | — | Required. Vision, and the voice LLM |
| `OPENAI_MODEL` | `gpt-4.1` | Screenshot analysis; must accept images |
| `LLM_PROVIDER` | `openai` | Voice backend: `openai`, `groq`, `anthropic` |
| `LLM_MODEL` | `gpt-4.1` | Voice model |
| `GROQ_API_KEY` | — | Speech-to-text (`whisper-large-v3`) |
| `CORS_ORIGINS` | localhost:3000,5173 | Allowed browser origins |

The frontend reads no environment variables at all; API URLs are hard-coded.

## API

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Reports whether the OpenAI key is configured |
| `POST` | `/api/session/create` | New session UUID |
| `POST` | `/api/screenshot/add` | Add a frame to session context |
| `POST` | `/api/analyze/stream` | Analyse; streams tokens over SSE |
| `POST` | `/api/context/clear/{id}` | Drop stored screenshots, keep conversation |
| `DELETE` | `/api/session/{id}` | Delete the session |
| `POST` | `/api/parse-pdf` | Extract CV text from an uploaded PDF |
| `WS` | `/ws/voice` | Live audio in, streamed answer out |

## Before deploying

These are known and unfixed. Each one is fine on `localhost` and not fine on a
public host.

**No authentication on the backend.** The frontend never sends the Supabase JWT,
and the backend never checks for one. Anyone who can reach the API can call
`/api/analyze/stream` and spend your OpenAI credits without limit. Verify the
Supabase JWT in a FastAPI dependency before exposing this.

**Session IDs are not tied to a user.** `/api/analyze/stream`,
`/api/context/clear/{id}` and `/api/session/{id}` accept any UUID without an
ownership check, and an unrecognised ID silently creates a new session. A guessed
session ID returns another user's screenshots and conversation.

**No rate limiting or request size cap.** Screenshot payloads are unbounded.

**Errors are returned verbatim.** `routers/analyze.py` streams `str(e)` to the
client, which can expose internals.

**`user_id` is supplied by the client** when writing history and usage. Without
RLS policies, a user can write rows as anyone. Usage limits are enforced in the
browser only.

**Hard-coded URLs.** `localhost:8000` appears in `services/api.js` (×3),
`components/ProfileModal.jsx` and `pages/InterviewPage.jsx`. Move these to
`import.meta.env.VITE_API_URL`, and the Supabase config to
`VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`, before building for anywhere but
a dev server.

**In-memory session store.** `services/context_manager.py` is a process
singleton: state is lost on restart and is not shared across workers, so the app
is single-instance only. Redis would fix both.

## Notes

There are no tests. `PyPDF2` is deprecated in favour of `pypdf`. Six
dependencies in `requirements.txt` are unpinned (`numpy`, `scipy`, `torch`,
`torchaudio`, `groq`, `PyPDF2`), so a fresh install is not reproducible.

## Licence

None specified.
