import { t } from "../lib/i18n";import TwoFactorSettings from "../components/TwoFactorSettings";
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileJson,
  Globe2,
  KeyRound,
  LockKeyhole,
  Play,
  RefreshCw,
  Save,
  ScrollText,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  UserRound } from
"lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { AuditLog, OperationResult, PanelSettings, XrayApplyResult, XrayStatus } from "../lib/types";
import { cn, formatBytes, formatDateTime, formatNumber } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  SectionHeader,
  Skeleton,
  Textarea,
  Select } from
"../components/UI";

type TabKey = "general" | "subscription" | "xray" | "security" | "audit";

const TABS: {key: TabKey;label: string;icon: typeof Settings2;hint: string;}[] = [
{ key: "general", label: t("تنظیمات عمومی"), icon: SlidersHorizontal, hint: t("برند و پیام‌ها") },
{ key: "subscription", label: t("اشتراک و دامنه"), icon: Globe2, hint: t("لینک‌ها و پیش‌فرض‌ها") },
{ key: "xray", label: t("هستهٔ Xray"), icon: Terminal, hint: t("کانفیگ و آمار") },
{ key: "security", label: t("امنیت حساب"), icon: ShieldCheck, hint: t("رمز عبور") },
{ key: "audit", label: t("گزارش فعالیت"), icon: ScrollText, hint: t("رویدادهای اخیر") }];


const ACTION_LABELS: Record<string, string> = {
  fail2ban_ban: t("مسدودکردن IP در Fail2ban"),
  fail2ban_unban: t("رفع مسدودیت IP"),
  fail2ban_configure: t("تغییر سیاست امنیت"),
  update_outbounds: t("تغییر خروجی‌ها"),
  update_routing: t("تغییر قوانین مسیریابی"),
  restore_data: t("بازیابی بکاپ"),
  login: t("ورود"),
  change_password: t("تغییر رمز"),
  create_user: t("ایجاد کاربر"),
  update_user: t("ویرایش کاربر"),
  delete_user: t("حذف کاربر"),
  reset_traffic: t("ریست مصرف"),
  revoke_subscription: t("ابطال اشتراک"),
  rotate_uuid: t("چرخش UUID"),
  create_node: t("افزودن نود"),
  update_node: t("ویرایش نود"),
  delete_node: t("حذف نود"),
  rotate_node_key: t("چرخش کلید نود"),
  create_inbound: t("ایجاد اینباند"),
  update_inbound: t("ویرایش اینباند"),
  delete_inbound: t("حذف اینباند"),
  apply_xray: t("اعمال کانفیگ"),
  restart_xray: t("ری‌استارت Xray"),
  stop_xray: t("توقف Xray"),
  sync_xray_stats: t("همگام‌سازی آمار"),
  update_settings: t("تنظیمات")
};

export default function SettingsPage({ section }: {section?: TabKey;}) {
  const { admin, logout } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>(section || "general");
  useEffect(() => setTab(section || "general"), [section]);
  const [form, setForm] = useState<PanelSettings | null>(null);
  const [password, setPassword] = useState({ current: "", next: "", confirm: "" });
  const [passwordError, setPasswordError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [keys, setKeys] = useState<{private_key: string;public_key: string;short_id: string;} | null>(null);
  const [applyResult, setApplyResult] = useState<XrayApplyResult | null>(null);

  const settings = useQuery({
    queryKey: ["panel-settings"],
    queryFn: () => api.get<PanelSettings>("/api/settings"),
    enabled: !!admin?.permissions.includes("settings.read") && !section
  });

  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  const xray = useQuery({
    queryKey: ["xray-status"],
    queryFn: () => api.get<XrayStatus>("/api/xray/status"),
    refetchInterval: 30_000,
    enabled: !!admin?.permissions.includes("xray.manage") && tab === "xray"
  });

  const preview = useQuery({
    queryKey: ["xray-config"],
    queryFn: () =>
    api.get<{config: unknown;warnings: string[];inbound_count: number;client_count: number;}>("/api/xray/config"),
    enabled: previewOpen
  });

  const audit = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => api.get<AuditLog[]>("/api/audit-logs?limit=60"),
    enabled: tab === "audit" && !!admin?.permissions.includes("audit.read")
  });

  const saveMutation = useMutation({
    mutationFn: (payload: Partial<PanelSettings>) => api.put<PanelSettings>("/api/settings", payload),
    onSuccess: (data) => {
      setForm(data);
      toast.success(t("تنظیمات ذخیره شد."));
      queryClient.invalidateQueries({ queryKey: ["panel-settings"] });
      queryClient.invalidateQueries({ queryKey: ["display-preferences"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const passwordMutation = useMutation({
    mutationFn: () =>
    api.post<OperationResult>("/api/auth/change-password", {
      current_password: password.current,
      new_password: password.next
    }),
    onSuccess: () => {
      setPassword({ current: "", next: "", confirm: "" });
      setPasswordError("");
      toast.success(t("رمز عبور تغییر کرد؛ دوباره وارد شوید."));
      void logout();
    },
    onError: (error: Error) => setPasswordError(error.message)
  });

  const applyMutation = useMutation({
    mutationFn: () => api.post<XrayApplyResult>("/api/xray/apply?restart=true"),
    onSuccess: (result) => {
      setApplyResult(result);
      queryClient.invalidateQueries({ queryKey: ["xray-status"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const restartMutation = useMutation({
    mutationFn: () => api.post<OperationResult>("/api/xray/restart"),
    onSuccess: (result) => {
      result.ok ? toast.success(result.message) : toast.error(result.message);
      queryClient.invalidateQueries({ queryKey: ["xray-status"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const syncMutation = useMutation({
    mutationFn: () => api.post<{ok: boolean;message: string;}>("/api/xray/sync-stats"),
    onSuccess: (result) => {
      result.ok ? toast.success(result.message) : toast.error(result.message);
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const keysMutation = useMutation({
    mutationFn: () => api.post<{private_key: string;public_key: string;short_id: string;}>("/api/xray/keys"),
    onSuccess: (data) => setKeys(data),
    onError: (error: Error) => toast.error(error.message)
  });

  function saveGeneral(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    saveMutation.mutate({
      panel_title: form.panel_title,
      panel_description: form.panel_description,
      support_url: form.support_url,
      announcement: form.announcement,
      registration_enabled: form.registration_enabled,
      time_zone: form.time_zone,
      calendar: form.calendar
    });
  }

  function saveSubscription(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    saveMutation.mutate({
      subscription_base_url: form.subscription_base_url,
      public_host: form.public_host,
      default_expiry_days: Number(form.default_expiry_days),
      default_data_limit_gb: Number(form.default_data_limit_gb)
    });
  }

  function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordError("");
    if (password.next.length < 8) {
      setPasswordError(t("رمز جدید باید حداقل ۸ کاراکتر باشد."));
      return;
    }
    if (password.next !== password.confirm) {
      setPasswordError(t("تکرار رمز جدید مطابقت ندارد."));
      return;
    }
    passwordMutation.mutate();
  }

  return (
    <div className="settings-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">{t("پیکربندی فضای کاری")}</p>
          <h2>{section ? TABS.find((item) => item.key === section)?.label : t("تنظیمات عمومی پنل")}</h2>
          <p className="page-subtitle">{section ? TABS.find((item) => item.key === section)?.hint : t("برند، پیام‌ها، دامنهٔ اشتراک و پیش‌فرض ساخت کاربران.")}</p>
        </div>
        <div className="admin-chip">
          <span className="avatar">{admin?.username?.slice(0, 2).toUpperCase()}</span>
          <div>
            <strong>{admin?.username}</strong>
            <span>{admin?.is_owner ? t("مالک پنل") : t("مدیر")}{" " + t("· آخرین ورود") + " "}{formatDateTime(admin?.last_login_at ?? null)}</span>
          </div>
        </div>
      </div>

      <div className="settings-layout">
        <Card className="settings-nav-card">
          <div className="settings-nav">
            {TABS.filter((item) => section ? item.key === section : ["general", "subscription"].includes(item.key)).map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  type="button"
                  className={cn("settings-nav-item", tab === item.key && "active")}
                  onClick={() => setTab(item.key)}>

                  <span className="settings-nav-icon">
                    <Icon size={18} />
                  </span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.hint}</small>
                  </span>
                </button>);

            })}
          </div>
          <div className="settings-version">
            <Sparkles size={15} />
            <span>SpecterGate v0.1.0</span>
          </div>
        </Card>

        <div className="settings-content">
          {tab === "general" && (
          settings.isLoading || !form ?
          <Card>
                <Skeleton height={300} />
              </Card> :

          <Card>
                <SectionHeader
              title={t("هویت پنل")}
              subtitle={t("این اطلاعات در صفحهٔ اشتراک کاربران نمایش داده می‌شود.")}
              action={<Badge tone="success">{t("فعال")}</Badge>} />

                <form onSubmit={saveGeneral} className="settings-form">
                  <Field label={t("نام پنل")}>
                    <Input
                  value={form.panel_title}
                  onChange={(event) => setForm({ ...form, panel_title: event.target.value })}
                  placeholder="SpecterGate" />

                  </Field>
                  <Field label={t("توضیح کوتاه")}>
                    <Input
                  value={form.panel_description}
                  onChange={(event) => setForm({ ...form, panel_description: event.target.value })}
                  placeholder={t("پنل یکپارچه مدیریت پروکسی و اشتراک")} />

                  </Field>
                  <Field label={t("لینک پشتیبانی")} hint={t("در صفحهٔ اشتراک به‌عنوان دکمهٔ پشتیبانی نمایش داده می‌شود.")}>
                    <Input
                  value={form.support_url}
                  onChange={(event) => setForm({ ...form, support_url: event.target.value })}
                  placeholder="https://t.me/your_support"
                  dir="ltr" />

                  </Field>
                  <Field label={t("پیام اطلاع‌رسانی")} hint={t("در صفحهٔ کاربر و هدر announce ساب ارسال می‌شود. نمایش داخل برنامه به پشتیبانی آن بستگی دارد و پس از به‌روزرسانی ساب انجام می‌شود.")}>
                    <Textarea
                  rows={3}
                  value={form.announcement}
                  onChange={(event) => setForm({ ...form, announcement: event.target.value })}
                  placeholder={t("مثلاً: به‌روزرسانی برنامه در تاریخ...")} />

                  </Field>
                  <Field label={t("منطقه زمانی نمایش تاریخ")} hint={t("شناسه IANA؛ مانند Asia/Tehran یا UTC. تاریخ‌ها در دیتابیس به صورت UTC نگهداری می‌شوند.")}><Input dir="ltr" value={form.time_zone} onChange={(e) => setForm({ ...form, time_zone: e.target.value })} /></Field>
                  <Field label={t("تقویم نمایش تاریخ")}><Select value={form.calendar} onChange={(e) => setForm({ ...form, calendar: e.target.value as 'persian' | 'gregory' })}><option value="persian">{t("شمسی")}</option><option value="gregory">{t("میلادی")}</option></Select></Field>
                  <div className="settings-info-note">
                    <Sparkles size={17} />
                    <span>{"" + t("ثبت‌نام عمومی کاربران در نقشهٔ راه نسخهٔ بعدی است. در حال حاضر ساخت حساب فقط از طریق همین پنل انجام می‌شود.") + " "}


                </span>
                  </div>
                  <div className="settings-form-foot">
                    <Button type="submit" icon={<Save size={16} />} loading={saveMutation.isPending}>{"" + t("ذخیره تغییرات") + " "}

                </Button>
                  </div>
                </form>
              </Card>)
          }

          {tab === "subscription" && (
          settings.isLoading || !form ?
          <Card>
                <Skeleton height={300} />
              </Card> :

          <Card>
                <SectionHeader
              title={t("لینک‌های اشتراک")}
              subtitle={t("دامنه‌ای که کلاینت‌ها از آن به پنل متصل می‌شوند.")} />

                <form onSubmit={saveSubscription} className="settings-form">
                  <Field
                label={t("آدرس پایهٔ اشتراک")}
                hint={t("مثلاً https://panel.example.com — خالی بماند از دامنهٔ فعلی استفاده می‌شود.")}>

                    <Input
                  value={form.subscription_base_url}
                  onChange={(event) => setForm({ ...form, subscription_base_url: event.target.value })}
                  placeholder="https://panel.example.com"
                  dir="ltr" />

                  </Field>
                  <Field label={t("هاست عمومی")} hint={t("آدرس یا دامنه‌ای که در کانفیگ لینک‌ها جایگزین نود محلی می‌شود.")}>
                    <Input
                  value={form.public_host}
                  onChange={(event) => setForm({ ...form, public_host: event.target.value })}
                  placeholder="panel.example.com"
                  dir="ltr" />

                  </Field>
                  <div className="form-grid">
                    <Field label={t("اعتبار پیش‌فرض (روز)")} hint={t("۰ یعنی بدون انقضا")}>
                      <Input
                    type="number"
                    min="0"
                    max="3650"
                    value={form.default_expiry_days}
                    onChange={(event) => setForm({ ...form, default_expiry_days: Number(event.target.value) })}
                    dir="ltr" />

                    </Field>
                    <Field label={t("حجم پیش‌فرض (گیگابایت)")} hint={t("۰ یعنی نامحدود")}>
                      <Input
                    type="number"
                    min="0"
                    value={form.default_data_limit_gb}
                    onChange={(event) => setForm({ ...form, default_data_limit_gb: Number(event.target.value) })}
                    dir="ltr" />

                    </Field>
                  </div>
                  <div className="subscription-preview">
                    <span>{t("نمونهٔ لینک اشتراک")}</span>
                    <code dir="ltr">
                      {(form.subscription_base_url || window.location.origin).replace(/\/$/, "")}/sub/&lt;token&gt;
                    </code>
                  </div>
                  <div className="settings-form-foot">
                    <Button type="submit" icon={<Save size={16} />} loading={saveMutation.isPending}>{"" + t("ذخیره تنظیمات اشتراک") + " "}

                </Button>
                  </div>
                </form>
              </Card>)
          }

          {tab === "xray" &&
          <div className="settings-stack">
              <Card className="xray-settings-card">
                <SectionHeader
                title={t("وضعیت هسته")}
                subtitle={t("Xray-core مسئول اجرای پروتکل‌ها و شمارش ترافیک است.")}
                action={
                <Badge tone={xray.data?.running ? "success" : xray.data?.binary_available ? "warning" : "danger"} dot>
                      {xray.data?.running ? t("در حال اجرا") : xray.data?.binary_available ? t("متوقف") : t("نصب نشده")}
                    </Badge>
                } />

                <div className="xray-status-grid">
                  <div>
                    <span>{t("باینری")}</span>
                    <strong>{xray.data?.binary_available ? t("در دسترس") : t("پیدا نشد")}</strong>
                  </div>
                  <div>
                    <span>{t("فایل کانفیگ")}</span>
                    <strong>{xray.data?.config_exists ? t("موجود") : t("ساخته نشده")}</strong>
                  </div>
                  <div>
                    <span>PID</span>
                    <strong dir="ltr">{xray.data?.pid ?? "—"}</strong>
                  </div>
                </div>
                <p className="xray-message">{xray.data?.message}</p>
                <div className="xray-actions">
                  <Button
                  icon={<Play size={16} />}
                  loading={applyMutation.isPending}
                  onClick={() => applyMutation.mutate()}>{"" + t("اعمال و اجرا") + " "}


                </Button>
                  <Button
                  variant="outline"
                  icon={<RefreshCw size={16} />}
                  loading={restartMutation.isPending}
                  onClick={() => restartMutation.mutate()}>{"" + t("ری‌استارت") + " "}


                </Button>
                  <Button
                  variant="outline"
                  icon={<Activity size={16} />}
                  loading={syncMutation.isPending}
                  onClick={() => syncMutation.mutate()}>{"" + t("همگام‌سازی آمار") + " "}


                </Button>
                  <Button variant="ghost" icon={<FileJson size={16} />} onClick={() => setPreviewOpen(true)}>{"" + t("پیش‌نمایش کانفیگ") + " "}

                </Button>
                </div>
              </Card>

              <Card>
                <SectionHeader
                title={t("کلیدهای Reality")}
                subtitle={t("برای ساخت اینباند VLESS Reality از این جفت کلید استفاده کنید.")}
                action={
                <Button
                  size="sm"
                  variant="outline"
                  icon={<KeyRound size={15} />}
                  loading={keysMutation.isPending}
                  onClick={() => keysMutation.mutate()}>{"" + t("تولید جفت کلید") + " "}


                </Button>
                } />

                <div className="settings-info-note">
                  <ShieldCheck size={17} />
                  <span>{"" + t("کلید خصوصی فقط روی سرور نگهداری می‌شود؛ کلید عمومی در لینک اشتراک قرار می‌گیرد. پس از ساخت اینباند، کلیدها به‌صورت خودکار ذخیره می‌شوند.") + " "}


                </span>
                </div>
                {keys &&
              <div className="key-result">
                    <div>
                      <span>Public</span>
                      <code dir="ltr">{keys.public_key}</code>
                    </div>
                    <div>
                      <span>Private</span>
                      <code dir="ltr">{keys.private_key}</code>
                    </div>
                    <div>
                      <span>Short ID</span>
                      <code dir="ltr">{keys.short_id}</code>
                    </div>
                  </div>
              }
              </Card>

              <Card>
                <SectionHeader title={t("مسیرهای سیستمی")} subtitle={t("این مقادیر از متغیرهای محیطی خوانده می‌شوند.")} />
                <div className="path-list">
                  <div>
                    <span>{t("کانفیگ")}</span>
                    <code dir="ltr">{xray.data?.config_path}</code>
                  </div>
                  <div>
                    <span>API</span>
                    <code dir="ltr">127.0.0.1:10085</code>
                  </div>
                </div>
              </Card>
            </div>
          }

          {tab === "security" &&
          <div className="settings-stack">
              <TwoFactorSettings />
              <Card>
                <SectionHeader title={t("تغییر رمز عبور")} subtitle={t("رمز قوی و یکتا برای حساب مدیریت انتخاب کنید.")} />
                <form onSubmit={changePassword} className="settings-form">
                  <Field label={t("رمز فعلی")}>
                    <Input
                    type="password"
                    value={password.current}
                    onChange={(event) => setPassword({ ...password, current: event.target.value })}
                    autoComplete="current-password"
                    dir="ltr"
                    required />

                  </Field>
                  <div className="form-grid">
                    <Field label={t("رمز جدید")} hint={t("حداقل ۸ کاراکتر")}>
                      <Input
                      type="password"
                      value={password.next}
                      onChange={(event) => setPassword({ ...password, next: event.target.value })}
                      autoComplete="new-password"
                      dir="ltr"
                      required />

                    </Field>
                    <Field label={t("تکرار رمز جدید")}>
                      <Input
                      type="password"
                      value={password.confirm}
                      onChange={(event) => setPassword({ ...password, confirm: event.target.value })}
                      autoComplete="new-password"
                      dir="ltr"
                      required />

                    </Field>
                  </div>
                  {passwordError && <div className="form-error">{passwordError}</div>}
                  <div className="settings-form-foot">
                    <Button type="submit" icon={<LockKeyhole size={16} />} loading={passwordMutation.isPending}>{"" + t("تغییر رمز") + " "}

                  </Button>
                  </div>
                </form>
              </Card>

              <Card>
                <SectionHeader title={t("اطلاعات حساب")} subtitle={t("نقش و زمان ورود حساب جاری")} />
                <div className="account-facts">
                  <div>
                    <UserRound size={17} />
                    <span>{t("نام کاربری")}</span>
                    <strong dir="ltr">{admin?.username}</strong>
                  </div>
                  <div>
                    <ShieldCheck size={17} />
                    <span>{t("نقش")}</span>
                    <strong>{admin?.role === "superadmin" ? t("مدیر کل") : t("مدیر")}</strong>
                  </div>
                  <div>
                    <Clock size={17} />
                    <span>{t("آخرین ورود")}</span>
                    <strong>{formatDateTime(admin?.last_login_at ?? null)}</strong>
                  </div>
                </div>
              </Card>
            </div>
          }

          {tab === "audit" &&
          <Card>
              <SectionHeader
              title={t("گزارش فعالیت")}
              subtitle={t("۶۰ رویداد اخیر پنل")}
              action={
              <Button variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={() => audit.refetch()}>{"" + t("به‌روزرسانی") + " "}

              </Button>
              } />

              {audit.isLoading ?
            <Skeleton height={240} /> :

            <div className="table-wrap">
                  <table className="data-table compact audit-table">
                    <thead>
                      <tr>
                        <th>{t("رویداد")}</th>
                        <th>{t("کاربر")}</th>
                        <th>{t("توضیح")}</th>
                        <th>{t("زمان")}</th>
                        <th>IP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {audit.data?.map((log) =>
                  <tr key={log.id}>
                          <td>
                            <Badge tone="neutral">{ACTION_LABELS[log.action] ?? log.action}</Badge>
                          </td>
                          <td>{log.admin_username}</td>
                          <td className="muted-cell">{log.detail ?? "—"}</td>
                          <td className="muted-cell">{formatDateTime(log.created_at)}</td>
                          <td dir="ltr" className="muted-cell">
                            {log.ip_address ?? "—"}
                          </td>
                        </tr>
                  )}
                    </tbody>
                  </table>
                  {audit.data?.length === 0 && <p className="audit-empty">{t("رویدادی ثبت نشده است.")}</p>}
                </div>
            }
            </Card>
          }
        </div>
      </div>

      <Modal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={t("پیش‌نمایش کانفیگ Xray")}
        description={t("این فایل هنگام اعمال، روی سرور نوشته می‌شود.")}
        wide
        footer={
        <Button
          icon={<Play size={16} />}
          loading={applyMutation.isPending}
          onClick={() => {
            setPreviewOpen(false);
            applyMutation.mutate();
          }}>{"" + t("اعمال کانفیگ") + " "}


        </Button>
        }>

        {preview.isLoading ?
        <Skeleton height={300} /> :

        <>
            <div className="preview-meta">
              <Badge tone="info">{formatNumber(preview.data?.inbound_count ?? 0)}{" " + t("اینباند") + ""}</Badge>
              <Badge tone="violet">{formatNumber(preview.data?.client_count ?? 0)}{" " + t("کلاینت") + ""}</Badge>
              {preview.data?.warnings.map((warning) =>
            <Badge key={warning} tone="warning">
                  {warning}
                </Badge>
            )}
            </div>
            <pre className="code-block" dir="ltr">
              {JSON.stringify(preview.data?.config, null, 2)}
            </pre>
          </>
        }
      </Modal>

      <Modal
        open={applyResult !== null}
        onClose={() => setApplyResult(null)}
        title={applyResult?.ok ? t("کانفیگ اعمال شد") : t("کانفیگ اعمال نشد")}
        description={applyResult?.message}
        wide
        footer={
        <Button variant="ghost" onClick={() => setApplyResult(null)}>{"" + t("بستن") + " "}

        </Button>
        }>

        <div className={cn("apply-result", applyResult?.ok ? "success" : "warning")}>
          {applyResult?.ok ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
          <div>
            <strong>
              {formatNumber(applyResult?.inbound_count ?? 0)}{" " + t("اینباند ·") + " "}{formatNumber(applyResult?.client_count ?? 0)}{" " + t("کلاینت") + " "}
            </strong>
            <span dir="ltr">{applyResult?.config_path}</span>
          </div>
        </div>
        {applyResult?.validation_output &&
        <pre className="code-block" dir="ltr">
            {applyResult.validation_output}
          </pre>
        }
      </Modal>
    </div>);

}
