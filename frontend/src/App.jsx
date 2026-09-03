/**
 * ScreenAI — screen analysis workspace.
 *
 * Streaming note: tokens arrive faster than the browser can usefully paint, and
 * every re-render re-parses the whole markdown answer. So tokens accumulate in
 * a ref and are flushed to state once per animation frame. Each answer also
 * carries a stable id, which lets the answer cards memoise — without it, a
 * prepended answer shifts every index and React re-renders the entire history
 * on every single token.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import AnswerPanel from "./components/AnswerPanel";
import ApiKeyModal from "./components/ApiKeyModal";
import ProfileModal from "./components/ProfileModal";
import QuestionInput from "./components/QuestionInput";
import ScreenPreview from "./components/ScreenPreview";
import { useAuth } from "./contexts/auth-context";
import { useProfile } from "./contexts/profile-context";
import { useScreenCapture } from "./hooks/useScreenCapture";
import {
  addScreenshot,
  analyzeScreenStream,
  checkHealth,
  clearContext,
  createSession,
} from "./services/api";
import { clearCredentials, getOpenAIKey } from "./services/credentials";
import { getTodayUsage, saveAnalysis, trackUsage } from "./services/supabaseService";
import "./App.css";

let answerSeq = 0;
const nextAnswerId = () => `a${Date.now().toString(36)}-${answerSeq++}`;

function App() {
  const { user, signOut } = useAuth();
  const { profile } = useProfile();
  const userId = user?.id;
  const navigate = useNavigate();

  const [sessionId, setSessionId] = useState(null);
  const [contextCount, setContextCount] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [answers, setAnswers] = useState([]);
  const [todayUsage, setTodayUsage] = useState(0);
  const [backendError, setBackendError] = useState(null);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // What the backend told us at /health about its own credentials.
  const [backendKeys, setBackendKeys] = useState(null);
  // Non-null while the key prompt is open: { needed: string[], error?: string }.
  const [keyPrompt, setKeyPrompt] = useState(null);

  const {
    isSharing,
    error: captureError,
    startCapture,
    stopCapture,
    captureFrame,
    videoRef,
    canvasRef,
  } = useScreenCapture();

  // ─── Streaming plumbing ──────────────────────────────────────────────
  const abortRef = useRef(null);
  const bufferRef = useRef("");
  const activeIdRef = useRef(null);
  const frameRef = useRef(0);
  const sessionIdRef = useRef(null);
  const initRef = useRef(false);
  // The question to replay once the user has entered a key.
  const pendingQuestionRef = useRef(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const flush = useCallback(() => {
    frameRef.current = 0;
    const id = activeIdRef.current;
    if (!id) return;
    const text = bufferRef.current;
    setAnswers((prev) =>
      prev.map((item) => (item.id === id ? { ...item, answer: text } : item))
    );
  }, []);

  const scheduleFlush = useCallback(() => {
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(flush);
  }, [flush]);

  const endStream = useCallback(() => {
    if (frameRef.current) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
    }
    abortRef.current = null;
    activeIdRef.current = null;
    setIsAnalyzing(false);
  }, []);

  // Abort any in-flight stream on unmount, so navigating away mid-answer does
  // not leave a fetch running and calling setState into a dead component.
  useEffect(
    () => () => {
      abortRef.current?.();
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    },
    []
  );

  // ─── Close the user menu on an outside click ─────────────────────────
  useEffect(() => {
    if (!showUserMenu) return;
    const handleClick = (e) => {
      if (!e.target.closest(".user-menu-wrapper")) setShowUserMenu(false);
    };
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [showUserMenu]);

  // ─── Boot ────────────────────────────────────────────────────────────
  useEffect(() => {
    // StrictMode mounts effects twice in development; without this guard that
    // means two backend sessions per page load, one of them orphaned.
    if (initRef.current) return;
    initRef.current = true;

    (async () => {
      try {
        const health = await checkHealth();
        setBackendKeys(health);

        // A missing server key is not fatal: if the server accepts keys from
        // the browser, the user is asked for one when they first analyse.
        if (!health.openai_configured && !health.allows_client_keys) {
          setBackendError(
            "This backend has no OpenAI key and does not accept one from the browser."
          );
          return;
        }
        setSessionId(await createSession());
      } catch {
        setBackendError("Cannot reach the backend. Is it running on port 8000?");
      }
    })();
  }, []);

  useEffect(() => {
    if (userId) getTodayUsage(userId).then(setTodayUsage);
  }, [userId]);

  // ─── Actions ─────────────────────────────────────────────────────────
  const handleStartCapture = useCallback(async () => {
    const ok = await startCapture();
    if (ok && !sessionIdRef.current) {
      try {
        setSessionId(await createSession());
      } catch {
        setBackendError("Cannot reach the backend. Is it running on port 8000?");
      }
    }
  }, [startCapture]);

  const handleCaptureContext = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;

    const frame = captureFrame();
    if (!frame) return;

    try {
      const result = await addScreenshot(id, frame, setSessionId);
      setContextCount(result.context_count);
      if (!result.added && result.reason === "duplicate") {
        setBackendError("That screen is already pinned as context.");
        setTimeout(() => setBackendError(null), 2500);
      }
    } catch (err) {
      console.error("Failed to pin screenshot:", err);
    }
  }, [captureFrame]);

  /** True when the server has no key of its own and the user has not given one. */
  const needsApiKey = useCallback(
    () => Boolean(backendKeys && !backendKeys.openai_configured && !getOpenAIKey()),
    [backendKeys]
  );

  const handleAnalyze = useCallback(
    (question = null) => {
      const id = sessionIdRef.current;
      if (!id || isAnalyzing) return;

      // Ask for the key before capturing anything, so the user is not left
      // looking at an empty answer card while a modal is open.
      if (needsApiKey()) {
        pendingQuestionRef.current = question;
        setKeyPrompt({ needed: ["openai_key"] });
        return;
      }

      const frame = captureFrame();
      if (!frame) {
        setBackendError("No frame available yet — is the screen still shared?");
        return;
      }

      const answerId = nextAnswerId();
      activeIdRef.current = answerId;
      bufferRef.current = "";
      setIsAnalyzing(true);
      setBackendError(null);
      setAnswers((prev) => [
        {
          id: answerId,
          question,
          answer: "",
          timestamp: new Date().toLocaleTimeString(),
          streaming: true,
        },
        ...prev,
      ]);

      const finalise = (patch) => {
        const text = bufferRef.current;
        setAnswers((prev) =>
          prev.map((item) =>
            item.id === answerId ? { ...item, answer: text, streaming: false, ...patch } : item
          )
        );
      };

      abortRef.current = analyzeScreenStream({
        sessionId: id,
        imageBase64: frame,
        question,
        profile,
        onNewSession: setSessionId,
        onToken: (token) => {
          bufferRef.current += token;
          scheduleFlush();
        },
        onDone: (info) => {
          setContextCount(info.context_count);
          finalise({ usage: info.usage });
          endStream();

          const answer = bufferRef.current;
          if (userId && answer.trim()) {
            saveAnalysis(userId, question, answer);
            trackUsage(userId).then((total) => {
              if (typeof total === "number") setTodayUsage(total);
            });
          }
        },
        onError: (message) => {
          finalise({ answer: bufferRef.current || `Error: ${message}`, error: message });
          endStream();
        },
        onKeyRequired: (err) => {
          // Drop the placeholder card — the request never reached the model,
          // so leaving an empty answer behind would just be confusing.
          setAnswers((prev) => prev.filter((item) => item.id !== answerId));
          endStream();

          if (err.refused) {
            setBackendError(err.message);
            return;
          }
          pendingQuestionRef.current = question;
          setKeyPrompt({ needed: ["openai_key"], error: err.message });
        },
      });
    },
    [isAnalyzing, captureFrame, profile, userId, scheduleFlush, endStream, needsApiKey]
  );

  const handleKeySaved = useCallback(() => {
    setKeyPrompt(null);
    setBackendError(null);
    const question = pendingQuestionRef.current;
    pendingQuestionRef.current = null;
    // Replay whatever the user was trying to do when we interrupted them.
    handleAnalyze(question);
  }, [handleAnalyze]);

  const handleKeyCancelled = useCallback(() => {
    setKeyPrompt(null);
    pendingQuestionRef.current = null;
  }, []);

  const handleStopAnalyze = useCallback(() => {
    abortRef.current?.();
    const id = activeIdRef.current;
    const text = bufferRef.current;
    if (id) {
      setAnswers((prev) =>
        prev.map((item) =>
          item.id === id
            ? { ...item, answer: text || "_Stopped._", streaming: false, stopped: true }
            : item
        )
      );
    }
    endStream();
  }, [endStream]);

  const handleClearContext = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    try {
      await clearContext(id, setSessionId);
      setContextCount(0);
    } catch (err) {
      console.error("Failed to clear context:", err);
    }
  }, []);

  const initials = user?.user_metadata?.full_name
    ? user.user_metadata.full_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : (user?.email?.slice(0, 2) || "U").toUpperCase();

  return (
    <div className="app">
      <canvas ref={canvasRef} style={{ display: "none" }} />

      <header className="app-header">
        <div className="header-left">
          <Link to="/" className="app-logo">
            <div className="logo-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <span className="logo-text">ScreenAI</span>
          </Link>
          <nav className="header-nav">
            <Link to="/app" className="nav-tab active">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
              Home
            </Link>
            <Link to="/interview" className="nav-tab">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
              Interview
            </Link>
            <Link to="/history" className="nav-tab">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/></svg>
              History
            </Link>
          </nav>
        </div>
        <div className="header-right">
          {todayUsage > 0 && (
            <button className="header-btn" title="Analyses run today">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
              {todayUsage} Today
            </button>
          )}
          {backendKeys && !backendKeys.openai_configured && (
            <button
              className="header-btn"
              onClick={() => setKeyPrompt({ needed: ["openai_key"] })}
              title={getOpenAIKey() ? "Replace your API key" : "Add your API key"}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
              {getOpenAIKey() ? "API key" : "Add key"}
            </button>
          )}
          <button
            className="header-btn primary"
            onClick={() => setShowProfileModal(true)}
            title="Update interview data"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            Interview Data
          </button>
          {user && (
            <div className="user-menu-wrapper">
              <div className="user-menu" onClick={() => setShowUserMenu(!showUserMenu)}>
                <div className="user-avatar">{initials}</div>
                <div className="user-info">
                  <span className="user-name">{user.user_metadata?.full_name || user.email?.split("@")[0] || "User"}</span>
                  <span className="user-email">{user.email}</span>
                </div>
                <svg className="dropdown-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
              </div>
              {showUserMenu && (
                <div className="user-dropdown">
                  <button
                    className="dropdown-item"
                    onClick={async () => {
                      setShowUserMenu(false);
                      // The key belongs to the person who typed it, not to the
                      // next person to use this browser.
                      clearCredentials();
                      await signOut();
                      navigate("/");
                    }}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    Sign out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      <div className="question-bar">
        <QuestionInput onSubmit={handleAnalyze} isAnalyzing={isAnalyzing} isSharing={isSharing} />
      </div>

      <main className="app-main">
        <section className="panel panel-left">
          <ScreenPreview
            isSharing={isSharing}
            onStartCapture={handleStartCapture}
            onStopCapture={stopCapture}
            onCaptureAndAnalyze={() => handleAnalyze(null)}
            onCaptureContext={handleCaptureContext}
            onClearContext={handleClearContext}
            onStopAnalyze={handleStopAnalyze}
            videoRef={videoRef}
            error={captureError || backendError}
            contextCount={contextCount}
            isAnalyzing={isAnalyzing}
          />
        </section>

        <section className="panel panel-right">
          <AnswerPanel answers={answers} isAnalyzing={isAnalyzing} />
        </section>
      </main>

      {showProfileModal && <ProfileModal onClose={() => setShowProfileModal(false)} />}

      {keyPrompt && (
        <ApiKeyModal
          needed={keyPrompt.needed}
          error={keyPrompt.error}
          onSaved={handleKeySaved}
          onCancel={handleKeyCancelled}
        />
      )}
    </div>
  );
}

export default App;
