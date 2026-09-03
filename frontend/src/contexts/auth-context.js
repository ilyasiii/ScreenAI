/**
 * Auth context object and its hook.
 *
 * Kept apart from AuthContext.jsx so that file exports only a component. Mixing
 * component and non-component exports in one module breaks React Fast Refresh:
 * editing the provider forces a full reload instead of a hot swap, dropping all
 * app state.
 */
import { createContext, useContext } from "react";

export const AuthContext = createContext(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
