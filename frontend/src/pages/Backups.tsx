import { t } from "../lib/i18n";import { useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { Button, Card, Field, Input, SectionHeader } from "../components/UI";

interface Preview {fingerprint: string;counts: Record<string, number>;}
const labels: Record<string, string> = { vpn_users: t("کاربران"), inbounds: t("اینباندها"), dns_tunnels: t("تونل‌های DNS"), nodes: t("نودها"), subscription_groups: t("گروه‌ها"), wireguard_peers: t("کاربران WireGuard"), plans: t("پلن‌ها") };

export default function Backups() {
  const { admin } = useAuth();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recovery, setRecovery] = useState("");
  async function saveFile(blob: Blob, name: string) {
    const url = URL.createObjectURL(blob),a = document.createElement("a");
    a.href = url;a.download = name;a.click();setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);try {await action();} catch (error) {toast.error(error instanceof Error ? error.message : t("عملیات انجام نشد."));} finally {setBusy(false);}
  }
  function formData() {
    if (!file) throw new Error(t("فایل بکاپ را انتخاب کنید."));
    if (password.length < 16) throw new Error(t("رمز بکاپ باید حداقل ۱۶ کاراکتر باشد."));
    const body = new FormData();body.append("file", file);body.append("password", password);return body;
  }
  if (!admin?.is_owner) return <p>{t("بکاپ و بازیابی فقط در دسترس مالک پنل است.")}</p>;
  return <div className="commerce-page">
    <SectionHeader title={t("بکاپ و بازیابی")} subtitle={t("از کاربران، کانفیگ‌ها، گروه‌ها، نودها و تنظیمات مسیریابی بکاپ رمزگذاری‌شده بگیرید؛ ربات لازم نیست.")} />
    <Card className="integration-card"><SectionHeader title={t("رمز بکاپ")} />
      <Field label={t("رمز فایل بکاپ")} hint={t("حداقل ۱۶ کاراکتر؛ برای دانلود، رمز دلخواه فایل جدید و برای بازیابی، رمز همان فایل را وارد کنید.")}><Input type="password" minLength={16} maxLength={256} autoComplete="new-password" value={password} onChange={(e) => {setPassword(e.target.value);setPreview(null);setConfirmed(false);}} /></Field>
      <Button disabled={password.length < 16 || busy} onClick={() => run(async () => {await saveFile(await api.download("/api/integrations/backups/download", { password }), `SpecterGate-${new Date().toISOString().slice(0, 10)}.sgbackup`);toast.success(t("بکاپ دانلود شد؛ رمز آن را نگه دارید."));})}>{t("دانلود بکاپ کاربران و کانفیگ‌ها")}</Button>
    </Card>
    <Card className="integration-card"><SectionHeader title={t("بازیابی از فایل")} subtitle={t("بازیابی، کاربران و کانفیگ‌های فعلی را با دادهٔ فایل جایگزین می‌کند. حساب ورود مدیر، آدرس پنل، دامنه‌های این نصب و توکن ربات فعلی حفظ می‌شوند.")} />
      <div className="commerce-form">
        <Field label={t("فایل بکاپ")} hint={t("فایل sgbackup با حداکثر اندازهٔ ۱۶ مگابایت.")}><Input type="file" accept=".sgbackup" onChange={(e) => {const item = e.target.files?.[0] || null;setPreview(null);setConfirmed(false);if (item && item.size > 16 * 1024 * 1024) {toast.error(t("فایل بیش از ۱۶ مگابایت است."));setFile(null);} else setFile(item);}} /></Field>
        <Button disabled={!file || busy || password.length < 16} onClick={() => run(async () => {setPreview(await api.upload<Preview>("/api/backups/inspect", formData()));setConfirmed(false);})}>{t("بررسی فایل و پیش‌نمایش")}</Button>
      </div>
      {preview && <div className="commerce-form">
        <div>{Object.entries(labels).map(([key, label]) => <p key={key}>{label}: <strong>{preview.counts[key] ?? 0}</strong></p>)}</div>
        <Field label={t("رمز ورود مالک برای تأیید بازیابی")}><Input type="password" autoComplete="current-password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} /></Field>
        <label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />{" " + t("جایگزینی کاربران و کانفیگ‌های فعلی را تأیید می‌کنم.") + ""}</label>
        <p className="field-hint">{t("قبل از تغییر، یک بکاپ بازگشت با همین رمز روی سرور ذخیره می‌شود. فایل‌های SSL و کلید خصوصی سرور WireGuard جزو بازیابی داده نیستند و باید روی مقصد موجود باشند. تاریخچهٔ نمودار مصرف پاک می‌شود؛ مجموع مصرف کاربران از بکاپ برمی‌گردد.")}</p>
        <Button variant="danger" disabled={!confirmed || !adminPassword || busy} onClick={() => run(async () => {
          const data = formData();data.append("admin_password", adminPassword);data.append("confirmation", "RESTORE");data.append("fingerprint", preview.fingerprint);
          const result = await api.upload<{rollback_id: string;runtime_warning: boolean;}>("/api/backups/restore", data);
          setRecovery(result.rollback_id);setPreview(null);setConfirmed(false);setAdminPassword("");
          toast.success(result.runtime_warning ? t("داده بازیابی شد؛ وضعیت هسته را بررسی کنید.") : t("بازیابی انجام شد؛ هسته تا حدود ۳۰ ثانیه همگام می‌شود."));
        })}>{t("بازیابی کاربران و کانفیگ‌ها")}</Button>
      </div>}
      {recovery && <Button disabled={busy} onClick={() => run(async () => saveFile(await api.download(`/api/backups/rollback/${recovery}`), "SpecterGate-before-restore.sgbackup"))}>{t("دانلود بکاپ قبل از بازیابی")}</Button>}
    </Card>
  </div>;
}
