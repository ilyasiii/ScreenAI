/**
 * Backend client.
 *
 * Three things worth knowing:
 *
 * 1. Every request carries the user's Supabase access token. The backend
 *    refuses anything without one, so it cannot be used by people who are not
 *    signed in to this site.
 *
 * 2. Sessions self-heal. The backend 404s unknown session IDs instead of
 *    silently minting one, so this module catches `session_not_found`, creates
 *    a fresh session and retries once. A backend restart mid-session is now
 *    invisible to the user rather than a wall of failed requests.
 *
 * 3. Streaming goes through fetch, not EventSource, because the requests are
 *    POSTs with a body. The SSE framing is parsed by hand below.
 */
import axios from "axios";

import { API_BASE, API_ORIGIN } from "../config";
import { supabase } from "../lib/supabase";
import { getOpenAIKey, loadCredentials } from "./credentials";

/** Error thrown when the backend has no key and the user has not supplied one. */
export class ApiKeyRequiredError extends Error {
  constructor(message, { refused = false, needed = ["openai_key"] } = {}) {
    super(message || "An API key is required.");
    this.name = "ApiKeyRequiredError";
    // `refused` means the operator has disabled client-supplied keys, so
    // prompting the user would achieve nothing.
    this.refused = refused;
    // Which credential fields to ask for, e.g. ["groq_key", "openai_key"].
    this.needed = needed;
  }
}

/** The signed-in user's bearer token. getSession() refreshes it when stale. */
async function authHeaders() {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Headers carrying the user's own keys, when they have entered any.
 *
 * Headers rather than the body: they stay out of request-body logs, and the
 * backend never persists them alongside session state.
 */
function keyHeaders() {
  const key = getOpenAIKey();
  return key ? { "X-OpenAI-Api-Key": key } : {};
}

function voiceKeyHeaders() {
  const { groq_key, openai_key, anthropic_key } = loadCredentials();
  return {
    ...(groq_key ? { "X-Groq-Api-Key": groq_key } : {}),
    ...(openai_key ? { "X-OpenAI-Api-Key": openai_key } : {}),
    ...(anthropic_key ? { "X-Anthropic-Api-Key": anthropic_key } : {}),
  };
}

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use(async (config) => {
  const headers = await authHeaders();
  for (const [name, value] of Object.entries(headers)) config.headers.set(name, value);
  return config;
});

/** True when a failure means "the session is gone, make a new one". */
function isMissingSession(error) {
  const detail = error?.response?.data?.detail;
  return error?.response?.status === 404 && detail?.code === "session_not_found";
}

/** Convert a 401 from the backend into a typed error the UI can act on. */
function asKeyError(detail, fallbackNeeded) {
  const needed = detail?.needed || fallbackNeeded;
  if (detail?.code === "api_key_required") {
    return new ApiKeyRequiredError(detail.message, { needed });
  }
  if (detail?.code === "api_key_refused") {
    return new ApiKeyRequiredError(detail.message, { refused: true, needed });
  }
  return null;
}

/** A user-facing message for a failed request's `detail`. */
function describe(detail, status) {
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  return `Request failed (${status})`;
}

export async function createSession() {
  const { data } = await api.post("/session/create");
  return data.session_id;
}

/** Best-effort: free a session the page no longer needs. */
export async function deleteSession(sessionId) {
  try {
    await api.delete(`/session/${sessionId}`);
  } catch {
    // It expires on its own; nothing to do.
  }
}

/**
 * Run `fn(sessionId)`, and if the session has expired, create a new one and
 * retry exactly once.
 *
 * @param {string} sessionId
 * @param {(id: string) => Promise<any>} fn
 * @param {(id: string) => void} [onNewSession] notified with the replacement id
 */
async function withSession(sessionId, fn, onNewSession) {
  try {
    return await fn(sessionId);
  } catch (error) {
    if (!isMissingSession(error)) throw error;
    const fresh = await createSession();
    onNewSession?.(fresh);
    return fn(fresh);
  }
}

/** Pin the current frame as reference context for later questions. */
export async function addScreenshot(sessionId, imageBase64, onNewSession) {
  return withSession(
    sessionId,
    async (id) => {
      const { data } = await api.post("/screenshot/add", {
        session_id: id,
        image_base64: imageBase64,
      });
      return data;
    },
    onNewSession
  );
}

export async function clearContext(sessionId, onNewSession) {
  return withSession(
    sessionId,
    async (id) => {
      const { data } = await api.post(`/context/clear/${id}`);
      return data;
    },
    onNewSession
  );
}

/** Forget the voice conversation so far. */
export async function resetVoiceMemory(sessionId, onNewSession) {
  return withSession(
    sessionId,
    async (id) => {
      const { data } = await api.post(`/voice/reset/${id}`);
      return data;
    },
    onNewSession
  );
}

export async function checkHealth() {
  const { data } = await axios.get(`${API_ORIGIN}/health`, { timeout: 8000 });
  return data;
}

/**
 * Extract text from a PDF on the backend.
 * @returns {Promise<string>} the text
 * @throws {Error} with a user-facing message
 */
export async function parsePdf(file) {
  const formData = new FormData();
  formData.append("file", file);
  let response;
  try {
    response = await fetch(`${API_BASE}/parse-pdf`, {
      method: "POST",
      headers: await authHeaders(),
      body: formData,
    });
  } catch {
    throw new Error("Upload failed. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || describe(data.detail, response.status));
  }
  return data.text;
}

/**
 * Parse a chunk of an SSE byte stream.
 *
 * Events are separated by a blank line and a single event may span several
 * `data:` lines, which must be rejoined with newlines. Splitting on "\n" and
 * treating every line as a whole event — as the previous implementation did —
 * happens to work only while every payload stays on one line.
 *
 * @returns {{ events: object[], rest: string }} parsed events, plus the
 *   trailing partial frame to carry into the next read.
 */
export function parseSSE(buffer) {
  const events = [];
  // Normalise CRLF so a proxy that rewrites line endings cannot break framing.
  const normalised = buffer.replace(/\r\n/g, "\n");
  const frames = normalised.split("\n\n");
  const rest = frames.pop() ?? "";

  for (const frame of frames) {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");

    if (!data) continue;
    try {
      events.push(JSON.parse(data));
    } catch {
      // A malformed frame is not worth aborting a live answer over.
    }
  }

  return { events, rest };
}

/**
 * POST to a streaming endpoint and dispatch its SSE events.
 *
 * Handles the shared failure paths: an expired session is replaced and the
 * request replayed once, and a missing key is surfaced through onKeyRequired.
 *
 * @param {object} opts
 * @param {string} opts.path
 * @param {string} opts.sessionId
 * @param {(id: string) => {body: BodyInit, headers: object}} opts.buildRequest
 * @param {(event: object) => void} opts.onEvent
 * @param {string[]} opts.defaultNeeded  key fields to ask for on a bare 401
 * @returns {() => void} abort
 */
function streamRequest({
  path,
  sessionId,
  buildRequest,
  onEvent,
  onError,
  onNewSession,
  onKeyRequired,
  defaultNeeded,
}) {
  const controller = new AbortController();

  const run = async (id, isRetry = false) => {
    const { body, headers } = buildRequest(id);
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { ...(await authHeaders()), ...headers },
      body,
      signal: controller.signal,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail = payload?.detail;

      // Session expired (backend restart, or idle past the TTL): make a new
      // one and replay the request once.
      if (response.status === 404 && detail?.code === "session_not_found" && !isRetry) {
        const fresh = await createSession();
        onNewSession?.(fresh);
        return run(fresh, true);
      }

      // The backend has no key of its own and we sent none (or it was
      // rejected). Surface this as its own error so the caller can prompt.
      const keyError = asKeyError(detail, defaultNeeded);
      if (keyError && onKeyRequired) {
        onKeyRequired(keyError);
        return;
      }

      onError(describe(detail, response.status));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSSE(buffer);
      buffer = rest;

      for (const event of events) {
        if (event.type === "done" || event.type === "error") finished = true;
        // A rejected key is recoverable: let the caller re-prompt rather
        // than showing an error the user cannot act on.
        if (event.type === "error" && event.code === "invalid_api_key" && onKeyRequired) {
          onKeyRequired(
            new ApiKeyRequiredError(event.message, {
              needed: event.provider ? [`${event.provider}_key`] : defaultNeeded,
            })
          );
        } else if (event.type === "error") {
          onError(event.message || "Request failed");
        } else {
          onEvent(event);
        }
      }
    }

    // The stream closed without saying it was done: the connection dropped,
    // the server restarted, or a proxy timed out. Without this the UI would
    // sit on "Generating answer…" forever.
    if (!finished) onError("The connection was interrupted. Try again.");
  };

  // Set once a terminal event has been delivered, so a late network failure
  // cannot report an error for a request that already completed.
  let finished = false;

  run(sessionId).catch((err) => {
    if (err.name === "AbortError" || finished) return;
    finished = true;
    // fetch() rejects with a TypeError for network failures in every browser,
    // each with its own message ("Failed to fetch", "Load failed", ...).
    onError(err instanceof TypeError ? "Cannot reach the server." : err.message);
  });

  return () => controller.abort();
}

/**
 * Analyse the current screen, streaming the answer back as it is generated.
 *
 * @param {object} opts
 * @param {string} opts.sessionId
 * @param {string|null} opts.imageBase64
 * @param {string|null} opts.question
 * @param {object|null} opts.profile   { job_title, job_description, cv_text }
 * @param {() => void} [opts.onStart]  request accepted, before the first token
 * @param {(text: string) => void} opts.onToken
 * @param {(info: object) => void} opts.onDone
 * @param {(message: string) => void} opts.onError
 * @param {(id: string) => void} [opts.onNewSession]
 * @param {(err: ApiKeyRequiredError) => void} [opts.onKeyRequired]
 * @returns {() => void} abort — cancels the stream and the underlying request
 */
export function analyzeScreenStream({
  sessionId,
  imageBase64 = null,
  question = null,
  profile = null,
  onStart,
  onToken,
  onDone,
  onError,
  onNewSession,
  onKeyRequired,
}) {
  return streamRequest({
    path: "/analyze/stream",
    sessionId,
    defaultNeeded: ["openai_key"],
    buildRequest: (id) => ({
      headers: { "Content-Type": "application/json", ...keyHeaders() },
      body: JSON.stringify({
        session_id: id,
        image_base64: imageBase64,
        question,
        ...(profile ? { profile } : {}),
      }),
    }),
    onEvent: (event) => {
      if (event.type === "start") onStart?.();
      else if (event.type === "token") onToken(event.text);
      else if (event.type === "done") {
        onDone({
          context_count: event.context_count,
          context_tokens: event.context_tokens,
          usage: event.usage || null,
        });
      }
    },
    onError,
    onNewSession,
    onKeyRequired,
  });
}

const AUDIO_EXTENSIONS = { "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4" };

/**
 * Send one recorded question and stream back its transcript and answer.
 *
 * @param {object} opts
 * @param {string} opts.sessionId
 * @param {Blob} opts.audio
 * @param {object|null} opts.profile
 * @param {(text: string) => void} opts.onTranscription
 * @param {() => void} opts.onNoSpeech
 * @param {(text: string) => void} opts.onToken
 * @param {() => void} opts.onDone
 * @param {(message: string) => void} opts.onError
 * @param {string[]} opts.defaultNeeded
 * @returns {() => void} abort
 */
export function voiceAnswerStream({
  sessionId,
  audio,
  profile = null,
  onTranscription,
  onNoSpeech,
  onToken,
  onDone,
  onError,
  onNewSession,
  onKeyRequired,
  defaultNeeded = ["groq_key"],
}) {
  const baseType = (audio.type || "audio/webm").split(";")[0];
  const filename = `question.${AUDIO_EXTENSIONS[baseType] || "webm"}`;

  return streamRequest({
    path: "/voice/answer",
    sessionId,
    defaultNeeded,
    buildRequest: (id) => {
      const form = new FormData();
      form.append("session_id", id);
      form.append("audio", audio, filename);
      if (profile) form.append("profile", JSON.stringify(profile));
      // No Content-Type: the browser sets the multipart boundary itself.
      return { body: form, headers: voiceKeyHeaders() };
    },
    onEvent: (event) => {
      if (event.type === "transcription") onTranscription(event.text);
      else if (event.type === "no_speech") onNoSpeech();
      else if (event.type === "token") onToken(event.text);
      else if (event.type === "done") onDone();
    },
    onError,
    onNewSession,
    onKeyRequired,
  });
}
