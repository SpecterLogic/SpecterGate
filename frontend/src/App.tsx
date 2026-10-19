import { lazy, Suspense, useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./lib/auth";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const DnsTunnelsPage = lazy(() => import("./pages/DnsTunnels"));
const InboundsPage = lazy(() => import("./pages/Inbounds"));
const Login = lazy(() => import("./pages/Login"));
const NodesPage = lazy(() => import("./pages/Nodes"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const SubscriptionPage = lazy(() => import("./pages/Subscription"));
const UsersPage = lazy(() => import("./pages/Users"));
const Commerce = lazy(() => import("./pages/Commerce"));

function PermissionRoute({ permission, children }: { permission: string; children: React.ReactNode }) {
  const { admin } = useAuth();
  return admin?.permissions.includes(permission) ? children : <Navigate to="/" replace />;
}

function RouteFallback() {
  return (
    <div className="route-fallback">
      <span className="spinner-dot" />
      <span>در حال بارگذاری...</span>
    </div>
  );
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [pathname]);
  return null;
}

function ProtectedRoute() {
  const { admin, loading } = useAuth();
  if (loading) {
    return (
      <div className="app-splash">
        <span className="splash-mark">
          <svg viewBox="0 0 40 40" fill="none">
            <path d="M9 28V12l11 7 11-7v16" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M15 28v-6l5 3 5-3v6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" opacity=".55" />
          </svg>
        </span>
        <span>در حال آماده‌سازی پنل...</span>
      </div>
    );
  }
  if (!admin) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/s/:token" element={<SubscriptionPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route index element={<Dashboard />} />
              <Route path="/users" element={<UsersPage />} />
              <Route path="/admins" element={<PermissionRoute permission="admins.read"><Commerce key="admins" mode="admins" /></PermissionRoute>} />
              <Route path="/plans" element={<PermissionRoute permission="plans.read"><Commerce key="plans" mode="plans" /></PermissionRoute>} />
              <Route path="/subscriptions" element={<PermissionRoute permission="subscriptions.read"><Commerce key="subscriptions" mode="subscriptions" /></PermissionRoute>} />
              <Route path="/inbounds" element={<InboundsPage />} />
              <Route path="/dns-tunnels" element={<DnsTunnelsPage />} />
              <Route path="/nodes" element={<NodesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </>
  );
}
