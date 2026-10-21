import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { ShieldCheck, KeyRound, Copy } from "lucide-react";
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, SectionHeader, Spinner } from "../components/UI";

interface Status { available: boolean; active: boolean; message?: string; currently_failed: number; total_failed: number; currently_banned: number; total_banned: number; banned_ips: string[]; maxretry: number; findtime: number; bantime: number }
export default function Security() {
  const { admin } = useAuth(), toast = useToast(), cache = useQueryClient();
  const canManage = !!admin?.permissions.includes("security.manage");
  const [ip, setIp] = useState("");
  const [pending, setPending] = useState<{ action: "ban" | "unban"; ip: string } | null>(null);
  const [form, setForm] = useState({ maxretry: 5, findtime: 600, bantime: 3600 });
  const [setupData, setSetupData] = useState<{ secret: string; uri: string; qr_svg: string; recovery_codes: string[] } | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [disable2FaOpen, setDisable2FaOpen] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");

  const setup2FaMutation = useMutation({
    mutationFn: () => api.post<{ secret: string; uri: string; qr_svg: string; recovery_codes: string[] }>("/api/auth/2fa/setup"),
    onSuccess: (data) => {
      setSetupData(data);
      setConfirmCode("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const enable2FaMutation = useMutation({
    mutationFn: () =>
      api.post("/api/auth/2fa/enable", {
        secret: setupData?.secret,
        code: confirmCode.trim(),
        recovery_codes: setupData?.recovery_codes || [],
      }),
    onSuccess: () => {
      toast.success("احراز هویت دومرحله‌ای با موفقیت فعال شد.");
      setSetupData(null);
      setConfirmCode("");
      window.location.reload();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const disable2FaMutation = useMutation({
    mutationFn: () => api.post("/api/auth/2fa/disable", { password: disablePassword }),
    onSuccess: () => {
      toast.success("احراز هویت دومرحله‌ای غیرفعال شد.");
      setDisable2FaOpen(false);
      setDisablePassword("");
      window.location.reload();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const query = useQuery({ queryKey: ["fail2ban"], queryFn: () => api.get<Status>("/api/security/fail2ban"), refetchInterval: 15000 });
  useEffect(() => { if (query.data?.available) setForm({ maxretry: query.data.maxretry, findtime: query.data.findtime, bantime: query.data.bantime }); }, [query.data?.maxretry, query.data?.findtime, query.data?.bantime]);
  const action = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => { cache.invalidateQueries({ queryKey: ["fail2ban"] }); setPending(null); setIp(""); toast.success("تنظیمات امنیت اعمال شد."); }, onError: (error: Error) => toast.error(error.message) });
  if (query.isLoading) return <Spinner />;
  const status = query.data;
  return <div className="commerce-page">
    <SectionHeader title="امنیت و Fail2ban" subtitle="محافظت SSH، مشاهدهٔ IPهای مسدود و مدیریت محدودیت تلاش ورود." action={<Button variant="outline" onClick={() => query.refetch()}>تازه‌سازی</Button>} />
    {query.error && <p role="alert">{query.error.message}</p>}
    <Card className="integration-card"><SectionHeader title="محافظت SSH" action={<Badge tone={status?.active ? "success" : "warning"}>{status?.active ? "فعال" : "در دسترس نیست"}</Badge>} />
      {!status?.available ? <p role="alert">{status?.message || "ارتباط با سرویس امنیت برقرار نشد."} نصب سرویس: <code dir="ltr">sudo bash /opt/spectergate/deploy/fail2ban_install.sh</code></p> : <>
        <div className="security-stats"><div><small>IPهای مسدود فعلی</small><strong>{status.currently_banned}</strong></div><div><small>کل مسدودسازی‌ها</small><strong>{status.total_banned}</strong></div><div><small>تلاش‌های ناموفق</small><strong>{status.total_failed}</strong></div></div>
        <p className="field-hint">این بخش از SSH محافظت می‌کند. محدودسازی ورود پنل در برنامه و Nginx جداگانه فعال است.</p>
      </>}
    </Card>
    {status?.available && <>
      <Card className="integration-card"><SectionHeader title="IPهای مسدود" />
        {status.banned_ips.length ? status.banned_ips.map(address => <div className="commerce-member" key={address}><code dir="ltr">{address}</code>{canManage && <Button variant="outline" disabled={action.isPending} onClick={() => setPending({ action: "unban", ip: address })}>رفع مسدودیت</Button>}</div>) : <p>در حال حاضر IP مسدودی وجود ندارد.</p>}
        {canManage && <form className="commerce-form" onSubmit={e => { e.preventDefault(); setPending({ action: "ban", ip: ip.trim() }); }}><Field label="مسدودکردن IP عمومی" hint="IP نشست فعلی و آدرس‌های خصوصی از داخل پنل مسدود نمی‌شوند."><Input dir="ltr" required value={ip} onChange={e => setIp(e.target.value)} placeholder="IPv4 / IPv6" /></Field><Button type="submit" variant="danger" disabled={!ip.trim() || action.isPending}>مسدودکردن</Button></form>}
      </Card>
      <Card className="integration-card"><SectionHeader title="سیاست تلاش ورود" subtitle={canManage ? "مقادیر روی سرویس اعمال و برای راه‌اندازی‌های بعدی ذخیره می‌شوند." : "برای تغییر این مقادیر، مجوز مدیریت Fail2ban لازم است."} />
        <form className="commerce-form" onSubmit={e => { e.preventDefault(); action.mutate(() => api.put("/api/security/fail2ban", form)); }}>
          <Field label="تعداد تلاش ناموفق"><Input type="number" min={3} max={20} disabled={!canManage} value={form.maxretry} onChange={e => setForm({ ...form, maxretry: Number(e.target.value) })} /></Field>
          <Field label="بازهٔ بررسی، ثانیه"><Input type="number" min={60} max={86400} disabled={!canManage} value={form.findtime} onChange={e => setForm({ ...form, findtime: Number(e.target.value) })} /></Field>
          <Field label="مدت مسدودیت، ثانیه"><Input type="number" min={60} max={604800} disabled={!canManage} value={form.bantime} onChange={e => setForm({ ...form, bantime: Number(e.target.value) })} /></Field>
          {canManage && <Button type="submit" loading={action.isPending}>ذخیرهٔ سیاست امنیت</Button>}
        </form>
      </Card>
    </>}
        {/* Two-Factor Authentication (2FA) */}
    <Card className="integration-card">
      <SectionHeader
        title="احراز هویت دومرحله‌ای (2FA / TOTP)"
        subtitle="امنیت حساب مدیریت با کدهای متغیر ۶ رقمی نرم‌افزارهای Authenticator."
        action={<Badge tone={admin?.totp_enabled ? "success" : "neutral"}>{admin?.totp_enabled ? "فعال" : "غیرفعال"}</Badge>}
      />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0" }}>
        <div>
          <p style={{ margin: "0 0 4px", fontWeight: 500 }}>
            {admin?.totp_enabled
              ? "ورود دومرحله‌ای برای این حساب فعال است. هنگام ورود، کد تأیید ۶ رقمی الزامی خواهد بود."
              : "ورود دومرحله‌ای هنوز فعال نشده است. فعال‌سازی آن امنیت پنل شما را ارتقا می‌دهد."}
          </p>
          <small className="field-hint">سازگار با Google Authenticator، Bitwarden، Aegis، و تمام برنامه‌های TOTP.</small>
        </div>
        <div>
          {admin?.totp_enabled ? (
            <Button variant="danger" size="sm" onClick={() => setDisable2FaOpen(true)}>
              غیرفعال‌سازی 2FA
            </Button>
          ) : (
            <Button variant="primary" size="sm" icon={<ShieldCheck size={15} />} loading={setup2FaMutation.isPending} onClick={() => setup2FaMutation.mutate()}>
              راه‌اندازی و فعال‌سازی 2FA
            </Button>
          )}
        </div>
      </div>
    </Card>

    {/* 2FA Setup Modal */}
    <Modal
      open={setupData !== null}
      onClose={() => setSetupData(null)}
      title="فعال‌سازی احراز هویت دومرحله‌ای"
      description="بارکد زیر را با نرم‌افزار Authenticator خود اسکن کرده و کد ۶ رقمی را وارد کنید."
      footer={
        <>
          <Button variant="ghost" onClick={() => setSetupData(null)}>انصراف</Button>
          <Button loading={enable2FaMutation.isPending} disabled={!confirmCode.trim()} onClick={() => enable2FaMutation.mutate()}>
            تأیید و فعال‌سازی
          </Button>
        </>
      }
    >
      {setupData && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px", alignItems: "center" }}>
          <div
            style={{ width: "200px", height: "200px", background: "white", padding: "8px", borderRadius: "8px" }}
            dangerouslySetInnerHTML={{ __html: setupData.qr_svg }}
          />
          <div style={{ width: "100%", textAlign: "center" }}>
            <span className="field-hint" style={{ display: "block", marginBottom: "4px" }}>کلید متنی (در صورت عدم امکان اسکن):</span>
            <code dir="ltr" style={{ fontSize: "14px", fontWeight: "bold", padding: "4px 8px", background: "#374151", borderRadius: "4px" }}>
              {setupData.secret}
            </code>
          </div>
          <div style={{ width: "100%", background: "#1f2937", padding: "12px", borderRadius: "8px" }}>
            <strong style={{ fontSize: "12px", display: "block", marginBottom: "6px" }}>کدهای پشتیبان یک‌بار مصرف (این کدها را یادداشت کنید):</strong>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
              {setupData.recovery_codes.map((code) => (
                <code key={code} dir="ltr" style={{ fontSize: "12px", background: "#111827", padding: "2px 6px", borderRadius: "3px" }}>
                  {code}
                </code>
              ))}
            </div>
          </div>
          <div style={{ width: "100%" }}>
            <Field label="کد ۶ رقمی نرم‌افزار Authenticator">
              <Input
                value={confirmCode}
                onChange={(e) => setConfirmCode(e.target.value)}
                placeholder="۱۲۳۴۵۶"
                dir="ltr"
                autoFocus
              />
            </Field>
          </div>
        </div>
      )}
    </Modal>

    {/* 2FA Disable Modal */}
    <Modal
      open={disable2FaOpen}
      onClose={() => setDisable2FaOpen(false)}
      title="غیرفعال‌سازی ورود دومرحله‌ای"
      description="برای غیرفعال‌سازی، لطفاً رمز عبور حساب خود را تأیید کنید."
      footer={
        <>
          <Button variant="ghost" onClick={() => setDisable2FaOpen(false)}>انصراف</Button>
          <Button variant="danger" loading={disable2FaMutation.isPending} disabled={!disablePassword} onClick={() => disable2FaMutation.mutate()}>
            غیرفعال‌سازی
          </Button>
        </>
      }
    >
      <Field label="رمز عبور فعلی">
        <Input
          type="password"
          value={disablePassword}
          onChange={(e) => setDisablePassword(e.target.value)}
          placeholder="رمز عبور فعلی را وارد کنید"
          dir="ltr"
          autoFocus
        />
      </Field>
    </Modal>

    <ConfirmDialog open={!!pending} onClose={() => setPending(null)} title={pending?.action === "ban" ? "مسدودکردن IP" : "رفع مسدودیت IP"} message={`${pending?.ip || ""} — ${pending?.action === "ban" ? "این IP مطابق سیاست Fail2ban مسدود می‌شود." : "این IP از فهرست مسدود SSH حذف می‌شود."}`} confirmLabel="تأیید" loading={action.isPending} onConfirm={() => pending && action.mutate(() => api.post(`/api/security/fail2ban/${pending.action}`, { ip: pending.ip }))} />
  </div>;
}
