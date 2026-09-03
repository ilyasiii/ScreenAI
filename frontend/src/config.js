/**
 * Runtime configuration.
 *
 * Everything environment-specific is read from Vite env vars so the same build
 * can point at a different backend without a code change. Defaults keep the
 * local dev flow working with no .env file at all.
 */

const rawApiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

/** Backend origin, no trailing slash. */
export const API_ORIGIN = rawApiUrl.replace(/\/+$/, "");

/** REST base. */
export const API_BASE = `${API_ORIGIN}/api`;

/** Voice WebSocket, derived from the API origin so the two cannot drift. */
export const WS_URL = `${API_ORIGIN.replace(/^http/, "ws")}/ws/voice`;

export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";
export const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || "";

/**
 * Whether Supabase is usable. Checked before the app renders, because
 * createClient() throws on a missing URL or key - and thrown at module scope
 * that kills the whole bundle before React mounts, which shows up as a blank
 * white page with no clue as to why.
 */
export const SUPABASE_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

/**
 * Screenshot capture size.
 *
 * The vision API rescales every high-detail image so its short side is 768px,
 * then bills by 512px tile. Capturing at exactly that size means:
 *   - no information is thrown away by a downscale we did not choose,
 *   - no bandwidth is spent on pixels the model will discard,
 *   - the backend's resize becomes a no-op.
 */
export const CAPTURE_SHORT_SIDE = 768;
export const CAPTURE_MAX_LONG_SIDE = 2048;

/** Client-side daily analysis cap. Advisory only — the backend does not enforce it. */
export const DAILY_ANALYSIS_LIMIT = Number(import.meta.env.VITE_DAILY_LIMIT || 0) || null;
