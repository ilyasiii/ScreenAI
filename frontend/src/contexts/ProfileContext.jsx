import { useCallback, useState } from "react";

import { useAuth } from "./auth-context";
import { ProfileContext } from "./profile-context";
import { ONBOARDED_KEY, PROFILE_KEY } from "./storage-keys";

/*
 * The profile holds a CV and job details, so it is personal data. It is
 * stored tagged with the owning user's id and only ever surfaced for that
 * user: on a shared computer, the next person to sign in does not inherit the
 * previous person's CV. Sign-out also wipes it (see AuthContext).
 */

const PROFILE_FIELDS = ["job_title", "job_description", "cv_text"];

function loadStored() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== "object") return null;
    if ("owner" in parsed) return parsed;
    // Saved by an earlier version, before profiles carried an owner. Adopted
    // by whoever is signed in now, and tagged with their id on the next save.
    if (PROFILE_FIELDS.some((field) => field in parsed)) return { owner: null, data: parsed };
    return null;
  } catch {
    return null;
  }
}

function loadOnboarded() {
  try {
    return sessionStorage.getItem(ONBOARDED_KEY);
  } catch {
    return null;
  }
}

function removeStored() {
  try {
    localStorage.removeItem(PROFILE_KEY);
  } catch {
    // Storage disabled; nothing was stored.
  }
}

export function ProfileProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;

  // { owner, data } — data is only exposed while `owner` is the current user.
  const [stored, setStored] = useState(loadStored);
  // Holds the id of the user who completed onboarding in this tab. The modal
  // shows once per tab session, and again for a different user.
  const [onboardedFor, setOnboardedFor] = useState(loadOnboarded);

  // When the signed-in user changes (sign-in, sign-out, switching accounts),
  // re-read storage instead of trusting what is in memory: sign-out has
  // already wiped storage, and that must take effect without a reload.
  const [seenUserId, setSeenUserId] = useState(userId);
  if (seenUserId !== userId) {
    setSeenUserId(userId);
    setStored(loadStored());
    setOnboardedFor(loadOnboarded());
  }

  const owned = Boolean(userId) && (stored?.owner === userId || stored?.owner === null);
  const profile = owned ? stored.data : null;
  const onboarded = Boolean(userId) && onboardedFor === userId;

  const saveProfile = useCallback(
    (data) => {
      // data: { job_title, job_description, cv_text } or null
      if (userId && data && Object.values(data).some((v) => v?.trim())) {
        const next = { owner: userId, data };
        try {
          localStorage.setItem(PROFILE_KEY, JSON.stringify(next));
        } catch {
          // Storage full or disabled: keep it for this page load only.
        }
        setStored(next);
      } else {
        removeStored();
        setStored(null);
      }
    },
    [userId]
  );

  const markOnboarded = useCallback(() => {
    if (!userId) return;
    try {
      sessionStorage.setItem(ONBOARDED_KEY, userId);
    } catch {
      // Private mode with storage disabled; the in-memory flag still works.
    }
    setOnboardedFor(userId);
  }, [userId]);

  return (
    <ProfileContext.Provider value={{ profile, saveProfile, onboarded, markOnboarded }}>
      {children}
    </ProfileContext.Provider>
  );
}
