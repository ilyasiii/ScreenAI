import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import AppRoutes from "./AppRoutes.jsx";
import { ConfigNotice, ErrorBoundary } from "./components/StartupNotice.jsx";
import { SUPABASE_CONFIGURED } from "./config";
import { AuthProvider } from "./contexts/AuthContext.jsx";
import { ProfileProvider } from "./contexts/ProfileContext.jsx";
import "./index.css";

/*
 * Clickjacking guard. GitHub Pages cannot send X-Frame-Options or a CSP
 * frame-ancestors header, so refuse to render inside another site's frame:
 * a framed copy of the sign-in or capture pages could trick users into clicks.
 */
const framed = (() => {
  try {
    return window.top !== window.self;
  } catch {
    return true; // cross-origin parent: definitely framed
  }
})();

const root = createRoot(document.getElementById("root"));

if (framed) {
  try {
    window.top.location = window.self.location.href;
  } catch {
    // Sandboxed frame that blocks top navigation; just render nothing.
  }
} else if (!SUPABASE_CONFIGURED) {
  root.render(<ConfigNotice />);
} else {
  root.render(
    <StrictMode>
      <ErrorBoundary>
        <BrowserRouter>
          <AuthProvider>
            <ProfileProvider>
              <AppRoutes />
            </ProfileProvider>
          </AuthProvider>
        </BrowserRouter>
      </ErrorBoundary>
    </StrictMode>
  );
}
