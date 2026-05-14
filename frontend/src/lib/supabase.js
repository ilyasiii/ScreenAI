import { createClient } from "@supabase/supabase-js";

const supabaseUrl = "https://hsxbtxmobtzwibmaxswg.supabase.co";
const supabaseAnonKey =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhzeGJ0eG1vYnR6d2libWF4c3dnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU5MDU2NDMsImV4cCI6MjA5MTQ4MTY0M30.ApKQynAh_UN9QYslH_R_ozKQdlzQkg8KtDPm08zY7vU";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
