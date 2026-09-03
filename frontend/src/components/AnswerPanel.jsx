/**
 * AnswerPanel — the streamed answer history.
 *
 * Each card is memoised on its answer object. App.jsx replaces only the object
 * that changed, so while one answer streams, every earlier card keeps its
 * previous reference and skips re-rendering. Without that, every token
 * re-parsed the markdown of every answer on screen.
 */
import { memo } from "react";
import ReactMarkdown from "react-markdown";

import "./AnswerPanel.css";

const PanelHeader = ({ count }) => (
  <div className="panel-header">
    <div className="panel-header-left">
      <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
      <h3 className="panel-title">AI Responses</h3>
    </div>
    {count > 0 && <span className="answer-count">{count}</span>}
  </div>
);

const AnswerCard = memo(function AnswerCard({ item, number }) {
  const { answer, question, timestamp, streaming, usage, error, stopped } = item;

  return (
    <div className={`answer-card${streaming ? " streaming" : ""}`}>
      <div className="answer-meta">
        <span className="answer-number">#{number}</span>
        <span className="answer-time">{timestamp}</span>
        {streaming && <span className="streaming-badge">streaming</span>}
        {stopped && <span className="streaming-badge">stopped</span>}
        {usage?.total_tokens != null && !streaming && (
          <span
            className="answer-time"
            title={
              `${usage.prompt_tokens} prompt + ${usage.completion_tokens} completion` +
              (usage.cached_tokens ? ` · ${usage.cached_tokens} cached` : "")
            }
          >
            {usage.total_tokens.toLocaleString()} tok
            {usage.cached_tokens ? " · cached" : ""}
          </span>
        )}
      </div>

      {question && (
        <div className="answer-question">
          <strong>Q:</strong> {question}
        </div>
      )}

      <div className="answer-content">
        <ReactMarkdown>{answer}</ReactMarkdown>
        {streaming && <span className="cursor-blink">▏</span>}
      </div>

      {error && !answer && <div className="error-banner">{error}</div>}
    </div>
  );
});

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-icon-wrapper">
        <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
      </div>
      <h2 className="empty-heading">Share your screen to get started</h2>
      <p className="empty-text">
        I&apos;ll read what&apos;s on screen and answer the question on it, or anything you ask about it.
      </p>

      <div className="steps-row">
        <div className="step">
          <div className="step-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          </div>
          <span className="step-num">1. Share Screen</span>
          <span className="step-desc">Start sharing</span>
        </div>
        <div className="step-arrow">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
        </div>
        <div className="step">
          <div className="step-icon accent">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          </div>
          <span className="step-num">2. AI Analyze</span>
          <span className="step-desc">Reading the screen</span>
        </div>
        <div className="step-arrow">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
        </div>
        <div className="step">
          <div className="step-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <span className="step-num">3. Get Answers</span>
          <span className="step-desc">Streamed live</span>
        </div>
      </div>

      <div className="bottom-note">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
        <span>Screenshots are held in memory for the session only.</span>
      </div>
    </div>
  );
}

export default function AnswerPanel({ answers, isAnalyzing }) {
  if (answers.length === 0 && !isAnalyzing) {
    return (
      <div className="answer-panel">
        <PanelHeader count={0} />
        <EmptyState />
      </div>
    );
  }

  const waiting = isAnalyzing && answers[0]?.streaming && answers[0].answer === "";

  return (
    <div className="answer-panel">
      <PanelHeader count={answers.length} />

      <div className="answers-list">
        {waiting && (
          <div className="answer-card analyzing">
            <div className="analyzing-label">
              <span className="analyzing-dot"></span>
              Reading the screen…
            </div>
            <div className="skeleton-loader">
              <div className="skeleton-line"></div>
              <div className="skeleton-line"></div>
              <div className="skeleton-line"></div>
            </div>
          </div>
        )}

        {answers.map((item, index) =>
          index === 0 && waiting ? null : (
            <AnswerCard key={item.id} item={item} number={answers.length - index} />
          )
        )}
      </div>
    </div>
  );
}
