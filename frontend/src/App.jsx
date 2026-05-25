/**
 * Screen Reader AI - Main App
 * 
 * A screen-reading AI assistant that captures your screen,
 * maintains context across multiple screenshots, and uses
 * GPT-4.1 Vision to answer any questions visible on screen.
 */
import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { useProfile } from "./contexts/ProfileContext";
import { useScreenCapture } from "./hooks/useScreenCapture";
import {
  createSession,
  addScreenshot,
  analyzeScreenStream,
  clearContext,
  checkHealth,
} from "./services/api";
import { saveAnalysis, trackUsage, getTodayUsage } from "./services/supabaseService";
import ScreenPreview from "./components/ScreenPreview";
import AnswerPanel from "./components/AnswerPanel";
import QuestionInput from "./components/QuestionInput";
import ProfileModal from "./components/ProfileModal";
import "./App.css";

function App() {
  // Auth
  const { user, signOut } = useAuth();
  const { profile } = useProfile();
  const navigate = useNavigate();

  // Session state
  const [sessionId, setSessionId] = useState(null);
  const [contextCount, setContextCount] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [answers, setAnswers] = useState([]);
  const [todayUsage, setTodayUsage] = useState(0);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Screen capture hook
  const {
    isSharing,
    error: captureError,
    startCapture,
    stopCapture,
    captureFrame,
    videoRef,
    canvasRef,
  } = useScreenCapture();

  // ─── Close user menu on click outside ────────────────────────────────
  useEffect(() => {
    if (!showUserMenu) return;
    const handleClick = (e) => {
      if (!e.target.closest(".user-menu-wrapper")) setShowUserMenu(false);
    };
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [showUserMenu]);

  // ─── Initialize session on mount ─────────────────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const health = await checkHealth();
        if (!health.openai_configured) return;

        const sid = await createSession();
        setSessionId(sid);

        if (user?.id) {
          getTodayUsage(user.id).then(setTodayUsage);
        }
      } catch (err) {
        console.error("Backend connection failed:", err);
      }
    }
    init();
  }, []);

  // ─── Handle starting screen capture ──────────────────────────────────
  const handleStartCapture = useCallback(async () => {
    const ok = await startCapture();
    if (ok && !sessionId) {
      try {
        const sid = await createSession();
        setSessionId(sid);
      } catch (err) {
        console.error("Failed to create session:", err);
      }
    }
  }, [startCapture, sessionId]);

  // ─── Handle stopping capture ─────────────────────────────────────────
  // (stopCapture from hook is passed directly to ScreenPreview)

  // ─── Capture frame and add to context (for multi-screen questions) ───
  const handleCaptureContext = useCallback(async () => {
    if (!sessionId) return;

    const frame = captureFrame();
    if (!frame) return;

    try {
      const result = await addScreenshot(sessionId, frame);
      setContextCount(result.context_count);
    } catch (err) {
      console.error("Failed to add screenshot:", err);
    }
  }, [sessionId, captureFrame]);

  // ─── Capture current screen + analyze with streaming ──────────────────
  const handleAnalyze = useCallback(
    async (question = null) => {
      if (!sessionId || isAnalyzing) return;

      setIsAnalyzing(true);

      const frame = captureFrame();
      if (!frame) {
        setIsAnalyzing(false);
        return;
      }

      // Create a live answer entry that updates as tokens stream in
      const liveAnswer = {
        answer: "",
        question: question,
        timestamp: new Date().toLocaleTimeString(),
        streaming: true,
      };
      setAnswers((prev) => [liveAnswer, ...prev]);

      analyzeScreenStream(
        sessionId,
        frame,
        question,
        // onToken — append each token to the live answer
        (token) => {
          liveAnswer.answer += token;
          setAnswers((prev) => {
            const updated = [...prev];
            updated[0] = { ...liveAnswer };
            return updated;
          });
        },
        // onDone
        (info) => {
          liveAnswer.streaming = false;
          setContextCount(info.context_count);
          setAnswers((prev) => {
            const updated = [...prev];
            updated[0] = { ...liveAnswer };
            return updated;
          });
          setIsAnalyzing(false);

          // Save to Supabase (fire-and-forget)
          if (user?.id) {
            saveAnalysis(user.id, question, liveAnswer.answer);
            trackUsage(user.id);
            setTodayUsage((n) => n + 1);
          }
        },
        // onError
        (errMsg) => {
          liveAnswer.streaming = false;
          liveAnswer.answer = liveAnswer.answer || `Error: ${errMsg}`;
          setAnswers((prev) => {
            const updated = [...prev];
            updated[0] = { ...liveAnswer };
            return updated;
          });
          setIsAnalyzing(false);
        },
        profile
      );
    },
    [sessionId, isAnalyzing, captureFrame, user, profile]
  );

  // ─── Handle clear context ────────────────────────────────────────────
  const handleClearContext = useCallback(async () => {
    if (!sessionId) return;
    try {
      await clearContext(sessionId);
      setContextCount(0);

    } catch (err) {
      console.error("Failed to clear context:", err);
    }
  }, [sessionId]);

  return (
    <div className="app">
      {/* Hidden canvas for frame capture */}
      <canvas ref={canvasRef} style={{ display: "none" }} />

      {/* Header */}
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
            <button className="header-btn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
              {todayUsage} Today
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
                <div className="user-avatar">
                  {(user.user_metadata?.full_name ? user.user_metadata.full_name.split(" ").map(n => n[0]).join("").slice(0, 2) : user.email?.slice(0, 2) || "U").toUpperCase()}
                </div>
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
                    onClick={async () => { setShowUserMenu(false); await signOut(); navigate("/"); }}
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

      {/* Question Input */}
      <div className="question-bar">
        <QuestionInput
          onSubmit={handleAnalyze}
          isAnalyzing={isAnalyzing}
          isSharing={isSharing}
        />
      </div>

      {/* Main Content */}
      <main className="app-main">
        {/* Left Panel - Screen Capture */}
        <section className="panel panel-left">
          <ScreenPreview
            isSharing={isSharing}
            onStartCapture={handleStartCapture}
            onStopCapture={stopCapture}
            onCaptureAndAnalyze={() => handleAnalyze(null)}
            onCaptureContext={handleCaptureContext}
            onClearContext={handleClearContext}
            videoRef={videoRef}
            error={captureError}
            contextCount={contextCount}
            isAnalyzing={isAnalyzing}
          />
        </section>

        {/* Right Panel - AI Answers */}
        <section className="panel panel-right">
          <AnswerPanel answers={answers} isAnalyzing={isAnalyzing} />
        </section>
      </main>

      {showProfileModal && <ProfileModal onClose={() => setShowProfileModal(false)} />}
    </div>
  );
}

export default App;
