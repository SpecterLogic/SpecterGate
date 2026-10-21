import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeftRight,
  Boxes,
  ChevronLeft,
  ChevronDown,
  CircleUserRound,
  LayoutDashboard,
  LogOut,
  Menu,
  RadioTower,
  Globe,
  Server,
  Settings,
  ShieldCheck,
  Users,
  X,
  Zap,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/format";
import type { XrayStatus } from "../lib/types";

const NAV_ITEMS = [
  { to: "/", label: "داشبورد", icon: LayoutDashboard, end: true, group: "نمای کلی" },
  { to: "/users", label: "کاربران", icon: Users, group: "کاربران و اشتراک‌ها" },
  { to: "/subscriptions", label: "اشتراک‌های گروهی", icon: Users, group: "کاربران و اشتراک‌ها" },
  { to: "/plans", label: "پلن‌ها", icon: Boxes, group: "کاربران و اشتراک‌ها" },
  { to: "/inbounds", label: "ورودی‌ها (Inbounds)", icon: Boxes, group: "شبکه" },
  { to: "/outbounds", label: "خروجی‌ها (Outbounds)", icon: Server, group: "شبکه" },
  { to: "/routing", label: "قوانین مسیریابی", icon: RadioTower, group: "شبکه" },
  { to: "/dns-hosts", label: "هاست‌ها و DNS", icon: Globe, group: "شبکه" },
  { to: "/certificates", label: "گواهی‌های SSL", icon: ShieldCheck, group: "شبکه" },
  { to: "/diagnostics", label: "عیب‌یابی و بالانسر", icon: ArrowLeftRight, group: "شبکه" },
  { to: "/dns-tunnels", label: "تونل‌های DNS", icon: RadioTower, group: "شبکه" },
  { to: "/nodes", label: "نودها", icon: Server, group: "شبکه" },
  { to: "/core", label: "هستهٔ Xray", icon: Activity, group: "شبکه" },
  { to: "/admins", label: "مدیران و مجوزها", icon: CircleUserRound, group: "مدیریت پنل" },
  { to: "/security", label: "امنیت و Fail2ban", icon: ShieldCheck, group: "مدیریت پنل" },
  { to: "/backups", label: "بکاپ و بازیابی", icon: Boxes, group: "مدیریت پنل" },
  { to: "/integrations", label: "ربات تلگرام", icon: Settings, group: "مدیریت پنل" },
  { to: "/settings", label: "تنظیمات عمومی", icon: Settings, group: "مدیریت پنل" },
  { to: "/activity", label: "گزارش فعالیت", icon: Activity, group: "مدیریت پنل" },
  { to: "/account", label: "حساب من", icon: CircleUserRound, group: "مدیریت پنل" },
];

const TITLES: Record<string, string> = {
  "/": "داشبورد",
  "/users": "مدیریت کاربران",
  "/backups": "بکاپ و بازیابی",
  "/routing": "قوانین مسیریابی",
  "/dns-hosts": "هاست‌ها و DNS جامع",
  "/certificates": "مدیریت گواهی‌های SSL",
  "/diagnostics": "ابزار عیب‌یابی و بالانسر",
  "/outbounds": "خروجی‌ها",
  "/outbounds/warp": "حساب WARP",
  "/security": "امنیت و Fail2ban",
  "/core": "هستهٔ Xray",
  "/activity": "گزارش فعالیت",
  "/account": "حساب من",
  "/admins": "ادمین‌ها و نمایندگان",
  "/plans": "پلن‌های فروش",
  "/subscriptions": "اشتراک‌های گروهی",
  "/inbounds": "اینباندها",
  "/dns-tunnels": "تونل‌های DNS",
  "/nodes": "نودها",
  "/settings": "تنظیمات پنل",
  "/integrations": "ربات و بکاپ",
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
  const [openGroup, setOpenGroup] = useState("");

  useEffect(() => {
    setMobileOpen(false);
    const active = NAV_ITEMS.find(item => item.to === location.pathname || (item.to !== "/" && location.pathname.startsWith(item.to + "/")));
    setOpenGroup(active?.group || "");
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
  const visibleItems = NAV_ITEMS.filter(item => {
    if (item.to === "/account") return true;
    if (["/integrations", "/backups"].includes(item.to)) return !!admin?.is_owner;
    const permissions: Record<string, string> = { "/": "dashboard.read", "/users": "users.read", "/admins": "admins.read", "/plans": "plans.read", "/subscriptions": "subscriptions.read", "/inbounds": "inbounds.read", "/outbounds": "routing.read", "/routing": "routing.read", "/security": "security.read", "/nodes": "nodes.read", "/dns-tunnels": "dns.read", "/settings": "settings.read", "/core": "xray.manage", "/activity": "audit.read" };
    return admin?.permissions.includes(permissions[item.to]);
  });

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

        <nav className="nav" aria-label="بخش‌های پنل">
          {["نمای کلی", "کاربران و اشتراک‌ها", "شبکه", "مدیریت پنل"].map(group => {
            const items = visibleItems.filter(item => item.group === group);
            return items.length ? <div className="nav-group" key={group}>
              {group === "نمای کلی" ? <span className="nav-caption">{group}</span> : <button className="nav-caption nav-group-toggle" type="button" aria-expanded={openGroup === group} onClick={() => setOpenGroup(openGroup === group ? "" : group)}><span>{group}</span><ChevronDown size={14} className={openGroup === group ? "expanded" : ""} /></button>}
              {(group === "نمای کلی" || openGroup === group) && items.map((item) => {
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
          })}</div> : null; })}
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
