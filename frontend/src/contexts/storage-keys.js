/**
 * Browser storage keys that hold per-user data, in one place so sign-out can
 * wipe all of them.
 */
export const PROFILE_KEY = "screenai_profile";
export const ONBOARDED_KEY = "screenai_onboarded";
export const CREDENTIALS_KEY = "screenai_api_keys";

/** Remove everything personal this app keeps in the browser. */
export function clearUserStorage() {
  try {
    localStorage.removeItem(PROFILE_KEY);
    sessionStorage.removeItem(ONBOARDED_KEY);
    sessionStorage.removeItem(CREDENTIALS_KEY);
  } catch {
    // Storage disabled; nothing was stored.
  }
}
