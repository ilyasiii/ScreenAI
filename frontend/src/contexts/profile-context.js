/**
 * Profile context object and its hook. Split from ProfileProvider for the same
 * Fast Refresh reason as auth-context.js.
 */
import { createContext, useContext } from "react";

export const ProfileContext = createContext(null);

export function useProfile() {
  const context = useContext(ProfileContext);
  if (!context) throw new Error("useProfile must be used within ProfileProvider");
  return context;
}
