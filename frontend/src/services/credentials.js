/**
 * User-supplied API keys.
 *
 * Only used when the backend reports it has no key of its own. The server's key
 * always wins, so entering one here can never redirect somebody else's billing.
 *
 * Storage is sessionStorage, deliberately:
 *   - it is cleared when the tab closes, so a key does not sit on a shared
 *     machine indefinitely the way a localStorage value would;
 *   - it is per-tab, so signing out in one tab cannot strand a key in another.
 *
 * This is still browser storage, and any script running on the page can read
 * it. That is an acceptable trade for a locally-run tool where the alternative
 * is not running at all — it is not a substitute for a server-side key in a
 * deployment.
 */

const STORAGE_KEY = "screenai_api_keys";

/** @typedef {{ openai_key?: string, groq_key?: string, anthropic_key?: string }} Credentials */

/** @returns {Credentials} */
export function loadCredentials() {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

/** Merge in new keys, dropping any that are blank. */
export function saveCredentials(partial) {
  const merged = { ...loadCredentials(), ...partial };
  for (const [name, value] of Object.entries(merged)) {
    if (!value || !value.trim()) delete merged[name];
    else merged[name] = value.trim();
  }

  try {
    if (Object.keys(merged).length === 0) sessionStorage.removeItem(STORAGE_KEY);
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // Private browsing with storage disabled. The key still works for this
    // page load; it just will not survive a reload.
  }
  return merged;
}

export function clearCredentials() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do.
  }
}

/** The OpenAI key, if the user has entered one. */
export function getOpenAIKey() {
  return loadCredentials().openai_key || "";
}

/**
 * Reject obvious paste errors before spending a round trip on them. Deliberately
 * loose: OpenAI has shipped several key prefixes and Groq another, and a format
 * check that is too strict ages badly.
 */
export function looksLikeKey(value) {
  const key = (value || "").trim();
  return key.length >= 20 && !/\s/.test(key);
}
