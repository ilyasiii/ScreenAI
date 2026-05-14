import { supabase } from "../lib/supabase";

/** Save a completed analysis to history */
export async function saveAnalysis(userId, question, answer) {
  const { error } = await supabase
    .from("analysis_history")
    .insert({ user_id: userId, question: question || "Quick analyze", answer });
  if (error) console.error("Failed to save analysis:", error.message);
}

/** Increment today's API call count */
export async function trackUsage(userId) {
  const today = new Date().toISOString().slice(0, 10);

  // Try to increment existing row
  const { data } = await supabase
    .from("usage_tracking")
    .select("id, api_calls")
    .eq("user_id", userId)
    .eq("date", today)
    .single();

  if (data) {
    await supabase
      .from("usage_tracking")
      .update({ api_calls: data.api_calls + 1 })
      .eq("id", data.id);
  } else {
    await supabase
      .from("usage_tracking")
      .insert({ user_id: userId, date: today, api_calls: 1 });
  }
}

/** Fetch analysis history for the current user */
export async function getHistory(userId, limit = 50) {
  const { data, error } = await supabase
    .from("analysis_history")
    .select("id, question, answer, created_at")
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error("Failed to load history:", error.message);
    return [];
  }
  return data;
}

/** Get today's usage count */
export async function getTodayUsage(userId) {
  const today = new Date().toISOString().slice(0, 10);
  const { data } = await supabase
    .from("usage_tracking")
    .select("api_calls")
    .eq("user_id", userId)
    .eq("date", today)
    .single();
  return data?.api_calls ?? 0;
}
