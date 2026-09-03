import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { ProtectedRoute, PublicOnly } from "./components/RouteGuards.jsx";

/*
 * Routes are split so each one ships only what it needs. Previously every
 * visitor downloaded the entire app in one chunk: the marketing landing page
 * pulled in the screen-capture workspace, and the workspace pulled in the
 * landing page's stylesheet. react-markdown in particular is a large dependency
 * that only two of the six routes ever touch.
 */
const LandingPage = lazy(() => import("./pages/LandingPage.jsx"));
const AuthPage = lazy(() => import("./pages/AuthPage.jsx"));
const ResetPasswordPage = lazy(() => import("./pages/ResetPasswordPage.jsx"));
const Workspace = lazy(() => import("./App.jsx"));
const InterviewPage = lazy(() => import("./pages/InterviewPage.jsx"));
const HistoryPage = lazy(() => import("./pages/HistoryPage.jsx"));

export default function AppRoutes() {
  return (
    // The guards already render null while auth resolves, so an empty fallback
    // keeps the transition from flashing a second loader.
    <Suspense fallback={null}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/auth" element={<PublicOnly><AuthPage /></PublicOnly>} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/app" element={<ProtectedRoute><Workspace /></ProtectedRoute>} />
        <Route path="/interview" element={<ProtectedRoute><InterviewPage /></ProtectedRoute>} />
        <Route path="/history" element={<ProtectedRoute><HistoryPage /></ProtectedRoute>} />
      </Routes>
    </Suspense>
  );
}
