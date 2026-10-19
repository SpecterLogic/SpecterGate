import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  ChevronLeft,
  CircleUserRound,
  LayoutDashboard,
  LogOut,
  Menu,
  RadioTower,
  Server,
  Settings,
  Users,
  X,
  Zap,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/format";
import type { XrayStatus } from "../lib/types";

const NAV_ITEMS = [
  { to: "/", label: "داشبورد", icon: LayoutDashboard, end: true },
  { to: "/users", label: "کاربران", icon: Users },
  { to: "/admins", label: "ادمین‌ها و نمایندگان", icon: CircleUserRound },
  { to: "/plans", label: "پلن‌های فروش", icon: Boxes },
  { to: "/subscriptions", label: "اشتراک‌های گروهی", icon: Users },
  { to: "/inbounds", label: "اینباندها", icon: Boxes },
  { to: "/dns-tunnels", label: "تونل‌های DNS", icon: RadioTower },
  { to: "/nodes", label: "نودها", icon: Server },
  { to: "/settings", label: "تنظیمات", icon: Settings },
];

const TITLES: Record<string, string> = {
  "/": "داشبورد",
  "/users": "مدیریت کاربران",
  "/admins": "ادمین‌ها و نمایندگان",
  "/plans": "پلن‌های فروش",
  "/subscriptions": "اشتراک‌های گروهی",
  "/inbounds": "اینباندها",
  "/dns-tunnels": "تونل‌های DNS",
  "/nodes": "نودها",
  "/settings": "تنظیمات پنل",
};

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={cn("brand", compact && "brand-compact")}>
      <span className="brand-mark" aria-hidden>
        <svg viewBox="0 0 40 40" fill="none">
          <path d="M9 28V12l11 7 11-7v16" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M15 28v-6l5 3 5-3v6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" opacity=".55" />
        </svg>
      </span>
      {!compact && (
        <span className="brand-text">
          <strong>SpecterGate</strong>
          <small>SpecterGate Panel</small>
        </span>
      )}
    </div>
  );
}

export default function Layout() {
  const { admin, logout } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const xray = useQuery({
    queryKey: ["xray-status"],
    queryFn: () => api.get<XrayStatus>("/api/xray/status"),
    refetchInterval: 30_000,
    retry: false,
    enabled: !!admin?.permissions.includes("xray.manage"),
  });

  const isHealthy = Boolean(xray.data?.running);
  const title = TITLES[location.pathname] ?? "SpecterGate";

  return (
    <div className="app-shell">
      <div
        className={cn("mobile-scrim", mobileOpen && "show")}
        onClick={() => setMobileOpen(false)}
        aria-hidden
      />
      <aside className={cn("sidebar", mobileOpen && "mobile-open")}>
        <div className="sidebar-top">
          <Brand />
          <button type="button" className="icon-btn mobile-close" onClick={() => setMobileOpen(false)} aria-label="بستن منو">
            <X size={19} />
          </button>
        </div>

        <div className="workspace-chip">
          <span className="workspace-icon">
            <Zap size={15} />
          </span>
          <div>
            <strong>فضای کاری</strong>
            <span>Production</span>
          </div>
          <ChevronLeft size={15} className="muted-icon" />
        </div>

        <nav className="nav">
          <span className="nav-caption">مدیریت</span>
          {NAV_ITEMS.filter(item => {
            const permission: Record<string, string> = { "/": "dashboard.read", "/users": "users.read", "/admins": "admins.read", "/plans": "plans.read", "/subscriptions": "subscriptions.read", "/inbounds": "inbounds.read", "/nodes": "nodes.read", "/dns-tunnels": "dns.read", "/settings": "settings.read" };
            return admin?.permissions.includes(permission[item.to]);
          }).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => cn("nav-item", isActive && "active")}
              >
                <Icon size={19} strokeWidth={1.9} />
                <span>{item.label}</span>
                <i className="nav-indicator" />
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />

        <div className={cn("core-status", isHealthy ? "is-online" : "is-offline")}>
          <span className="pulse-dot" />
          <div>
            <strong>هستهٔ Xray</strong>
            <span>{isHealthy ? "در حال اجرا" : xray.data?.binary_available ? "آماده به اجرا" : "نصب نشده"}</span>
          </div>
          <Activity size={18} />
        </div>

        <div className="sidebar-user">
          <span className="avatar">{admin?.username?.slice(0, 2).toUpperCase() ?? "HM"}</span>
          <div className="sidebar-user-info">
            <strong>{admin?.username ?? "مدیر"}</strong>
            <span>{{ superadmin: "مدیر کل", admin: "مدیر", reseller: "نماینده", support: "پشتیبان", viewer: "بازدیدکننده" }[admin?.role ?? "viewer"]}</span>
          </div>
          <button type="button" className="icon-btn" onClick={logout} title="خروج" aria-label="خروج">
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <div className="main-wrap">
        <header className="topbar">
          <div className="topbar-start">
            <button type="button" className="icon-btn menu-btn" onClick={() => setMobileOpen(true)} aria-label="باز کردن منو">
              <Menu size={21} />
            </button>
            <div className="page-heading">
              <span className="eyebrow">پنل مدیریت</span>
              <h1>{title}</h1>
            </div>
          </div>
          <div className="topbar-actions">
            <span className={cn("core-chip", isHealthy ? "online" : "offline")}>
              <i />
              {isHealthy ? "هسته متصل" : "هسته متوقف"}
            </span>
            <div className="topbar-avatar" title={admin?.username}>
              <CircleUserRound size={20} />
            </div>
          </div>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
