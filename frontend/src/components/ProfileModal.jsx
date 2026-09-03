import { useState } from "react";
import { API_BASE } from "../config";
import { useProfile } from "../contexts/profile-context";
import "./ProfileModal.css";

export default function ProfileModal({ onClose }) {
  const { profile, saveProfile, markOnboarded } = useProfile();
  const [jobTitle, setJobTitle] = useState(profile?.job_title || "");
  const [jobDescription, setJobDescription] = useState(profile?.job_description || "");
  const [cvText, setCvText] = useState(profile?.cv_text || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const isEditMode = !!onClose;

  const handlePdfUpload = async (e, target) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.type === "application/pdf") {
      setLoading(true);
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = await fetch(`${API_BASE}/parse-pdf`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          setError("");
          if (target === "cv") setCvText(data.text);
          else setJobDescription(data.text);
        } else {
          setError(data.error || "Could not read that PDF.");
        }
      } catch {
        setError("Upload failed. Is the backend running?");
      } finally {
        setLoading(false);
      }
    } else {
      const text = await file.text();
      if (target === "cv") setCvText(text);
      else setJobDescription(text);
    }
    e.target.value = "";
  };

  const handleSave = () => {
    const data = {};
    if (jobTitle.trim()) data.job_title = jobTitle.trim();
    if (jobDescription.trim()) data.job_description = jobDescription.trim();
    if (cvText.trim()) data.cv_text = cvText.trim();
    saveProfile(Object.keys(data).length > 0 ? data : null);
    markOnboarded();
    if (onClose) onClose();
  };

  const handleSkip = () => {
    markOnboarded();
    if (onClose) onClose();
  };

  return (
    <div className="profile-modal-overlay">
      <div className="profile-modal">
        <div className="profile-modal-header">
          <h2>{isEditMode ? "Update Interview Data" : "Set Up Your Profile"}</h2>
          <p>{isEditMode
            ? "Update your job details for the current interview. Changes apply immediately."
            : "Personalize your AI answers by providing your details. You can always update this later."
          }</p>
        </div>

        <div className="profile-modal-body">
          <div className="modal-field">
            <label>Job Title</label>
            <input
              type="text"
              placeholder="e.g. Senior Frontend Developer"
              value={jobTitle}
              onChange={(e) => setJobTitle(e.target.value)}
            />
          </div>

          <div className="modal-field">
            <label>Job Description</label>
            <textarea
              placeholder="Paste job description here or upload a PDF..."
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              rows={3}
            />
            <label className="modal-upload-btn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              Upload PDF/TXT
              <input type="file" accept=".pdf,.txt" onChange={(e) => handlePdfUpload(e, "jd")} hidden />
            </label>
          </div>

          <div className="modal-field">
            <label>Your CV / Resume</label>
            <textarea
              placeholder="Paste your CV text here or upload a PDF..."
              value={cvText}
              onChange={(e) => setCvText(e.target.value)}
              rows={3}
            />
            <label className="modal-upload-btn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              Upload PDF/TXT
              <input type="file" accept=".pdf,.txt" onChange={(e) => handlePdfUpload(e, "cv")} hidden />
            </label>
          </div>

          {loading && <p className="modal-loading">Parsing PDF...</p>}
          {error && <p className="modal-error">{error}</p>}
        </div>

        <div className="profile-modal-footer">
          <button className="btn-skip" onClick={handleSkip}>
            {isEditMode ? "Cancel" : "Skip for now"}
          </button>
          <button className="btn-continue" onClick={handleSave} disabled={loading}>
            {isEditMode ? "Update" : "Save & Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
