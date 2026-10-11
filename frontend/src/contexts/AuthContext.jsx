import { useEffect, useRef, useState } from "react";

import { supabase } from "../lib/supabase";
import { AuthContext } from "./auth-context";
import { clearUserStorage } from "./storage-keys";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const skipAuthRef = useRef(false);

  useEffect(() => {
    // Tokens in the URL (email confirmation, OAuth, password reset) are read
    // and then cleared from the address bar by supabase-js itself
    // (detectSessionInUrl). Stripping them here as well raced that read and
    // could sign the user out of a link they had just clicked.

    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!skipAuthRef.current) setUser(session?.user ?? null);
      setLoading(false);
    });

    // Listen for auth changes (login, logout, token refresh)
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      // Covers sign-out from another tab and server-side session revocation,
      // not just the button: personal data must not outlive the session.
      if (event === "SIGNED_OUT") clearUserStorage();
      if (!skipAuthRef.current) setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  const signUp = async (email, password, name) => {
    skipAuthRef.current = true;
    try {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: { full_name: name },
          emailRedirectTo: window.location.origin + "/auth",
        },
      });
      if (error) throw error;
      if (!data.session) {
        // Email confirmation required — no session created
      } else {
        await supabase.auth.signOut();
      }
      return data;
    } finally {
      skipAuthRef.current = false;
    }
  };

  const signIn = async (email, password) => {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) throw error;
    return data;
  };

  const signInWithGoogle = async () => {
    const { data, error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin + "/app" },
    });
    if (error) throw error;
    return data;
  };

  const signOut = async () => {
    // Cleared first, so a failed network call cannot leave the CV and API
    // keys behind on a shared computer.
    clearUserStorage();
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
  };

  const resetPassword = async (email) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin + "/reset-password",
    });
    if (error) throw error;
  };

  const updatePassword = async (newPassword) => {
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) throw error;
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, signUp, signIn, signInWithGoogle, signOut, resetPassword, updatePassword }}
    >
      {children}
    </AuthContext.Provider>
  );
}
