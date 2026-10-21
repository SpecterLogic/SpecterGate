import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { Admin } from "../lib/types";
import { Button, Card, Field, Input, Select, SectionHeader, Toggle, ConfirmDialog, Spinner } from "../components/UI";

interface Config { enabled: boolean; owner_id: number | null; backup_enabled: boolean; backup_hours: number; token_configured: boolean; backup_password_configured: boolean; last_backup_at: string | null }
interface Binding { telegram_user_id: number; admin_id: number; allow_create: boolean }

export default function Integrations() {
  const { admin } = useAuth();
  const toast = useToast();
  const cache = useQueryClient();
  const [form, setForm] = useState({ enabled: false, owner_id: "", backup_enabled: false, backup_hours: "24", bot_token: "", backup_password: "" });
  const [binding, setBinding] = useState({ telegram_user_id: "", admin_id: "", allow_create: false });
  const [removing, setRemoving] = useState(false);
  const config = useQuery({ queryKey: ["telegram-config"], queryFn: () => api.get<Config>("/api/integrations/telegram"), enabled: !!admin?.is_owner });
  const admins = useQuery({ queryKey: ["admins"], queryFn: () => api.get<Admin[]>("/api/admins"), enabled: !!admin?.is_owner });
  const bindings = useQuery({ queryKey: ["telegram-bindings"], queryFn: () => api.get<Binding[]>("/api/integrations/telegram/admins"), enabled: !!admin?.is_owner });
  useEffect(() => { if (config.data) setForm({ enabled: config.data.enabled, owner_id: String(config.data.owner_id ?? ""), backup_enabled: config.data.backup_enabled, backup_hours: String(config.data.backup_hours), bot_token: "", backup_password: "" }); }, [config.data]);
  const action = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => { setForm(current => ({ ...current, bot_token: "", backup_password: "" })); cache.invalidateQueries({ queryKey: ["telegram-config"] }); cache.invalidateQueries({ queryKey: ["telegram-bindings"] }); toast.success("عملیات انجام شد."); setRemoving(false); }, onError: (e: Error) => toast.error(e.message) });
  function save(e: FormEvent) {
    e.preventDefault();
    const body = { enabled: form.enabled, backup_enabled: form.backup_enabled, backup_hours: Number(form.backup_hours), ...(form.owner_id ? { owner_id: Number(form.owner_id) } : {}), ...(form.bot_token ? { bot_token: form.bot_token } : {}), ...(form.backup_password ? { backup_password: form.backup_password } : {}) };
    action.mutate(() => api.put("/api/integrations/telegram", body));
  }
  if (!admin?.is_owner) return <p>این بخش فقط در دسترس مالک پنل است.</p>;
  if (config.isLoading) return <Spinner />;
  if (config.error) return <p role="alert">{config.error.message}</p>;
  return <div className="commerce-page">
    <SectionHeader title="ربات تلگرام" subtitle="تنظیم ربات، ساخت کاربر از تلگرام و ارسال بکاپ خودکار به مالک." action={<Link className="text-link" to="/backups">بکاپ و بازیابی از فایل ←</Link>} />
    <Card className="integration-card"><SectionHeader title="اتصال ربات تلگرام" />
      <form onSubmit={save} className="commerce-form">
        <Field label="توکن ربات" hint={config.data?.token_configured ? "توکن ذخیره شده است؛ برای حفظ آن خالی بگذارید." : "ربات خودتان را با BotFather بسازید و توکن را اینجا وارد کنید."}><Input type="password" autoComplete="new-password" value={form.bot_token} onChange={e => setForm({ ...form, bot_token: e.target.value })} /></Field>
        <Field label="شناسه عددی تلگرام مالک" hint="شناسه حساب شخصی مالک؛ نام کاربری یا شناسه گروه پذیرفته نمی‌شود."><Input type="number" min="1" value={form.owner_id} onChange={e => setForm({ ...form, owner_id: e.target.value })} /></Field>
        <Field label="رمز رمزگذاری بکاپ" hint={config.data?.backup_password_configured ? "رمز قبلاً ذخیره شده؛ مقدار خالی آن را تغییر نمی‌دهد. نسخه‌ای امن از رمز نزد خود نگه دارید." : "حداقل ۱۶ کاراکتر؛ برای بازیابی بکاپ لازم است."}><Input type="password" minLength={16} maxLength={256} autoComplete="new-password" value={form.backup_password} onChange={e => setForm({ ...form, backup_password: e.target.value })} /></Field>
        <Field label="فاصله بکاپ خودکار (ساعت)"><Input type="number" min="1" max="168" required value={form.backup_hours} onChange={e => setForm({ ...form, backup_hours: e.target.value })} /></Field>
        <Toggle checked={form.enabled} onChange={enabled => setForm({ ...form, enabled })} label="ربات فعال" />
        <Toggle checked={form.backup_enabled} onChange={backup_enabled => setForm({ ...form, backup_enabled })} label="ارسال دوره‌ای بکاپ رمزگذاری‌شده فقط برای مالک" />
        <div className="commerce-form-footer"><Button type="submit" loading={action.isPending}>ذخیره تنظیمات</Button><Button type="button" variant="outline" disabled={!config.data?.token_configured || action.isPending} onClick={() => action.mutate(async () => { const result = await api.post<{ username: string }>("/api/integrations/telegram/check"); toast.success(`ربات تأیید شد: ${result.username}`); })}>بررسی اتصال</Button></div>
      </form>
      <p className="field-hint">مالک و مدیران مجاز باید ابتدا گفت‌وگوی خصوصی ربات را باز کنند و /start بزنند. توکن در مرورگر بازیابی نمی‌شود و در دیتابیس رمزگذاری‌شده نگهداری می‌شود.</p>
    </Card>
    <Card className="integration-card"><SectionHeader title="ارسال بکاپ با ربات" subtitle={config.data?.last_backup_at ? `آخرین ارسال موفق: ${new Date(config.data.last_backup_at).toLocaleString("fa-IR")}` : "هنوز بکاپی ارسال نشده است."} />
      <div className="commerce-actions"><Button variant="outline" disabled={!config.data?.token_configured || !config.data?.backup_password_configured || action.isPending} onClick={() => action.mutate(() => api.post("/api/integrations/backups/send"))}>ارسال بکاپ برای مالک</Button><Button variant="danger" disabled={action.isPending} onClick={() => setRemoving(true)}>قطع اتصال ربات</Button></div>
    </Card>
    <Card className="integration-card"><SectionHeader title="دسترسی مدیران در ربات" subtitle="حساب تلگرام هر مدیر را به حساب پنل او متصل کنید؛ نقش، سهمیه و محدوده دسترسی پنل همچنان اعمال می‌شوند." />
      <form className="commerce-form" onSubmit={e => { e.preventDefault(); action.mutate(() => api.put("/api/integrations/telegram/admins", { telegram_user_id: Number(binding.telegram_user_id), admin_id: Number(binding.admin_id), allow_create: binding.allow_create })); }}>
        <Field label="شناسه عددی تلگرام مدیر"><Input type="number" min="1" required value={binding.telegram_user_id} onChange={e => setBinding({ ...binding, telegram_user_id: e.target.value })} /></Field>
        <Field label="حساب مدیر در پنل"><Select required value={binding.admin_id} onChange={e => setBinding({ ...binding, admin_id: e.target.value })}><option value="">انتخاب مدیر</option>{admins.data?.filter(a => !a.is_owner).map(a => <option key={a.id} value={a.id}>{a.username}</option>)}</Select></Field>
        <Toggle checked={binding.allow_create} onChange={allow_create => setBinding({ ...binding, allow_create })} label="اجازه ساخت کاربر از ربات" /><Button type="submit" disabled={action.isPending}>ثبت دسترسی</Button>
      </form>
      {bindings.data?.map(b => <div className="commerce-member" key={b.telegram_user_id}><span>{b.telegram_user_id} · {admins.data?.find(a => a.id === b.admin_id)?.username} · {b.allow_create ? "ساخت کاربر مجاز" : "فقط دریافت ساب کاربران مجاز"}</span><Button variant="ghost" disabled={action.isPending} onClick={() => action.mutate(() => api.delete(`/api/integrations/telegram/admins/${b.telegram_user_id}`))}>لغو دسترسی</Button></div>)}
      <p className="field-hint" dir="ltr">/new username days GiB [plan_id] · /sub username · /backup (owner only)</p>
    </Card>
    <ConfirmDialog open={removing} onClose={() => setRemoving(false)} title="قطع اتصال ربات" message="توکن و اتصال مدیران ربات حذف می‌شوند. رمز بکاپ برای دریافت محلی حفظ می‌شود." confirmLabel="قطع اتصال" loading={action.isPending} onConfirm={() => action.mutate(() => api.delete("/api/integrations/telegram"))} />
  </div>;
}
