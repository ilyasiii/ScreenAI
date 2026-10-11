/**
 * InterviewPage — voice interview mode.
 *
 * The browser captures the interviewer's audio (the meeting tab, the system
 * output, or a microphone), records one clip per push-to-talk press, and
 * uploads it. The backend transcribes it and streams back an answer.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import Markdown from "../components/Markdown";
import { useAuth } from "../contexts/auth-context";
import { useProfile } from "../contexts/profile-context";
import ApiKeyModal from "../components/ApiKeyModal";
import ProfileModal from "../components/ProfileModal";
import {
  supportsMeetingAudio,
  supportsRecording,
  useAudioCapture,
} from "../hooks/useAudioCapture";
import {
  checkHealth,
  createSession,
  deleteSession,
  resetVoiceMemory,
  voiceAnswerStream,
} from "../services/api";
import { clearCredentials, loadCredentials } from "../services/credentials";
import "./InterviewPage.css";

let answerSeq = 0;
const nextAnswerId = () => `v${Date.now().toString(36)}-${answerSeq++}`;

/** True when Space should type a character rather than trigger recording. */
function isTyping(target) {
  return Boolean(target.closest?.("input, textarea, select, [contenteditable='true']"));
}

/**
 * Key fields the server cannot supply itself, per its /health report. Empty
 * when the server refuses browser keys: prompting for one would be pointless.
 */
function keysServerLacks(health) {
  if (!health || !health.allows_client_keys) return [];
  const needed = [];
  if (!health.groq_configured) needed.push("groq_key");
  const provider = health.voice_provider || "openai";
  if (!health[`${provider}_configured`]) needed.push(`${provider}_key`);
  return [...new Set(needed)];
}

/** Input level bar. Animates itself so the page does not re-render per frame. */
function LevelMeter({ getLevel, active }) {
  const barRef = useRef(null);
  useEffect(() => {
    if (!active) return undefined;
    let frame = 0;
    const tick = () => {
      if (barRef.current) {
        // RMS of speech sits around 0.02-0.2; scale so normal talk fills most of it.
        const pct = Math.min(100, Math.sqrt(getLevel()) * 220);
        barRef.current.style.width = `${pct}%`;
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [getLevel, active]);

  return (
    <div className="level-meter" aria-hidden="true">
      <div className="level-meter-fill" ref={barRef} />
    </div>
  );
}

export default function InterviewPage() {
  const { user, signOut } = useAuth();
  const { profile } = useProfile();
  const navigate = useNavigate();

  const [state, setState] = useState("idle"); // idle | recording | transcribing | answering
  const [transcript, setTranscript] = useState("");
  const [answer, setAnswer] = useState("");
  const [answers, setAnswers] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [recordingTime, setRecordingTime] = useState(0);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [health, setHealth] = useState(null);
  // Non-null while the key prompt is open: { needed: string[], error?: string }.
  const [keyPrompt, setKeyPrompt] = useState(null);

  const stateRef = useRef("idle");

  const setPhase = useCallback((next) => {
    stateRef.current = next;
    setState(next);
  }, []);

  // Sharing ended from the browser's own bar. If that happened mid-press the
  // pointer-up never reaches a button (the picker replaces it), so reset here.
  const handleCaptureEnded = useCallback(() => {
    if (stateRef.current === "recording") setPhase("idle");
    setNotice("Audio sharing stopped. Choose a source to continue.");
  }, [setPhase]);

  const audio = useAudioCapture({ onEnded: handleCaptureEnded });
  const {
    connected,
    connecting,
    source,
    connect,
    disconnect,
    startRecording: beginClip,
    stopRecording: endClip,
    getLevel,
  } = audio;

  const sessionIdRef = useRef(null);
  const abortRef = useRef(null);
  // Mirrors whether a modal is open, for the global Space handler.
  const modalOpenRef = useRef(false);
  const answerRef = useRef("");
  const transcriptRef = useRef("");
  // A recorded clip held back while the user enters a missing key, so the
  // question they just asked is not lost.
  const pendingClipRef = useRef(null);
  // Tokens arrive faster than the browser can usefully repaint, and every
  // repaint re-parses the whole markdown answer. Buffer into the ref, flush to
  // state once per animation frame.
  const frameRef = useRef(0);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    modalOpenRef.current = Boolean(keyPrompt) || showProfileModal;
  }, [keyPrompt, showProfileModal]);

  // ─── Close user menu on click outside ──────────────────────────────
  useEffect(() => {
    if (!showUserMenu) return;
    const handleClick = (e) => {
      if (!e.target.closest(".user-menu-wrapper")) setShowUserMenu(false);
    };
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [showUserMenu]);

  const flushAnswer = useCallback(() => {
    frameRef.current = 0;
    setAnswer(answerRef.current);
  }, []);

  const scheduleFlush = useCallback(() => {
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(flushAnswer);
  }, [flushAnswer]);

  const cancelFlush = useCallback(() => {
    if (frameRef.current) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
    }
  }, []);

  // ─── Boot: server capabilities and a session ─────────────────────────
  useEffect(() => {
    let cancelled = false;
    let created = null;
    (async () => {
      try {
        const info = await checkHealth();
        if (cancelled) return;
        setHealth(info);
        const provider = info.voice_provider || "openai";
        if (
          !info.allows_client_keys &&
          (!info.groq_configured || !info[`${provider}_configured`])
        ) {
          setError("Voice mode is not configured on this server.");
          return;
        }
        created = await createSession();
        if (cancelled) {
          deleteSession(created);
          return;
        }
        setSessionId(created);
      } catch (err) {
        if (!cancelled) {
          setError(
            err?.response?.data?.detail?.message || "Cannot reach the server. Try reloading."
          );
        }
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.();
      cancelFlush();
      const id = sessionIdRef.current || created;
      if (id) deleteSession(id);
    };
  }, [cancelFlush]);

  // ─── Recording timer ─────────────────────────────────────────────────
  useEffect(() => {
    if (state !== "recording") return undefined;

    // Elapsed time is measured against a start stamp rather than accumulated
    // in 0.1 increments, which drifts as soon as the tab is throttled. The
    // counter is reset in startRecording, so nothing sets state in this body.
    const started = performance.now();
    const timer = setInterval(() => {
      setRecordingTime((performance.now() - started) / 1000);
    }, 100);

    return () => clearInterval(timer);
  }, [state]);

  /** Key fields still missing: the server lacks them and so does this tab. */
  const missingKeys = useCallback(() => {
    const stored = loadCredentials();
    return keysServerLacks(health).filter((name) => !stored[name]);
  }, [health]);

  // ─── Ask ─────────────────────────────────────────────────────────────
  const submitClip = useCallback(
    (clip) => {
      const id = sessionIdRef.current;
      if (!id) return;
      // Never two answers writing into the same buffers.
      abortRef.current?.();

      answerRef.current = "";
      transcriptRef.current = "";
      setAnswer("");
      setTranscript("");
      setError("");
      setNotice("");
      setPhase("transcribing");

      abortRef.current = voiceAnswerStream({
        sessionId: id,
        audio: clip,
        profile,
        defaultNeeded: keysServerLacks(health),
        onNewSession: setSessionId,
        onTranscription: (text) => {
          transcriptRef.current = text;
          setTranscript(text);
          setPhase("answering");
        },
        onNoSpeech: () => {
          setNotice("Nothing intelligible was heard. Try again a little closer to the question.");
        },
        onToken: (token) => {
          answerRef.current += token;
          scheduleFlush();
        },
        onDone: () => {
          cancelFlush();
          const finalAnswer = answerRef.current;
          if (finalAnswer.trim()) {
            setAnswers((prev) => [
              {
                id: nextAnswerId(),
                question: transcriptRef.current,
                answer: finalAnswer,
                timestamp: new Date().toLocaleTimeString(),
              },
              ...prev,
            ]);
          }
          answerRef.current = "";
          setAnswer("");
          abortRef.current = null;
          setPhase("idle");
        },
        onError: (message) => {
          cancelFlush();
          abortRef.current = null;
          // Keep whatever had already streamed rather than discarding it.
          const partial = answerRef.current;
          if (partial.trim()) {
            setAnswers((prev) => [
              {
                id: nextAnswerId(),
                question: transcriptRef.current,
                answer: `${partial}\n\n_(Answer interrupted.)_`,
                timestamp: new Date().toLocaleTimeString(),
              },
              ...prev,
            ]);
          }
          answerRef.current = "";
          setAnswer("");
          setError(message);
          setPhase("idle");
        },
        onKeyRequired: (err) => {
          abortRef.current = null;
          setPhase("idle");
          if (err.refused) {
            setError(err.message);
            return;
          }
          pendingClipRef.current = clip;
          setKeyPrompt({ needed: err.needed, error: err.message });
        },
      });
    },
    [profile, health, scheduleFlush, cancelFlush, setPhase]
  );

  // ─── Push-to-talk ────────────────────────────────────────────────────
  const startRecording = useCallback(() => {
    if (!connected || !sessionIdRef.current || stateRef.current !== "idle") return;

    // Ask for keys before recording, so the user is not left holding the
    // button only to be interrupted by a modal afterwards.
    const needed = missingKeys();
    if (needed.length) {
      setKeyPrompt({ needed });
      return;
    }

    if (beginClip()) {
      setRecordingTime(0);
      setNotice("");
      setPhase("recording");
    }
  }, [connected, missingKeys, beginClip, setPhase]);

  const stopRecording = useCallback(async () => {
    if (stateRef.current !== "recording") return;
    // Busy until the clip is finalised, so a quick second press cannot start
    // a new recording while this one is still being closed.
    setPhase("transcribing");
    const clip = await endClip();
    if (!clip) {
      setPhase("idle");
      return;
    }
    if (!clip.hasSound) {
      setPhase("idle");
      setNotice(
        clip.seconds < 0.4
          ? "Hold the button for the whole question."
          : "No sound was picked up. Check the audio source is the one the interviewer is on."
      );
      return;
    }
    submitClip(clip.blob);
  }, [endClip, submitClip, setPhase]);

  const clearMemory = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    try {
      await resetVoiceMemory(id, setSessionId);
      setAnswers([]);
      setTranscript("");
      setAnswer("");
      setNotice("Memory cleared.");
    } catch {
      setError("Could not clear memory. Try again.");
    }
  }, []);

  // Keyboard: hold Space to record
  useEffect(() => {
    let spaceHeld = false;

    const onKeyDown = (e) => {
      if (e.code === "Space" && !e.repeat && !isTyping(e.target) && !modalOpenRef.current) {
        e.preventDefault();
        if (!spaceHeld) {
          spaceHeld = true;
          startRecording();
        }
      }
    };

    const onKeyUp = (e) => {
      if (e.code === "Space" && !isTyping(e.target)) {
        e.preventDefault();
        if (spaceHeld) {
          spaceHeld = false;
          stopRecording();
        }
      }
    };

    // Switching windows while holding Space means the keyup never arrives.
    const onBlur = () => {
      spaceHeld = false;
      stopRecording();
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [startRecording, stopRecording]);

  // Primary button / finger only. Capturing the pointer keeps a slight finger
  // movement from ending the press early on touch screens.
  const handlePointerDown = useCallback(
    (e) => {
      if (e.button !== 0) return;
      e.currentTarget.setPointerCapture?.(e.pointerId);
      startRecording();
    },
    [startRecording]
  );

  /** Free the server session before the token goes away, then sign out. */
  const handleSignOut = useCallback(async () => {
    setShowUserMenu(false);
    const id = sessionIdRef.current;
    sessionIdRef.current = null;
    if (id) await deleteSession(id);
    try {
      clearCredentials();
      await signOut();
    } finally {
      navigate("/");
    }
  }, [signOut, navigate]);

  const ready = connected && Boolean(sessionId);
  const busy = state === "transcribing" || state === "answering";
  const canRecord = supportsRecording();
  const canShareMeeting = supportsMeetingAudio();

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
                  <button
                    className="dropdown-item"
                    onClick={handleSignOut}
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

      {/* Main Content */}
      <main className="interview-main">
        {/* Left: Controls & Status */}
        <section className="interview-controls-panel">
          {(error || audio.error) && (
            <div className="interview-error">{error || audio.error}</div>
          )}
          {notice && !error && <div className="interview-notice">{notice}</div>}

          {!connected ? (
            <div className="audio-source-picker">
              <h3>Where is the interviewer?</h3>
              {!canRecord ? (
                <p className="record-hint">
                  This browser cannot record audio. Use a recent Chrome, Edge or Firefox on a
                  computer.
                </p>
              ) : (
                <>
                  {canShareMeeting && (
                    <button
                      className="source-btn primary"
                      onClick={() => connect("meeting")}
                      disabled={connecting}
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                      <span>
                        <strong>Share meeting audio</strong>
                        <small>
                          Pick the meeting tab and turn on &ldquo;Share tab audio&rdquo;, or pick
                          the entire screen and turn on &ldquo;Share system audio&rdquo;.
                        </small>
                      </span>
                    </button>
                  )}
                  <button
                    className="source-btn"
                    onClick={() => connect("microphone")}
                    disabled={connecting}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                    <span>
                      <strong>Use microphone</strong>
                      <small>For calls on speaker, or where audio sharing is unavailable.</small>
                    </span>
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="record-center">
              <div className="record-section">
                <div className="record-icon-wrapper">
                  <button
                    className={`record-btn ${state === "recording" ? "recording" : ""}`}
                    onPointerDown={handlePointerDown}
                    onPointerUp={stopRecording}
                    onPointerCancel={stopRecording}
                    onLostPointerCapture={stopRecording}
                    onContextMenu={(e) => e.preventDefault()}
                    disabled={!ready || busy}
                    aria-label="Hold to record the question"
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
                <LevelMeter getLevel={getLevel} active={connected} />
                <div className="record-label">
                  {state === "recording" && <span className="rec-time">{recordingTime.toFixed(1)}s</span>}
                  {state === "idle" && (ready ? "Hold to Record" : error ? "Unavailable" : "Connecting…")}
                  {state === "transcribing" && "Transcribing…"}
                  {state === "answering" && "Generating answer…"}
                </div>
                <p className="record-hint">
                  {state === "idle" && "Press & hold Space or click & hold the button"}
                  {state === "recording" && "Release when the question ends"}
                  {state === "transcribing" && "Processing audio…"}
                  {state === "answering" && "Streaming response…"}
                </p>
                <button className="source-change" onClick={disconnect} disabled={state !== "idle"}>
                  Listening to {source === "meeting" ? "meeting audio" : "microphone"} · Change
                </button>
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
          )}

          {/* Transcript */}
          {transcript && (
            <div className="transcript-box">
              <div className="transcript-label">Last heard:</div>
              <p className="transcript-text">"{transcript}"</p>
            </div>
          )}

          {/* Clear button */}
          <button className="btn-clear-memory" onClick={clearMemory} disabled={!sessionId || busy}>
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
                <Markdown>{answer}</Markdown>
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
            <div key={item.id} className="answer-card">
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
                <Markdown>{item.answer}</Markdown>
              </div>
            </div>
          ))}
        </section>
      </main>

      {showProfileModal && <ProfileModal onClose={() => setShowProfileModal(false)} />}


      {keyPrompt && (
        <ApiKeyModal
          needed={keyPrompt.needed}
          error={keyPrompt.error}
          onSaved={() => {
            setKeyPrompt(null);
            setError("");
            // Replay the question that was interrupted by the prompt.
            const clip = pendingClipRef.current;
            pendingClipRef.current = null;
            if (clip && stateRef.current === "idle") submitClip(clip);
          }}
          onCancel={() => {
            pendingClipRef.current = null;
            setKeyPrompt(null);
          }}
        />
      )}
    </div>
  );
}
