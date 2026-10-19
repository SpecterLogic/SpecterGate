import clsx, { type ClassValue } from "clsx";

export const cn = (...inputs: ClassValue[]) => clsx(inputs);

const faNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
let datePreferences: { timeZone: string; calendar: string } = { timeZone: 'Asia/Tehran', calendar: 'persian' };
let faDate = new Intl.DateTimeFormat("fa-IR", { ...datePreferences, year: "numeric", month: "short", day: "numeric" });
let faDateTime = new Intl.DateTimeFormat("fa-IR", {
  ...datePreferences,
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function configureDatePreferences(timeZone: string, calendar: string) {
  if (datePreferences.timeZone === timeZone && datePreferences.calendar === calendar) return;
  try {
    const next = { timeZone, calendar };
    const date = new Intl.DateTimeFormat('fa-IR', { ...next, year: 'numeric', month: 'short', day: 'numeric' });
    const datetime = new Intl.DateTimeFormat('fa-IR', { ...next, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    datePreferences = next; faDate = date; faDateTime = datetime;
  } catch { /* Retain valid defaults if a browser cannot render a preference. */ }
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return faNumber.format(value);
}

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes === null || bytes === undefined) return "نامحدود";
  if (bytes === 0) return "\u2066۰ B\u2069";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  const formatted = new Intl.NumberFormat("fa-IR", {
    maximumFractionDigits: index === 0 ? 0 : digits,
    minimumFractionDigits: 0,
  }).format(value);
  // LTR isolates keep the unit after the number inside RTL text.
  return `\u2066${formatted} ${units[index]}\u2069`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "بدون انقضا";
  return faDate.format(new Date(value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return faDateTime.format(new Date(value));
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const diff = new Date(value).getTime() - Date.now();
  const seconds = Math.round(diff / 1000);
  const formatter = new Intl.RelativeTimeFormat("fa-IR", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  const days = Math.round(hours / 24);
  if (Math.abs(days) < 30) return formatter.format(days, "day");
  const months = Math.round(days / 30);
  return formatter.format(months, "month");
}

export function daysLeft(value: string | null | undefined): number | null {
  if (!value) return null;
  return Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
}

export function toDateTimeLocal(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

export function fromDateTimeLocal(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}

export function toLocalDate(value: string): string {
  return new Intl.DateTimeFormat("fa-IR", { ...datePreferences, weekday: "short" }).format(new Date(`${value}T12:00:00`));
}

export function todayLabel(): string {
  return new Intl.DateTimeFormat("fa-IR", {
    ...datePreferences,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());
}

export function statusLabel(status: string): string {
  return (
    {
      active: "فعال",
      expired: "منقضی",
      limited: "اتمام حجم",
      disabled: "غیرفعال",
      online: "آنلاین",
      offline: "آفلاین",
      unknown: "نامشخص",
    } as Record<string, string>
  )[status] ?? status;
}

export function protocolLabel(protocol: string): string {
  return (
    {
      vless: "VLESS",
      vmess: "VMess",
      trojan: "Trojan",
      shadowsocks: "Shadowsocks",
    } as Record<string, string>
  )[protocol] ?? protocol;
}
