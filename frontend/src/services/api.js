/**
 * API Service - handles all backend communication
 */
import axios from "axios";

const API_BASE = "http://localhost:8000/api";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000, // 2 min timeout for AI analysis
  headers: { "Content-Type": "application/json" },
});

/**
 * Create a new session
 */
export async function createSession() {
  const { data } = await api.post("/session/create");
  return data.session_id;
}

/**
 * Add a screenshot to the session context
 */
export async function addScreenshot(sessionId, imageBase64) {
  const { data } = await api.post("/screenshot/add", {
    session_id: sessionId,
    image_base64: imageBase64,
  });
  return data;
}

/**
 * Analyze current screen with SSE streaming — tokens arrive in real-time
 * @param {string} sessionId
 * @param {string|null} imageBase64
 * @param {string|null} question
 * @param {function} onToken - called with each text chunk as it arrives
 * @param {function} onDone - called with {context_count} when stream ends
 * @param {function} onError - called with error message
 * @param {object|null} profile - optional profile { job_title, job_description, cv_text }
 * @returns {function} abort — call to cancel the stream
 */
export function analyzeScreenStream(sessionId, imageBase64 = null, question = null, onToken, onDone, onError, profile = null) {
  const controller = new AbortController();

  (async () => {
    try {
      const body = {
        session_id: sessionId,
        image_base64: imageBase64,
        question: question,
      };
      if (profile) body.profile = profile;

      const res = await fetch(`${API_BASE}/analyze/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        onError(err.detail || "Request failed");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) {
                onToken(data.token);
              } else if (data.done) {
                onDone({ context_count: data.context_count, usage: data.usage || null });
              } else if (data.error) {
                onError(data.error);
              }
            } catch {
              // skip malformed lines
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        onError(err.message || "Stream failed");
      }
    }
  })();

  return () => controller.abort();
}

/**
 * Clear all context for a session
 */
export async function clearContext(sessionId) {
  const { data } = await api.post(`/context/clear/${sessionId}`);
  return data;
}

/**
 * Check backend health
 */
export async function checkHealth() {
  const { data } = await axios.get("http://localhost:8000/health");
  return data;
}
