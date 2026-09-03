import { useCallback, useState } from "react";

import { ProfileContext } from "./profile-context";

const STORAGE_KEY = "screenai_profile";

function loadProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function ProfileProvider({ children }) {
  const [profile, setProfileState] = useState(loadProfile);
  // Use sessionStorage so the modal shows every time user logs in (resets on tab close/new session)
  const [onboarded, setOnboarded] = useState(() => sessionStorage.getItem("screenai_onboarded") === "1");

  const saveProfile = useCallback((data) => {
    // data: { job_title, job_description, cv_text } or null
    if (data && Object.values(data).some((v) => v?.trim())) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      setProfileState(data);
    } else {
      localStorage.removeItem(STORAGE_KEY);
      setProfileState(null);
    }
  }, []);

  const markOnboarded = useCallback(() => {
    sessionStorage.setItem("screenai_onboarded", "1");
    setOnboarded(true);
  }, []);

  const clearProfile = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setProfileState(null);
  }, []);

  return (
    <ProfileContext.Provider value={{ profile, saveProfile, clearProfile, onboarded, markOnboarded }}>
      {children}
    </ProfileContext.Provider>
  );
}
