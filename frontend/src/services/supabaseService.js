import { supabase } from "../lib/supabase";

/**
 * Today's date in the *user's* timezone.
 *
 * `toISOString().slice(0, 10)` returns the UTC date, so a user in UTC+5 saw
 * their daily count reset in the middle of the afternoon.
 */
function localDateKey(date = new Date()) {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
}

/** Save a completed analysis to history. Fire-and-forget. */
export async function saveAnalysis(userId, question, answer) {
  const { error } = await supabase
    .from("analysis_history")
    .insert({ user_id: userId, question: question || "Quick analyze", answer });
  if (error) console.error("Failed to save analysis:", error.message);
}

/**
 * Increment today's API call count.
 *
 * Prefers the `increment_usage` RPC, which does the whole thing in one atomic
 * statement. The previous select-then-update lost increments whenever two
 * analyses finished close together. The fallback keeps working on a database
 * where the function has not been created yet — see the README for the SQL.
 *
 * @returns {Promise<number|null>} the new total, when known
 */
export async function trackUsage(userId) {
  const today = localDateKey();

  const { data, error } = await supabase.rpc("increment_usage", {
    p_user_id: userId,
    p_date: today,
  });

  if (!error) return typeof data === "number" ? data : null;

  // The RPC is missing (or not yet granted). Fall back to the read-modify-write
  // path, which is racy but better than losing the count entirely.
  const { data: row } = await supabase
    .from("usage_tracking")
    .select("id, api_calls")
    .eq("user_id", userId)
    .eq("date", today)
    .maybeSingle();

  if (row) {
    const next = row.api_calls + 1;
    await supabase.from("usage_tracking").update({ api_calls: next }).eq("id", row.id);
    return next;
  }

  await supabase.from("usage_tracking").insert({ user_id: userId, date: today, api_calls: 1 });
  return 1;
}

/** Analysis history, most recent first. */
export async function getHistory(userId, limit = 30) {
  const { data, error } = await supabase
    .from("analysis_history")
    .select("id, question, answer, created_at")
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) console.error("Failed to get history:", error.message);
  return data || [];
}

/** Today's analysis count. */
export async function getTodayUsage(userId) {
  // maybeSingle, not single: single() throws PGRST116 on the very common
  // "no row for today yet" path.
  const { data } = await supabase
    .from("usage_tracking")
    .select("api_calls")
    .eq("user_id", userId)
    .eq("date", localDateKey())
    .maybeSingle();
  return data?.api_calls || 0;
}
