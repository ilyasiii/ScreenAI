# ScreenAI

A screen-reading assistant. It captures your screen, sends the frames to a
vision model, and answers questions about what is on it — either typed, or
spoken through a live voice channel. Answers can be tailored to a CV and job
description you supply.

React + Vite frontend, FastAPI backend, Supabase for auth and history.

> **Status: local development only.** The backend has no authentication and no
> rate limiting. Read [Before deploying](#before-deploying) before putting this
> anywhere reachable.

---

## How it works

```
Browser ──getDisplayMedia──▶ React (Vite)
                              │
                    screenshots│  PNG at 768px short side
                              ▼
                        FastAPI backend ──▶ OpenAI vision  ──▶ SSE token stream
                              │
                    mic audio │  WebSocket
                              ▼
                     Silero VAD ─▶ Groq whisper-large-v3 ─▶ LLM ─▶ spoken answer

React ──▶ Supabase (auth, analysis history, usage counts)
```

Session state — pinned screenshots plus the last five exchanges — lives in
memory in the backend process, keyed by a session UUID. Idle sessions are
evicted every ten minutes.

### Why screenshots are 768px on the short side

The vision API rescales every `detail: high` image so its **short** side is
768 px, then bills `ceil(w/512) × ceil(h/512)` tiles. That has two consequences
that decide the whole image pipeline:

- Sending something **larger** is downscaled on arrival. Same token cost, wasted
  upload.
- Sending something **smaller** is upscaled back to 768. Same token cost, and
  the detail is gone for good.

So 768 is simultaneously the cheapest and the sharpest setting, and it is what
the browser captures at. Downscaling from a 1440p or 4K screen is done in
repeated halving steps, because a single large `drawImage` reduction aliases
small text into mush.

Frames are captured as **PNG** and encoded to JPEG exactly once, on the server,
with 4:4:4 chroma. The browser's own JPEG encoder uses 4:2:0 subsampling, which
bleeds syntax highlighting into glyph edges — and encoding in the browser *and
then again* on the server compounded the damage twice over.

### Why the message order matters

Requests are assembled stable-prefix-first:

```
system  →  pinned screenshots  →  conversation history  →  current screen + question
```

Everything before the last message is byte-identical between consecutive
questions, so automatic prompt caching can serve it at a fraction of the input
price and a much shorter time to first token. Putting the images in the final
message — after a history that grows every turn — means the most expensive part
of the request is the one part that never gets cached.

### Voice: what reaches Whisper

Voice activity detection decides **where** the speech is; it never deletes
audio. The whole recording is kept, resampled in one pass, trimmed to the speech
region with 350 ms of padding at each end, and normalised once as a single
signal. Dropping sub-threshold chunks as they arrive — the obvious design —
eats the leading consonant of most sentences and removes the pauses Whisper
uses to punctuate.

If a profile is set, its job title and the distinctive technical terms in the
job description are passed to Whisper as a vocabulary hint, so role-specific
jargon survives transcription.

## API keys: yours or the server's

Every key is optional in `backend/.env`. Whichever ones you leave blank, the
app asks the signed-in user for when they first need it:

- Start an analysis with no OpenAI key configured and a prompt appears. The key
  is kept in that browser tab's `sessionStorage`, sent as an `X-OpenAI-Api-Key`
  header, and never written to disk or stored with session state on the server.
- Voice mode does the same over its WebSocket handshake, asking for the Groq
  key and the voice provider's key.
- Keys are cleared on sign-out and when the tab closes.

**A key in `backend/.env` always wins.** Users are never prompted for a
provider the server can already serve, and a client-supplied key can never
redirect usage away from a configured one. So:

| You want | Do this |
| :--- | :--- |
| Everyone uses your key | Set the keys in `backend/.env` |
| Everyone pays for their own | Leave them blank |
| No client keys at all | Set `ALLOW_CLIENT_API_KEYS=false` |

With `ALLOW_CLIENT_API_KEYS=false` and no server key, the app reports the
problem rather than prompting for a key it would refuse.

`sessionStorage` is readable by any script on the page. That is a fair trade
for a locally-run tool, and not a substitute for a server-side key in a real
deployment.

## Requirements

- **Python 3.10+** and **Node 18+**. Verified on 3.12 and 3.14; 3.12 is the
  safer choice for the voice feature (see the note under Backend setup).
- **Windows.** `PyAudioWPatch` is Windows-only, so the voice feature — and
  therefore `pip install -r requirements.txt` — will not work on macOS or Linux.
  Screen analysis itself is platform-independent; the dependency is not.
- An **OpenAI API key** (vision, and the voice LLM by default) — in
  `backend/.env`, or entered by each user in the browser
- A **Groq API key** (speech-to-text) — only for the voice feature, same choice
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

`torch` and `torchaudio` are pulled in solely to run Silero VAD on the CPU. If
pip resolves a CUDA build on your platform, install the CPU wheels first:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**If the install tries to compile `pydantic-core` and fails on a missing
`link.exe`,** you are on a Python version that has no prebuilt wheel for some
pinned package, so pip fell back to building it from Rust source. Nothing in
this project needs a compiler. `requirements.txt` uses version *ranges* rather
than exact pins precisely so pip can pick a build that exists for your
interpreter — if you have edited it to pin versions exactly, that is the cause.
Recreate the environment rather than repairing it:

```bash
deactivate                       # if the venv is active
rmdir /s /q venv                 # Windows; rm -rf venv elsewhere
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On **Python 3.14**, Silero VAD still loads but torch prints a warning that
`torch.jit.load` "is not supported in Python 3.14+ and may break". It works
today; if voice mode ever fails to load the VAD after a torch upgrade, use
Python 3.12.

Check it came up: <http://localhost:8000/health>.

### Frontend

```bash
cd frontend
cp .env.example .env.local       # then fill in your Supabase project
npm install
npm run dev                      # http://localhost:5173
```

### Supabase

Create a project, then two tables:

| Table | Columns |
| :--- | :--- |
| `analysis_history` | `id`, `user_id`, `question`, `answer`, `created_at` |
| `usage_tracking` | `id`, `user_id`, `date`, `api_calls` |

**Enable Row Level Security on both, with policies restricting rows to
`auth.uid() = user_id`.** The anon key is shipped to the browser by design — RLS
is the only thing preventing any visitor from reading and writing every row.

Then add the atomic usage counter. Without it the client falls back to a
read-modify-write that loses increments when two analyses finish together:

```sql
create unique index if not exists usage_tracking_user_date
  on usage_tracking (user_id, date);

create or replace function increment_usage(p_user_id uuid, p_date date)
returns integer
language sql
security invoker
as $$
  insert into usage_tracking (user_id, date, api_calls)
  values (p_user_id, p_date, 1)
  on conflict (user_id, date)
    do update set api_calls = usage_tracking.api_calls + 1
  returning api_calls;
$$;
```

## Configuration

Backend settings live in `backend/.env`, frontend settings in
`frontend/.env.local`. Both `.env.example` files document every option.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | — | Vision and the voice LLM. Blank prompts the user |
| `GROQ_API_KEY` | — | Speech-to-text. Blank prompts the user |
| `ANTHROPIC_API_KEY` | — | Only when `LLM_PROVIDER=anthropic` |
| `ALLOW_CLIENT_API_KEYS` | `true` | Whether users may supply their own key |
| `OPENAI_MODEL` | `gpt-4.1` | Screenshot analysis; must accept images |
| `LLM_PROVIDER` | `openai` | Voice backend: `openai`, `groq`, `anthropic` |
| `IMAGE_SHORT_SIDE` | `768` | Capture target — see above before changing |
| `IMAGE_JPEG_QUALITY` | `88` | Below ~80, JPEG ringing starts costing answers |
| `MAX_CONTEXT_IMAGES` | `6` | Main cost dial: ~1.1k tokens per pinned frame |
| `CORS_ORIGINS` | localhost:3000,5173 | Allowed browser origins |
| `VITE_API_URL` | localhost:8000 | Backend origin; the WS URL derives from it |

Each voice provider reads its **own** key, so switching `LLM_PROVIDER` no longer
breaks screenshot analysis.

## API

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Which keys are configured, model, live session count |
| `POST` | `/api/session/create` | New session UUID |
| `POST` | `/api/screenshot/add` | Pin a frame as context (deduplicated) |
| `POST` | `/api/analyze/stream` | Analyse; streams tokens over SSE |
| `POST` | `/api/context/clear/{id}` | Drop pinned frames, keep conversation |
| `DELETE` | `/api/session/{id}` | Delete the session |
| `POST` | `/api/parse-pdf` | Extract CV text from an uploaded PDF |
| `WS` | `/ws/voice` | Live audio in, streamed answer out |

Unknown session IDs return `404 {"code": "session_not_found"}`. The client
treats that as "create a new session and retry once", so a backend restart is
invisible rather than a wall of failures.

`/api/analyze/stream` accepts an optional `X-OpenAI-Api-Key` header, used only
when the server has no key of its own. Without a usable key it returns
`401 {"code": "api_key_required"}`, which is the browser's cue to prompt; a key
the provider rejects arrives as an `invalid_api_key` SSE error so the user can
correct it.

SSE events are typed: `start`, `token`, `done`, `error`.

`/ws/voice` opens with a handshake. The server sends
`{"type": "ready", "needs_groq_key": bool, "needs_llm_key": bool, ...}`; the
client replies with `{"action": "init", "credentials": {...}}`. The audio
pipeline is only built once that is accepted, so opening the page no longer
seizes the loopback device.

## Tests

```bash
cd backend
python -m pytest
```

Covers image sizing and the tile-cost formula, perceptual-hash deduplication,
session lifecycle and window trimming, prompt-cache message ordering, the audio
conversion maths, and credential precedence. No network, keys, or audio device
required.

```bash
cd frontend
npm run lint
npm run build
```

## Before deploying

These are known and unfixed. Each one is fine on `localhost` and not fine on a
public host.

**No authentication on the backend.** The frontend never sends the Supabase JWT,
and the backend never checks for one. Anyone who can reach the API can call
`/api/analyze/stream` and spend your OpenAI credits without limit. Verify the
Supabase JWT in a FastAPI dependency before exposing this.

**Session IDs are not tied to a user.** Unknown IDs are now rejected rather than
silently creating a session, but a *valid* guessed ID still returns another
user's screenshots and conversation. Bind sessions to the JWT subject.

**No rate limiting.** Payload size is capped (`MAX_IMAGE_BYTES`,
`MAX_PDF_BYTES`) but request frequency is not.

**User-supplied keys pass through an unauthenticated backend.** With no server
key set, anyone who can reach the API can have it call OpenAI with a key they
supply. That costs you nothing directly, but it makes your server an open proxy
for someone else's key. Either set a server key and
`ALLOW_CLIENT_API_KEYS=false`, or put authentication in front of the API, before
exposing this.

**`user_id` is supplied by the client** when writing history and usage. RLS is
what makes that safe. Usage limits are advisory and enforced in the browser only.

**In-memory session store.** `services/context_manager.py` is a process
singleton: state is lost on restart and is not shared across workers, so the app
is single-instance only. Redis would fix both.

**The voice feature is structurally single-user.** It captures system-wide
WASAPI loopback audio and opens a fresh loopback stream per WebSocket
connection, so two tabs fight over one device. It is a local desktop feature,
not a server one.

## Licence

None specified.
