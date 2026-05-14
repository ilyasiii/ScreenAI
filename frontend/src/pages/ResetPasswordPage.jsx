import { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { supabase } from "../lib/supabase";
import "./AuthPage.css";

const EyeIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
  </svg>
);
const EyeOffIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
    <line x1="1" y1="1" x2="23" y2="23" />
    <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
  </svg>
);

export default function ResetPasswordPage() {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);

  const passwordRef = useRef(null);
  const confirmRef = useRef(null);
  const navigate = useNavigate();

  // Exchange the code for a session before showing the form
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");

    if (code) {
      supabase.auth.exchangeCodeForSession(code).then(({ error }) => {
        if (error) {
          setError("Reset link expired or invalid. Please request a new one.");
        } else {
          setSessionReady(true);
          window.history.replaceState(null, "", window.location.pathname);
        }
      });
    } else {
      // No code — check if there's already a session (e.g. from hash tokens)
      supabase.auth.getSession().then(({ data: { session } }) => {
        if (session) {
          setSessionReady(true);
        } else {
          setError("No valid reset session. Please request a new password reset link.");
        }
      });
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    const password = passwordRef.current.value;
    const confirm = confirmRef.current.value;

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      await supabase.auth.signOut();
      navigate("/auth");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <Link to="/" className="auth-logo">
          <div className="auth-logo-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          </div>
          <span>ScreenAI</span>
        </Link>

        <h1 className="auth-title">Set new password</h1>
        <p className="auth-subtitle">Enter your new password below</p>

        {!sessionReady && !error && (
          <p className="auth-subtitle">Verifying reset link...</p>
        )}

        {sessionReady && (
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-field">
            <label htmlFor="newPassword">New Password</label>
            <div className="password-wrapper">
              <input
                id="newPassword"
                ref={passwordRef}
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                required
                minLength={6}
              />
              <button
                type="button"
                className="btn-eye"
                onClick={() => setShowPassword((v) => !v)}
                tabIndex={-1}
              >
                {showPassword ? EyeOffIcon : EyeIcon}
              </button>
            </div>
          </div>

          <div className="form-field">
            <label htmlFor="confirmNewPassword">Confirm Password</label>
            <div className="password-wrapper">
              <input
                id="confirmNewPassword"
                ref={confirmRef}
                type={showConfirm ? "text" : "password"}
                placeholder="••••••••"
                required
                minLength={6}
              />
              <button
                type="button"
                className="btn-eye"
                onClick={() => setShowConfirm((v) => !v)}
                tabIndex={-1}
              >
                {showConfirm ? EyeOffIcon : EyeIcon}
              </button>
            </div>
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn-auth-submit" type="submit" disabled={loading}>
            {loading ? "Updating..." : "Update Password"}
          </button>
        </form>
        )}

        {error && !sessionReady && <div className="auth-error">{error}</div>}

        <p className="auth-switch">
          <Link to="/auth">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
