# ScreenAI

A screen-reading assistant. It captures your screen, sends the frames to a
vision model, and answers questions about what is on it — typed, or spoken by
an interviewer and captured from the meeting audio. Answers can be tailored to
a CV and job description you supply.

React + Vite frontend, FastAPI backend, Supabase for auth and history.
Live at **https://screenai.tech**. Deployment is covered in
[deploy/README.md](deploy/README.md).

---

## How it works

```
Browser ──getDisplayMedia──▶ React (Vite)
                              │  every request carries the Supabase JWT
                    screenshots│  PNG at 768px short side
                              ▼
                        FastAPI backend ──▶ OpenAI vision  ──▶ SSE token stream
                              ▲
      meeting audio clip      │  one push-to-talk recording (WebM/Opus)
                              ▼
                     Groq whisper-large-v3 ─▶ LLM ─▶ SSE token stream

React ──▶ Supabase (auth, analysis history, usage counts)
```

Session state — pinned screenshots plus the last five exchanges — lives in
memory in the backend process, keyed by a session UUID and owned by the user
who created it. Idle sessions are evicted every ten minutes.

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

### Voice: capturing the interviewer

The browser captures the audio, not the server. The user shares the meeting
tab with "Share tab audio" on (or the entire screen with "Share system audio"
for a desktop meeting app), or falls back to the microphone. Each push-to-talk
press records one clip with `MediaRecorder` and uploads it; Whisper accepts the
browser's WebM/Opus or MP4 directly, so the server never decodes audio.

A press that picked up no sound is dropped in the browser, and Whisper's stock
output for silence ("Thank you.") is discarded on the server, so neither turns
into an answer to a question nobody asked.

If a profile is set, its job title and the distinctive technical terms in the
job description are passed to Whisper as a vocabulary hint, so role-specific
jargon survives transcription.

## API keys: yours or the server's

Every key is optional in `backend/.env`. Whichever ones you leave blank, the
app asks the signed-in user for when they first need it:

- Start an analysis with no OpenAI key configured and a prompt appears. The key
  is kept in that browser tab's `sessionStorage`, sent as an `X-OpenAI-Api-Key`
  header, and never written to disk or stored with session state on the server.
- Voice mode does the same, asking for the Groq key and the voice provider's
  key; they travel as `X-Groq-Api-Key` / `X-OpenAI-Api-Key` headers.
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

`sessionStorage` is readable by any script on the page, which is why the site
ships a Content-Security-Policy allowing scripts from its own origin only.

## Requirements

- **Python 3.10+** and **Node 22.12+**. Any OS.
- An **OpenAI API key** (vision, and the voice LLM by default) — in
  `backend/.env`, or entered by each user in the browser
- A **Groq API key** (speech-to-text) — only for the voice feature, same choice
- A **Supabase project** (auth, history)

## Setup

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows; source venv/bin/activate elsewhere
pip install -r requirements-dev.txt

cp .env.example .env             # set SUPABASE_URL at minimum
python -m uvicorn main:app --reload --port 8000
```

`SUPABASE_URL` is required: the backend verifies every request's Supabase
token against it and refuses requests without one.

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
is the only thing preventing any visitor from reading and writing every row:

```sql
alter table analysis_history enable row level security;
alter table usage_tracking  enable row level security;

create policy "own history" on analysis_history
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own usage" on usage_tracking
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

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
| `SUPABASE_URL` | — | **Required.** Project whose tokens the API accepts |
| `SUPABASE_JWT_SECRET` | — | Only for legacy HS256 projects |
| `ENVIRONMENT` | `development` | `production` hides API docs, enables HSTS |
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
| `RATE_LIMIT_*_PER_MIN` | 20–40 | Per-user request limits |
| `VITE_API_URL` | localhost:8000 | Backend origin; https in production |

Each voice provider reads its **own** key, so switching `LLM_PROVIDER` no longer
breaks screenshot analysis.

## API

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Which keys are configured (public) |
| `POST` | `/api/session/create` | New session UUID |
| `POST` | `/api/screenshot/add` | Pin a frame as context (deduplicated) |
| `POST` | `/api/analyze/stream` | Analyse; streams tokens over SSE |
| `POST` | `/api/context/clear/{id}` | Drop pinned frames, keep conversation |
| `DELETE` | `/api/session/{id}` | Delete the session |
| `POST` | `/api/parse-pdf` | Extract CV text from an uploaded PDF |
| `POST` | `/api/voice/answer` | Recorded question in; transcript + answer over SSE |
| `POST` | `/api/voice/reset/{id}` | Forget the voice conversation |

Everything except `/health` requires `Authorization: Bearer <Supabase access
token>` and is rate limited per user. Sessions belong to the user who created
them; another user's session ID behaves exactly like an unknown one.

Unknown session IDs return `404 {"code": "session_not_found"}`. The client
treats that as "create a new session and retry once", so a backend restart is
invisible rather than a wall of failures.

`/api/analyze/stream` accepts an optional `X-OpenAI-Api-Key` header, used only
when the server has no key of its own. Without a usable key it returns
`401 {"code": "api_key_required"}`, which is the browser's cue to prompt; a key
the provider rejects arrives as an `invalid_api_key` SSE error so the user can
correct it.

SSE events are typed: `start`, `token`, `done`, `error`.

`/api/voice/answer` takes a multipart upload (`session_id`, `audio`, optional
`profile` JSON) and streams `start`, `transcription`, `token`, `done`, or
`no_speech` when nothing intelligible was said. A missing key returns
`401 {"code": "api_key_required", "needed": [...]}` naming every key to ask for.

## Tests

```bash
cd backend
python -m pytest
```

Covers image sizing and the tile-cost formula, decompression-bomb and format
guards, perceptual-hash deduplication, session lifecycle, ownership and caps,
prompt-cache message ordering, credential precedence, and the HTTP security
layer: token verification (forged, expired, wrong-project and unsigned tokens),
rate limits, body-size limits, CORS and response headers. No network or keys
required.

```bash
cd frontend
npm run lint
npm run build
```

## Security model

- **Authentication.** Every API request carries the user's Supabase access
  token, verified locally against the project's JWKS (or the legacy HS256
  secret): signature, issuer, audience and expiry. A server without
  `SUPABASE_URL` refuses everything rather than running open.
- **Isolation.** Sessions are bound to the token's user. Caps per user and in
  total bound the memory any one account can hold.
- **Abuse limits.** Per-user rate limits on every endpoint group (PDF parsing
  has its own small budget). Request bodies are capped before they are read,
  and only read *after* sign-in and rate-limit checks pass, then validated
  without building intermediate objects, so oversized or deeply nested
  payloads cannot exhaust memory. Images are restricted to PNG/JPEG/WebP,
  checked for decompression bombs, decoded two at a time, and re-compressed so
  no frame pins more than ~1.5 MB; all pinned screenshots share a global
  memory budget. PDFs are checked by content and parsed in a separate process
  that is killed at a 20-second deadline (and memory-capped on Linux), one at a
  time. Audio is restricted to recorder formats and size-capped.
- **User keys.** Sent per request in headers, used once, never stored or
  logged. The server key, when set, always wins.
- **Browser.** A Content-Security-Policy limits scripts to the site's own
  origin; the app refuses to render inside a frame; CVs and keys are cleared
  on sign-out and scoped to the signed-in user.
- **Transport.** HTTPS everywhere; HSTS and hardening headers on the API.

Known limits: sessions and rate-limit counters live in process memory, so the
backend runs as a single instance (restart = sessions recreated transparently).
Usage counts in Supabase are advisory and written by the client under RLS.

## Licence

None specified.
