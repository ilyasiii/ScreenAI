/**
 * QuestionInput Component — Floating Pill Search Bar
 */
import { useState } from "react";
import "./QuestionInput.css";

export default function QuestionInput({ onSubmit, isAnalyzing, isSharing }) {
  const [question, setQuestion] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isSharing || isAnalyzing) return;
    onSubmit(question.trim() || null);
    setQuestion("");
  };

  return (
    <form className="question-input" onSubmit={handleSubmit}>
      <input
        type="text"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder={
          isSharing
            ? "Ask about what's on screen..."
            : "Start screen sharing first..."
        }
        disabled={!isSharing || isAnalyzing}
      />
      <span className="kbd-hint">Enter ↵</span>
      <button
        type="submit"
        className="btn-send"
        disabled={!isSharing || isAnalyzing}
        aria-label="Send"
      >
        {isAnalyzing ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10" strokeDasharray="31.4" strokeDashoffset="10"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/></circle></svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        )}
      </button>
    </form>
  );
}
