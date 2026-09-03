/**
 * Prompts for the API keys the backend cannot supply itself.
 *
 * Shown only when /health reports a key is missing and the server accepts
 * client-supplied keys. Which fields appear is driven entirely by what the
 * backend says it needs, so this covers both the analysis flow (OpenAI) and
 * voice mode (Groq, plus the voice provider).
 */
import { useState } from "react";

import { looksLikeKey, saveCredentials } from "../services/credentials";
import "./ApiKeyModal.css";

const FIELDS = {
  openai_key: {
    label: "OpenAI API key",
    placeholder: "sk-...",
    help: "Used to read your screen and answer questions.",
    link: "https://platform.openai.com/api-keys",
    linkLabel: "platform.openai.com",
  },
  groq_key: {
    label: "Groq API key",
    placeholder: "gsk_...",
    help: "Used to transcribe what the interviewer says.",
    link: "https://console.groq.com/keys",
    linkLabel: "console.groq.com",
  },
  anthropic_key: {
    label: "Anthropic API key",
    placeholder: "sk-ant-...",
    help: "Used to answer spoken questions.",
    link: "https://console.anthropic.com/settings/keys",
    linkLabel: "console.anthropic.com",
  },
};

export default function ApiKeyModal({ needed = ["openai_key"], onSaved, onCancel, error }) {
  const fields = needed.filter((name) => FIELDS[name]);
  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((name) => [name, ""]))
  );
  const [touched, setTouched] = useState(false);

  const allValid = fields.every((name) => looksLikeKey(values[name]));

  const handleSubmit = (e) => {
    e.preventDefault();
    setTouched(true);
    if (!allValid) return;
    saveCredentials(values);
    onSaved?.(values);
  };

  return (
    <div className="apikey-overlay" role="dialog" aria-modal="true" aria-labelledby="apikey-title">
      <form className="apikey-modal" onSubmit={handleSubmit}>
        <div className="apikey-header">
          <div className="apikey-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
            </svg>
          </div>
          <h2 id="apikey-title">
            {fields.length > 1 ? "API keys required" : "API key required"}
          </h2>
          <p>
            This server has no key of its own, so it uses yours. It is kept in
            this browser tab only, sent with your requests, and never stored on
            the server or written to disk.
          </p>
        </div>

        <div className="apikey-body">
          {fields.map((name) => {
            const field = FIELDS[name];
            const invalid = touched && !looksLikeKey(values[name]);
            return (
              <div className="apikey-field" key={name}>
                <label htmlFor={name}>{field.label}</label>
                <input
                  id={name}
                  type="password"
                  autoComplete="off"
                  spellCheck="false"
                  placeholder={field.placeholder}
                  value={values[name]}
                  aria-invalid={invalid}
                  onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                />
                <span className="apikey-help">
                  {field.help} Get one at{" "}
                  <a href={field.link} target="_blank" rel="noreferrer noopener">
                    {field.linkLabel}
                  </a>
                  .
                </span>
                {invalid && (
                  <span className="apikey-invalid">
                    That does not look like a key — check for a missing character.
                  </span>
                )}
              </div>
            );
          })}

          {error && <div className="apikey-error">{error}</div>}
        </div>

        <div className="apikey-footer">
          <button type="button" className="apikey-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="apikey-save" disabled={touched && !allValid}>
            Save and continue
          </button>
        </div>
      </form>
    </div>
  );
}
