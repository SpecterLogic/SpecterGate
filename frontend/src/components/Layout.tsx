import LanguageSelect from "./LanguageSelect";
import InstallApp from "./InstallApp";
import { t } from "../lib/i18n";import { useEffect, useState } from "react";
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
  Zap } from
"lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/format";
import type { XrayStatus } from "../lib/types";

const NAV_ITEMS = [
{ to: "/", label: t("داشبورد"), icon: LayoutDashboard, end: true, group: t("نمای کلی") },
{ to: "/users", label: t("کاربران"), icon: Users, group: t("کاربران و اشتراک‌ها") },
{ to: "/subscriptions", label: t("اشتراک‌های گروهی"), icon: Users, group: t("کاربران و اشتراک‌ها") },
{ to: "/plans", label: t("پلن‌ها"), icon: Boxes, group: t("کاربران و اشتراک‌ها") },
{ to: "/inbounds", label: t("ورودی‌ها (Inbounds)"), icon: Boxes, group: t("شبکه") },
{ to: "/amneziawg", label: "AmneziaWG", icon: ShieldCheck, group: t("شبکه") },
{ to: "/sessions", label: t("IPهای آنلاین"), icon: Activity, group: t("کاربران و اشتراک‌ها") },
{ to: "/outbounds", label: t("خروجی‌ها (Outbounds)"), icon: Server, group: t("شبکه") },
{ to: "/routing", label: t("قوانین مسیریابی"), icon: RadioTower, group: t("شبکه") },
{ to: "/dns-hosts", label: t("هاست‌ها و DNS"), icon: Globe, group: t("شبکه") },
{ to: "/certificates", label: t("گواهی‌های SSL"), icon: ShieldCheck, group: t("شبکه") },
{ to: "/diagnostics", label: t("عیب‌یابی و بالانسر"), icon: ArrowLeftRight, group: t("شبکه") },
{ to: "/dns-tunnels", label: t("تونل‌های DNS"), icon: RadioTower, group: t("شبکه") },
{ to: "/nodes", label: t("نودها"), icon: Server, group: t("شبکه") },
{ to: "/core", label: t("هستهٔ Xray"), icon: Activity, group: t("شبکه") },
{ to: "/admins", label: t("مدیران و مجوزها"), icon: CircleUserRound, group: t("مدیریت پنل") },
{ to: "/security", label: t("امنیت و Fail2ban"), icon: ShieldCheck, group: t("مدیریت پنل") },
{ to: "/backups", label: t("بکاپ و بازیابی"), icon: Boxes, group: t("مدیریت پنل") },
{ to: "/integrations", label: t("ربات تلگرام"), icon: Settings, group: t("مدیریت پنل") },
{ to: "/settings", label: t("تنظیمات عمومی"), icon: Settings, group: t("مدیریت پنل") },
{ to: "/activity", label: t("گزارش فعالیت"), icon: Activity, group: t("مدیریت پنل") },
{ to: "/account", label: t("حساب من"), icon: CircleUserRound, group: t("مدیریت پنل") }];


const TITLES: Record<string, string> = {
  "/": t("داشبورد"),
  "/users": t("مدیریت کاربران"),
  "/backups": t("بکاپ و بازیابی"),
  "/routing": t("قوانین مسیریابی"),
  "/dns-hosts": t("هاست‌ها و DNS جامع"),
  "/certificates": t("مدیریت گواهی‌های SSL"),
  "/diagnostics": t("ابزار عیب‌یابی و بالانسر"),
  "/outbounds": t("خروجی‌ها"),
  "/outbounds/warp": t("حساب WARP"),
  "/security": t("امنیت و Fail2ban"),
  "/core": t("هستهٔ Xray"),
  "/activity": t("گزارش فعالیت"),
  "/account": t("حساب من"),
  "/admins": t("ادمین‌ها و نمایندگان"),
  "/plans": t("پلن‌های فروش"),
  "/subscriptions": t("اشتراک‌های گروهی"),
  "/inbounds": t("اینباندها"),
  "/amneziawg": "AmneziaWG",
  "/sessions": t("IPهای آنلاین"),
  "/dns-tunnels": t("تونل‌های DNS"),
  "/nodes": t("نودها"),
  "/settings": t("تنظیمات پنل"),
  "/integrations": t("ربات و بکاپ")
};

export function Brand({ compact = false }: {compact?: boolean;}) {
  return (
    <div className={cn("brand", compact && "brand-compact")}>
      <span className="brand-mark" aria-hidden>
        <svg viewBox="0 0 40 40" fill="none">
          <path d="M9 28V12l11 7 11-7v16" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M15 28v-6l5 3 5-3v6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" opacity=".55" />
        </svg>
      </span>
      {!compact &&
      <span className="brand-text">
          <strong>SpecterGate</strong>
          <small>SpecterGate Panel</small>
        </span>
      }
    </div>);

}

export default function Layout() {
  const { admin, logout } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openGroup, setOpenGroup] = useState("");

  useEffect(() => {
    setMobileOpen(false);
    const active = NAV_ITEMS.find((item) => item.to === location.pathname || item.to !== "/" && location.pathname.startsWith(item.to + "/"));
    setOpenGroup(active?.group || "");
  }, [location.pathname]);

  const xray = useQuery({
    queryKey: ["xray-status"],
    queryFn: () => api.get<XrayStatus>("/api/xray/status"),
    refetchInterval: 30_000,
    retry: false,
    enabled: !!admin?.permissions.includes("xray.manage")
  });

  const isHealthy = Boolean(xray.data?.running);
  const title = TITLES[location.pathname] ?? "SpecterGate";
  const visibleItems = NAV_ITEMS.filter((item) => {
    if (item.to === "/account") return true;
    if (["/integrations", "/backups"].includes(item.to)) return !!admin?.is_owner;
    const permissions: Record<string, string> = { "/": "dashboard.read", "/users": "users.read", "/admins": "admins.read", "/plans": "plans.read", "/subscriptions": "subscriptions.read", "/inbounds": "inbounds.read", "/amneziawg": "users.read", "/sessions": "users.read", "/dns-hosts": "dns.read", "/certificates": "settings.read", "/diagnostics": "routing.read", "/outbounds": "routing.read", "/routing": "routing.read", "/security": "security.read", "/nodes": "nodes.read", "/dns-tunnels": "dns.read", "/settings": "settings.read", "/core": "xray.manage", "/activity": "audit.read" };
    return admin?.permissions.includes(permissions[item.to]);
  });

  return (
    <div className="app-shell">
      <div
        className={cn("mobile-scrim", mobileOpen && "show")}
        onClick={() => setMobileOpen(false)}
        aria-hidden />

      <aside className={cn("sidebar", mobileOpen && "mobile-open")}>
        <div className="sidebar-top">
          <Brand />
          <button type="button" className="icon-btn mobile-close" onClick={() => setMobileOpen(false)} aria-label={t("بستن منو")}>
            <X size={19} />
          </button>
        </div>

        <div className="workspace-chip">
          <span className="workspace-icon">
            <Zap size={15} />
          </span>
          <div>
            <strong>{t("فضای کاری")}</strong>
            <span>Production</span>
          </div>
          <ChevronLeft size={15} className="muted-icon" />
        </div>

        <nav className="nav" aria-label={t("بخش‌های پنل")}>
          {[t("نمای کلی"), t("کاربران و اشتراک‌ها"), t("شبکه"), t("مدیریت پنل")].map((group) => {
            const items = visibleItems.filter((item) => item.group === group);
            return items.length ? <div className="nav-group" key={group}>
              {group === t("نمای کلی") ? <span className="nav-caption">{group}</span> : <button className="nav-caption nav-group-toggle" type="button" aria-expanded={openGroup === group} onClick={() => setOpenGroup(openGroup === group ? "" : group)}><span>{group}</span><ChevronDown size={14} className={openGroup === group ? "expanded" : ""} /></button>}
              {(group === t("نمای کلی") || openGroup === group) && items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => cn("nav-item", isActive && "active")}>

                <Icon size={19} strokeWidth={1.9} />
                <span>{item.label}</span>
                <i className="nav-indicator" />
              </NavLink>);

              })}</div> : null;})}
        </nav>

        <div className="sidebar-spacer" />

        <div className={cn("core-status", isHealthy ? "is-online" : "is-offline")}>
          <span className="pulse-dot" />
          <div>
            <strong>{t("هستهٔ Xray")}</strong>
            <span>{isHealthy ? t("در حال اجرا") : xray.data?.binary_available ? t("آماده به اجرا") : t("نصب نشده")}</span>
          </div>
          <Activity size={18} />
        </div>

        <div className="sidebar-user">
          <span className="avatar">{admin?.username?.slice(0, 2).toUpperCase() ?? "HM"}</span>
          <div className="sidebar-user-info">
            <strong>{admin?.username ?? t("مدیر")}</strong>
            <span>{{ superadmin: t("مدیر کل"), admin: t("مدیر"), reseller: t("نماینده"), support: t("پشتیبان"), viewer: t("بازدیدکننده") }[admin?.role ?? "viewer"]}</span>
          </div>
          <button type="button" className="icon-btn" onClick={logout} title={t("خروج")} aria-label={t("خروج")}>
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <div className="main-wrap">
        <header className="topbar">
          <div className="topbar-start">
            <button type="button" className="icon-btn menu-btn" onClick={() => setMobileOpen(true)} aria-label={t("باز کردن منو")}>
              <Menu size={21} />
            </button>
            <div className="page-heading">
              <span className="eyebrow">{t("پنل مدیریت")}</span>
              <h1>{title}</h1>
            </div>
          </div>
          <div className="topbar-actions"><LanguageSelect /><InstallApp />
            <span className={cn("core-chip", isHealthy ? "online" : "offline")}>
              <i />
              {isHealthy ? t("هسته متصل") : t("هسته متوقف")}
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
    </div>);

}
