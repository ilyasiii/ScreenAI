/**
 * AnswerPanel Component — Professional Dashboard Panel
 */
import ReactMarkdown from "react-markdown";
import "./AnswerPanel.css";

export default function AnswerPanel({ answers, isAnalyzing }) {
  if (answers.length === 0 && !isAnalyzing) {
    return (
      <div className="answer-panel">
        <div className="panel-header">
          <div className="panel-header-left">
            <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
            </svg>
            <h3 className="panel-title">AI Responses</h3>
          </div>
        </div>
        <div className="empty-state">
          <div className="empty-icon-wrapper">
            <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
            </svg>
          </div>
          <h2 className="empty-heading">Share your screen to get started</h2>
          <p className="empty-text">I'll analyze your screen and provide intelligent answers to your questions in real-time.</p>

          {/* Steps */}
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
              <span className="step-desc">Processing content</span>
            </div>
            <div className="step-arrow">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
            </div>
            <div className="step">
              <div className="step-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <span className="step-num">3. Get Answers</span>
              <span className="step-desc">View results</span>
            </div>
          </div>

          {/* Bottom note */}
          <div className="bottom-note">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
            <span>AI analysis happens in real-time and is not stored.</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="answer-panel">
      <div className="panel-header">
        <div className="panel-header-left">
          <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
          </svg>
          <h3 className="panel-title">AI Responses</h3>
        </div>
        <span className="answer-count">{answers.length}</span>
      </div>

      <div className="answers-list">
        {isAnalyzing && answers.length > 0 && answers[0].streaming && answers[0].answer === "" && (
          <div className="answer-card analyzing">
            <div className="analyzing-label">
              <span className="analyzing-dot"></span>
              Analyzing...
            </div>
            <div className="skeleton-loader">
              <div className="skeleton-line"></div>
              <div className="skeleton-line"></div>
              <div className="skeleton-line"></div>
            </div>
          </div>
        )}

        {answers.map((item, index) => {
          if (index === 0 && item.streaming && item.answer === "") return null;

          return (
            <div key={index} className={`answer-card${item.streaming ? " streaming" : ""}`}>
              <div className="answer-meta">
                <span className="answer-number">#{answers.length - index}</span>
                <span className="answer-time">{item.timestamp}</span>
                {item.streaming && <span className="streaming-badge">streaming</span>}
              </div>

              {item.question && (
                <div className="answer-question">
                  <strong>Q:</strong> {item.question}
                </div>
              )}

              <div className="answer-content">
                <ReactMarkdown>{item.answer}</ReactMarkdown>
                {item.streaming && <span className="cursor-blink">▏</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
