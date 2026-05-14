/**
 * Screen Reader AI - Main App
 * 
 * A screen-reading AI assistant that captures your screen,
 * maintains context across multiple screenshots, and uses
 * GPT-4o Vision to answer any questions visible on screen.
 */
import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { useScreenCapture } from "./hooks/useScreenCapture";
import {
  createSession,
  addScreenshot,
  analyzeScreenStream,
  clearContext,
  checkHealth,
} from "./services/api";
import { saveAnalysis, trackUsage } from "./services/supabaseService";
import ScreenPreview from "./components/ScreenPreview";
import AnswerPanel from "./components/AnswerPanel";
import QuestionInput from "./components/QuestionInput";
import "./App.css";

function App() {
  // Auth
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  // Session state
  const [sessionId, setSessionId] = useState(null);
  const [contextCount, setContextCount] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [answers, setAnswers] = useState([]);
  const [backendStatus, setBackendStatus] = useState(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [modelName, setModelName] = useState("");

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

  // ─── Initialize session on mount ─────────────────────────────────────
  useEffect(() => {
    async function init() {
      try {
        const health = await checkHealth();
        if (!health.ai_configured) {
          setBackendStatus("error");
          setStatusMessage(
            "⚠️ Gemini API key not configured. Edit backend/.env and set your GEMINI_API_KEY."
          );
          return;
        }
        setBackendStatus("ok");
        setModelName(health.model);
        setStatusMessage(`Connected • Model: ${health.model}`);

        const sid = await createSession();
        setSessionId(sid);
      } catch (err) {
        setBackendStatus("error");
        setStatusMessage(
          "❌ Cannot connect to backend. Make sure the FastAPI server is running on port 8000."
        );
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
  const handleStopCapture = useCallback(() => {
    stopCapture();
  }, [stopCapture]);

  // ─── Capture frame and add to context (for multi-screen questions) ───
  const handleCaptureContext = useCallback(async () => {
    if (!sessionId) return;

    const frame = captureFrame();
    if (!frame) return;

    try {
      const result = await addScreenshot(sessionId, frame);
      setContextCount(result.context_count);
      setStatusMessage(`📸 Screenshot added to context (${result.context_count} total)`);
    } catch (err) {
      console.error("Failed to add screenshot:", err);
      setStatusMessage("❌ Failed to add screenshot to context");
    }
  }, [sessionId, captureFrame]);

  // ─── Capture current screen + analyze with streaming ──────────────────
  const handleAnalyze = useCallback(
    async (question = null) => {
      if (!sessionId || isAnalyzing) return;

      setIsAnalyzing(true);
      setStatusMessage("🔍 Analyzing screen...");

      const frame = captureFrame();
      if (!frame) {
        setStatusMessage("❌ Could not capture screen frame");
        setIsAnalyzing(false);
        return;
      }

      // Create a live answer entry that updates as tokens stream in
      const liveAnswer = {
        answer: "",
        model: "",
        contextCount: 0,
        usage: null,
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
          liveAnswer.contextCount = info.context_count;
          setContextCount(info.context_count);
          setAnswers((prev) => {
            const updated = [...prev];
            updated[0] = { ...liveAnswer };
            return updated;
          });
          setStatusMessage("✅ Analysis complete");
          setIsAnalyzing(false);

          // Save to Supabase (fire-and-forget)
          if (user?.id) {
            saveAnalysis(user.id, question, liveAnswer.answer);
            trackUsage(user.id);
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
          setStatusMessage(`❌ ${errMsg}`);
          setIsAnalyzing(false);
        }
      );
    },
    [sessionId, isAnalyzing, captureFrame, user]
  );

  // ─── Handle clear context ────────────────────────────────────────────
  const handleClearContext = useCallback(async () => {
    if (!sessionId) return;
    try {
      await clearContext(sessionId);
      setContextCount(0);
      setStatusMessage("🗑️ Context cleared");
    } catch (err) {
      console.error("Failed to clear context:", err);
    }
  }, [sessionId]);

  // ─── Handle question from input ──────────────────────────────────────
  const handleAskQuestion = useCallback(
    (question) => {
      handleAnalyze(question);
    },
    [handleAnalyze]
  );

  return (
    <div className="app">
      {/* Hidden canvas for frame capture */}
      <canvas ref={canvasRef} style={{ display: "none" }} />

      {/* Header — Slim Toolbar */}
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
          <Link to="/" className="back-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
            <span>Home</span>
          </Link>
        </div>
        <div className="header-right">
          {backendStatus === "ok" ? (
            <div className="status-group">
              <span className="status-dot" />
              <span className="status-model">{modelName}</span>
            </div>
          ) : (
            <div className={`backend-status ${backendStatus || ""}`}>
              {statusMessage}
            </div>
          )}
          {contextCount > 0 && (
            <button className="btn-clear-ctx" onClick={handleClearContext}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              Clear
            </button>
          )}
          {user && (
            <div className="user-menu">
              <div className="user-avatar">
                {(user.email?.[0] || "U").toUpperCase()}
              </div>
              <button
                className="btn-sign-out"
                onClick={async () => { await signOut(); navigate("/"); }}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Question Input */}
      <div className="question-bar">
        <QuestionInput
          onSubmit={handleAskQuestion}
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
            onStopCapture={handleStopCapture}
            onCaptureAndAnalyze={() => handleAnalyze(null)}
            onCaptureContext={handleCaptureContext}
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
    </div>
  );
}

export default App;
