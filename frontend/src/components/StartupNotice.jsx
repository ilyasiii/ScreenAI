/**
 * Shown instead of the app when it cannot start, or when a render throws.
 *
 * Both cases used to produce a blank white page: a module-scope throw kills the
 * bundle before React mounts, and an uncaught render error unmounts the tree.
 * Neither leaves anything on screen, so the only clue is the browser console.
 */
import { Component } from "react";

import "./StartupNotice.css";

function Notice({ title, children, detail }) {
  return (
    <div className="startup-notice">
      <div className="startup-card">
        <div className="startup-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        </div>
        <h1>{title}</h1>
        {children}
        {detail && <pre className="startup-detail">{detail}</pre>}
      </div>
    </div>
  );
}

/** Missing Supabase configuration — the app cannot sign anyone in. */
export function ConfigNotice() {
  return (
    <Notice title="Supabase is not configured">
      <p>
        The frontend needs a Supabase URL and anon key to sign you in. Create{" "}
        <code>frontend/.env.local</code> and restart the dev server:
      </p>
      <pre className="startup-code">
        {`cd frontend
copy .env.example .env.local

# then set these two values in it:
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key`}
      </pre>
      <p className="startup-footnote">
        Vite only reads env files at startup, so restart <code>npm run dev</code>{" "}
        after editing. The anon key is public by design — Row Level Security is
        what protects your data.
      </p>
    </Notice>
  );
}

/**
 * Catches render-time errors anywhere below it.
 *
 * Without this, one thrown error in any component blanks the entire page.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Unhandled render error:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <Notice
        title="Something went wrong"
        detail={this.state.error?.stack || String(this.state.error)}
      >
        <p>
          The app hit an error it could not recover from. The details below are
          also in the browser console.
        </p>
        <button className="startup-button" onClick={() => window.location.reload()}>
          Reload
        </button>
      </Notice>
    );
  }
}
