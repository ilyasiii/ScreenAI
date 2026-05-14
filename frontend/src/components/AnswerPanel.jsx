/**
 * AnswerPanel Component — Clean Minimal Tool UI
 */
import ReactMarkdown from "react-markdown";
import "./AnswerPanel.css";

export default function AnswerPanel({ answers, isAnalyzing }) {
  if (answers.length === 0 && !isAnalyzing) {
    return (
      <div className="answer-panel">
        <div className="panel-header">
          <h3 className="panel-title">Responses</h3>
        </div>
        <div className="empty-state">
          <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <p className="empty-text">Share screen → Analyze → Get answers</p>
        </div>
      </div>
    );
  }

  return (
    <div className="answer-panel">
      <div className="panel-header">
        <h3 className="panel-title">Responses</h3>
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
