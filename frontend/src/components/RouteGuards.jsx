/**
 * Route guards.
 *
 * Lives outside main.jsx so that entry file holds only the render call — a
 * module that defines components but exports none cannot be hot-reloaded.
 */
import { Navigate } from "react-router-dom";

import { useAuth } from "../contexts/auth-context";
import { useProfile } from "../contexts/profile-context";
import ProfileModal from "./ProfileModal";

/** Signed-in only. Unonboarded users get the profile prompt first. */
export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const { onboarded } = useProfile();

  if (loading) return null;
  if (!user) return <Navigate to="/auth" replace />;
  if (!onboarded) return <ProfileModal />;
  return children;
}

/** Signed-out only. Signed-in users are bounced to the app. */
export function PublicOnly({ children }) {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (user) return <Navigate to="/app" replace />;
  return children;
}
