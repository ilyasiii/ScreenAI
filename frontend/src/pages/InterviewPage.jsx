/**
 * InterviewPage — Voice AI Interview Mode
 * Real-time audio capture, transcription, and AI-powered answer streaming.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { useAuth } from "../contexts/AuthContext";
import { useProfile } from "../contexts/ProfileContext";
import ProfileModal from "../components/ProfileModal";
import "./InterviewPage.css";

const WS_URL = "ws://localhost:8000/ws/voice";

export default function InterviewPage() {
  const { user, signOut } = useAuth();
  const { profile } = useProfile();
  const [state, setState] = useState("idle"); // idle | recording | transcribing | answering
  const [transcript, setTranscript] = useState("");
  const [answer, setAnswer] = useState("");
  const [answers, setAnswers] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [recordingTime, setRecordingTime] = useState(0);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // ─── Close user menu on click outside ──────────────────────────────
  useEffect(() => {
    if (!showUserMenu) return;
    const handleClick = (e) => {
      if (!e.target.closest(".user-menu-wrapper")) setShowUserMenu(false);
    };
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [showUserMenu]);

  const wsRef = useRef(null);
  const timerRef = useRef(null);
  const answerRef = useRef("");
  const transcriptRef = useRef("");

  // ─── WebSocket connection ────────────────────────────────────────────
  useEffect(() => {
    let ws = null;
    let cancelled = false;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) { ws.close(); return; }
        setConnected(true);
        setError("");
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        const msg = JSON.parse(event.data);

        switch (msg.type) {
          case "status":
            setState(msg.state);
            if (msg.state === "transcribing") {
              setAnswer("");
              answerRef.current = "";
            }
            break;
          case "transcription":
            setTranscript(msg.text);
            transcriptRef.current = msg.text;
            break;
          case "token":
            answerRef.current += msg.text;
            setAnswer(answerRef.current);
            break;
          case "done": {
            const finalAnswer = answerRef.current;
            const finalQuestion = transcriptRef.current;
            if (finalAnswer) {
              setAnswers((prev) => [
                { question: finalQuestion, answer: finalAnswer, timestamp: new Date().toLocaleTimeString() },
                ...prev,
              ]);
            }
            answerRef.current = "";
            setAnswer("");
            setState("idle");
            break;
          }
          case "error":
            setError(msg.message);
            setState("idle");
            break;
        }
      };

      ws.onclose = () => {
        if (!cancelled) setConnected(false);
      };

      ws.onerror = () => {
        if (!cancelled) {
          setConnected(false);
          setError("WebSocket connection failed. Make sure the backend is running.");
        }
      };
    };

    // Small delay to survive React StrictMode double-mount
    const timer = setTimeout(connect, 100);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (ws) ws.close();
    };
  }, []);

  // ─── Recording timer ─────────────────────────────────────────────────
  useEffect(() => {
    if (state === "recording") {
      setRecordingTime(0);
      timerRef.current = setInterval(() => {
        setRecordingTime((t) => t + 0.1);
      }, 100);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [state]);

  // ─── Actions ─────────────────────────────────────────────────────────
  const startRecording = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "start_recording" }));
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "stop_recording" }));
    }
  }, []);

  const clearMemory = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "clear_memory" }));
      setAnswers([]);
      setTranscript("");
      setAnswer("");
    }
  }, []);

  // ─── Send profile to WebSocket when connected ────────────────────────
  useEffect(() => {
    if (connected && wsRef.current?.readyState === WebSocket.OPEN && profile) {
      wsRef.current.send(JSON.stringify({ action: "set_profile", profile }));
    }
  }, [connected, profile]);

  // ─── Hold-to-record handlers ─────────────────────────────────────────
  const handlePointerDown = useCallback(() => {
    startRecording();
  }, [startRecording]);

  const handlePointerUp = useCallback(() => {
    stopRecording();
  }, [stopRecording]);

  // Keyboard: hold Space to record
  useEffect(() => {
    let spaceHeld = false;

    const onKeyDown = (e) => {
      if (e.code === "Space" && !e.repeat && !e.target.closest("input, textarea")) {
        e.preventDefault();
        if (!spaceHeld) {
          spaceHeld = true;
          startRecording();
        }
      }
    };

    const onKeyUp = (e) => {
      if (e.code === "Space" && !e.target.closest("input, textarea")) {
        e.preventDefault();
        if (spaceHeld) {
          spaceHeld = false;
          stopRecording();
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [startRecording, stopRecording]);

  return (
    <div className="interview-page">
      {/* Header */}
      <header className="interview-header">
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
            <Link to="/app" className="nav-tab">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              Home
            </Link>
            <span className="nav-tab active">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
              Interview
            </span>
            <Link to="/history" className="nav-tab">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              History
            </Link>
          </nav>
        </div>
        <div className="header-right">
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
                  {user.user_metadata?.full_name
                    ? user.user_metadata.full_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2)
                    : (user.email?.slice(0, 2) || "U").toUpperCase()}
                </div>
                <div className="user-info">
                  <span className="user-name">{user.user_metadata?.full_name || user.email?.split("@")[0] || "User"}</span>
                  <span className="user-email">{user.email}</span>
                </div>
                <svg className="dropdown-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
              </div>
              {showUserMenu && (
                <div className="user-dropdown">
                  <button className="dropdown-item" onClick={signOut}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    Sign out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main className="interview-main">
        {/* Left: Controls & Status */}
        <section className="interview-controls-panel">
          {error && <div className="interview-error">{error}</div>}

          {/* Centered Record Area */}
          <div className="record-center">
            <div className="record-section">
              <div className="record-icon-wrapper">
                <button
                  className={`record-btn ${state === "recording" ? "recording" : ""}`}
                  onPointerDown={handlePointerDown}
                  onPointerUp={handlePointerUp}
                  onPointerLeave={state === "recording" ? handlePointerUp : undefined}
                  disabled={!connected || state === "transcribing" || state === "answering"}
                >
                  <div className="record-btn-inner">
                    {state === "recording" ? (
                      <div className="recording-pulse"></div>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                        <line x1="12" y1="19" x2="12" y2="23"/>
                        <line x1="8" y1="23" x2="16" y2="23"/>
                      </svg>
                    )}
                  </div>
                </button>
              </div>
              <div className="record-label">
                {state === "recording" && <span className="rec-time">{recordingTime.toFixed(1)}s</span>}
                {state === "idle" && "Hold to Record"}
                {state === "transcribing" && "Transcribing…"}
                {state === "answering" && "Generating answer…"}
              </div>
              <p className="record-hint">
                {state === "idle" && "Press & hold Space or click & hold the button"}
                {state === "recording" && "Release when done speaking"}
                {state === "transcribing" && "Processing audio…"}
                {state === "answering" && "Streaming response…"}
              </p>
            </div>

            {/* Status Indicators */}
            <div className="pipeline-status">
              <div className={`pipeline-step ${state === "recording" ? "active" : ""}`}>
                <span className="step-dot"></span>
                <span>Capture</span>
              </div>
              <div className="pipeline-arrow">→</div>
              <div className={`pipeline-step ${state === "transcribing" ? "active" : ""}`}>
                <span className="step-dot"></span>
                <span>Transcribe</span>
              </div>
              <div className="pipeline-arrow">→</div>
              <div className={`pipeline-step ${state === "answering" ? "active" : ""}`}>
                <span className="step-dot"></span>
                <span>Answer</span>
              </div>
            </div>
          </div>

          {/* Transcript */}
          {transcript && (
            <div className="transcript-box">
              <div className="transcript-label">Last heard:</div>
              <p className="transcript-text">"{transcript}"</p>
            </div>
          )}

          {/* Clear button */}
          <button className="btn-clear-memory" onClick={clearMemory} disabled={!connected}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            Clear Memory
          </button>
        </section>

        {/* Right: Answers */}
        <section className="interview-answers-panel">
          <div className="answers-header">
            <h3>AI Responses</h3>
            {answers.length > 0 && <span className="ans-count">{answers.length}</span>}
          </div>

          {/* Live answer (currently streaming) */}
          {answer && state === "answering" && (
            <div className="answer-card live">
              <div className="answer-meta">
                <span className="streaming-indicator">
                  <span className="stream-dot"></span>
                  Streaming
                </span>
              </div>
              {transcript && (
                <div className="answer-question">
                  <strong>Q:</strong> {transcript}
                </div>
              )}
              <div className="answer-content">
                <ReactMarkdown>{answer}</ReactMarkdown>
                <span className="cursor-blink">▏</span>
              </div>
            </div>
          )}

          {/* Historical answers */}
          {answers.length === 0 && state !== "answering" && (
            <div className="empty-answers">
              <div className="empty-icon-wrapper">
                <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <p>Hold record while interviewer speaks to get AI answers</p>
            </div>
          )}

          {answers.map((item, index) => (
            <div key={index} className="answer-card">
              <div className="answer-meta">
                <span className="answer-number">#{answers.length - index}</span>
                <span className="answer-time">{item.timestamp}</span>
              </div>
              {item.question && (
                <div className="answer-question">
                  <strong>Q:</strong> {item.question}
                </div>
              )}
              <div className="answer-content">
                <ReactMarkdown>{item.answer}</ReactMarkdown>
              </div>
            </div>
          ))}
        </section>
      </main>

      {showProfileModal && <ProfileModal onClose={() => setShowProfileModal(false)} />}
    </div>
  );
}
