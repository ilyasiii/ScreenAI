import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { useAuth } from "../contexts/auth-context";
import { getHistory } from "../services/supabaseService";
import "./HistoryPage.css";

function HistoryPage() {
  const { user } = useAuth();
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    getHistory(user.id).then((data) => {
      setHistory(data);
      setLoading(false);
    });
  }, [user]);

  function formatDate(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
      " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  return (
    <div className="history-page">
      <header className="history-header">
        <div className="history-header-left">
          <div className="history-logo">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            <span>ScreenAI</span>
          </div>
          <Link to="/app" className="history-back-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back to App
          </Link>
        </div>
        <h1 className="history-title">Analysis History</h1>
      </header>

      <main className="history-main">
        {loading ? (
          <div className="history-empty">Loading…</div>
        ) : history.length === 0 ? (
          <div className="history-empty">
            <p>No history yet.</p>
            <Link to="/app" className="history-cta">Start analyzing →</Link>
          </div>
        ) : (
          <div className="history-list">
            {history.map((item) => (
              <div
                key={item.id}
                className={`history-card ${expanded === item.id ? "expanded" : ""}`}
                onClick={() => setExpanded(expanded === item.id ? null : item.id)}
              >
                <div className="history-card-header">
                  <span className="history-question">
                    {item.question || "Quick analyze"}
                  </span>
                  <span className="history-time">{formatDate(item.created_at)}</span>
                  <svg
                    className="history-chevron"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
                {expanded === item.id && (
                  <div className="history-answer" onClick={(e) => e.stopPropagation()}>
                    <ReactMarkdown>{item.answer}</ReactMarkdown>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default HistoryPage;
