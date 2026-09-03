import { createClient } from "@supabase/supabase-js";

import { SUPABASE_ANON_KEY, SUPABASE_CONFIGURED, SUPABASE_URL } from "../config";

/*
 * Credentials come from VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY in
 * frontend/.env.local.
 *
 * The anon key is compiled into the bundle and is public by design — Row Level
 * Security is what actually protects the data. Every table must have RLS
 * enabled with a policy restricting rows to `auth.uid() = user_id`, or any
 * visitor can read and write every row in it.
 *
 * When configuration is missing we build the client against placeholders rather
 * than letting createClient throw. A throw here happens at module scope, before
 * React mounts, and takes the entire page down to a blank white screen with the
 * real cause buried in the console. The app checks SUPABASE_CONFIGURED and
 * renders setup instructions instead, so this client is never actually used in
 * that state.
 */
export const supabase = createClient(
  SUPABASE_CONFIGURED ? SUPABASE_URL : "https://placeholder.supabase.co",
  SUPABASE_CONFIGURED ? SUPABASE_ANON_KEY : "placeholder-anon-key",
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  }
);
