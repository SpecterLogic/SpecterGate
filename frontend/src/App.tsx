import { lazy, Suspense, useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./lib/auth";
import { useQuery } from '@tanstack/react-query';
import { api } from './lib/api';
import { configureDatePreferences } from './lib/format';

const Dashboard = lazy(() => import("./pages/Dashboard"));
const DnsTunnelsPage = lazy(() => import("./pages/DnsTunnels"));
const InboundsPage = lazy(() => import("./pages/Inbounds"));
const Login = lazy(() => import("./pages/Login"));
const NodesPage = lazy(() => import("./pages/Nodes"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const SubscriptionPage = lazy(() => import("./pages/Subscription"));
const UsersPage = lazy(() => import("./pages/Users"));
const Commerce = lazy(() => import("./pages/Commerce"));
const Integrations = lazy(() => import("./pages/Integrations"));
const Backups = lazy(() => import("./pages/Backups"));
const SecurityPage = lazy(() => import("./pages/Security"));
const Outbounds = lazy(() => import("./pages/Outbounds"));
const RoutingPage = lazy(() => import("./pages/Routing"));
const DnsHostsPage = lazy(() => import("./pages/DnsHosts").then(m => ({ default: m.DnsHosts })));
const CertificatesPage = lazy(() => import("./pages/Certificates").then(m => ({ default: m.Certificates })));
const DiagnosticsPage = lazy(() => import("./pages/Diagnostics").then(m => ({ default: m.Diagnostics })));

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
  const { admin } = useAuth();
  const preferences = useQuery({ queryKey: ['display-preferences'], queryFn: () => api.get<{time_zone: string; calendar: string}>('/api/display-preferences'), enabled: !!admin });
  configureDatePreferences(preferences.data?.time_zone || 'Asia/Tehran', preferences.data?.calendar || 'persian');
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
              <Route path="/integrations" element={<PermissionRoute permission="settings.manage"><Integrations /></PermissionRoute>} />
              <Route path="/backups" element={<PermissionRoute permission="settings.manage"><Backups /></PermissionRoute>} />
              <Route path="/routing" element={<PermissionRoute permission="routing.read"><RoutingPage /></PermissionRoute>} />
              <Route path="/outbounds" element={<PermissionRoute permission="routing.read"><Outbounds /></PermissionRoute>} />
              <Route path="/outbounds/warp" element={<PermissionRoute permission="routing.read"><RoutingPage key="warp" mode="warp" /></PermissionRoute>} />
              <Route path="/security" element={<PermissionRoute permission="security.read"><SecurityPage /></PermissionRoute>} />
              <Route path="/core" element={<PermissionRoute permission="xray.manage"><SettingsPage key="core" section="xray" /></PermissionRoute>} />
              <Route path="/activity" element={<PermissionRoute permission="audit.read"><SettingsPage key="activity" section="audit" /></PermissionRoute>} />
              <Route path="/account" element={<SettingsPage key="account" section="security" />} />
              <Route path="/plans" element={<PermissionRoute permission="plans.read"><Commerce key="plans" mode="plans" /></PermissionRoute>} />
              <Route path="/subscriptions" element={<PermissionRoute permission="subscriptions.read"><Commerce key="subscriptions" mode="subscriptions" /></PermissionRoute>} />
              <Route path="/inbounds" element={<InboundsPage />} />
              <Route path="/dns-hosts" element={<PermissionRoute permission="dns.read"><DnsHostsPage /></PermissionRoute>} />
              <Route path="/certificates" element={<PermissionRoute permission="settings.read"><CertificatesPage /></PermissionRoute>} />
              <Route path="/diagnostics" element={<PermissionRoute permission="routing.read"><DiagnosticsPage /></PermissionRoute>} />
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
