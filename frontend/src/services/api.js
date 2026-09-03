/**
 * Backend client.
 *
 * Two things worth knowing:
 *
 * 1. Sessions self-heal. The backend 404s unknown session IDs instead of
 *    silently minting one, so this module catches `session_not_found`, creates
 *    a fresh session and retries once. A backend restart mid-session is now
 *    invisible to the user rather than a wall of failed requests.
 *
 * 2. Streaming goes through fetch, not EventSource, because the request is a
 *    POST with a JSON body. The SSE framing is parsed by hand below.
 */
import axios from "axios";

import { API_BASE, API_ORIGIN } from "../config";
import { getOpenAIKey } from "./credentials";

/** Error thrown when the backend has no key and the user has not supplied one. */
export class ApiKeyRequiredError extends Error {
  constructor(message, { refused = false } = {}) {
    super(message || "An API key is required.");
    this.name = "ApiKeyRequiredError";
    // `refused` means the operator has disabled client-supplied keys, so
    // prompting the user would achieve nothing.
    this.refused = refused;
  }
}

/**
 * Headers carrying the user's key, when they have entered one.
 *
 * A header rather than the JSON body: it stays out of request-body logs, and
 * the backend never persists it alongside session state.
 */
function keyHeaders() {
  const key = getOpenAIKey();
  return key ? { "X-OpenAI-Api-Key": key } : {};
}

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  headers: { "Content-Type": "application/json" },
});

/** True when a failure means "the session is gone, make a new one". */
function isMissingSession(error) {
  const detail = error?.response?.data?.detail;
  return error?.response?.status === 404 && detail?.code === "session_not_found";
}

/** Convert a 401 from the backend into a typed error the UI can act on. */
function asKeyError(detail) {
  if (detail?.code === "api_key_required") {
    return new ApiKeyRequiredError(detail.message);
  }
  if (detail?.code === "api_key_refused") {
    return new ApiKeyRequiredError(detail.message, { refused: true });
  }
  return null;
}

export async function createSession() {
  const { data } = await api.post("/session/create");
  return data.session_id;
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

export async function checkHealth() {
  const { data } = await axios.get(`${API_ORIGIN}/health`, { timeout: 5000 });
  return data;
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
  const controller = new AbortController();

  const run = async (id, isRetry = false) => {
    const response = await fetch(`${API_BASE}/analyze/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...keyHeaders() },
      body: JSON.stringify({
        session_id: id,
        image_base64: imageBase64,
        question,
        ...(profile ? { profile } : {}),
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const detail = body?.detail;

      // Session expired (backend restart, or idle past the TTL): make a new
      // one and replay the request once.
      if (response.status === 404 && detail?.code === "session_not_found" && !isRetry) {
        const fresh = await createSession();
        onNewSession?.(fresh);
        return run(fresh, true);
      }

      // The backend has no key of its own and we sent none (or it was
      // rejected). Surface this as its own error so the caller can prompt.
      const keyError = asKeyError(detail);
      if (keyError) {
        onKeyRequired?.(keyError);
        return;
      }

      onError(
        typeof detail === "string"
          ? detail
          : detail?.message || `Request failed (${response.status})`
      );
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
        switch (event.type) {
          case "start":
            onStart?.();
            break;
          case "token":
            onToken(event.text);
            break;
          case "done":
            onDone({
              context_count: event.context_count,
              context_tokens: event.context_tokens,
              usage: event.usage || null,
            });
            break;
          case "error":
            // A rejected key is recoverable: let the caller re-prompt rather
            // than showing an error the user cannot act on.
            if (event.code === "invalid_api_key" && onKeyRequired) {
              onKeyRequired(new ApiKeyRequiredError(event.message));
            } else {
              onError(event.message || "Analysis failed");
            }
            break;
          default:
            break;
        }
      }
    }
  };

  run(sessionId).catch((err) => {
    if (err.name === "AbortError") return;
    onError(err.message || "Stream failed");
  });

  return () => controller.abort();
}
