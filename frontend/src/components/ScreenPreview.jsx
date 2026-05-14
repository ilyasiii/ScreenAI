/**
 * ScreenPreview Component — Clean Minimal Tool UI
 */
import "./ScreenPreview.css";

export default function ScreenPreview({
  isSharing,
  onStartCapture,
  onStopCapture,
  onCaptureAndAnalyze,
  onCaptureContext,
  videoRef,
  error,
  contextCount,
  isAnalyzing,
}) {
  return (
    <div className="screen-preview">
      {/* Compact Header */}
      <div className="preview-header">
        <h3 className="preview-title">Screen</h3>
        <div className="status-badge" data-active={isSharing}>
          <span className="status-dot"></span>
          {isSharing ? "Live" : "Off"}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Video Area — Clean, no browser chrome */}
      <div className="preview-area">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="screen-video"
          style={{ display: isSharing ? "block" : "none" }}
        />
        {!isSharing && (
          <div className="placeholder">
            <svg className="placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            <p className="placeholder-text">Click below to share your screen</p>
          </div>
        )}
      </div>

      {/* Compact Action Buttons */}
      <div className="controls">
        {!isSharing ? (
          <button className="btn btn-primary" onClick={onStartCapture}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            Share Screen
          </button>
        ) : (
          <>
            <button
              className={`btn btn-primary${!isAnalyzing ? " pulse-ready" : ""}`}
              onClick={onCaptureAndAnalyze}
              disabled={isAnalyzing}
            >
              {isAnalyzing ? (
                <>
                  <span className="spinner"></span>
                  Analyzing...
                </>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                  Analyze
                </>
              )}
            </button>

            <button
              className="btn btn-outline"
              onClick={onCaptureContext}
              disabled={isAnalyzing}
              title="Add screenshot to context"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              Context
              {contextCount > 0 && <span className="ctx-badge">{contextCount}</span>}
            </button>

            <button className="btn btn-ghost" onClick={onStopCapture}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
              Stop
            </button>
          </>
        )}
      </div>
    </div>
  );
}
