import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, ConfirmDialog, Field, Input, SectionHeader, Spinner } from "../components/UI";

interface Status { available: boolean; active: boolean; message?: string; currently_failed: number; total_failed: number; currently_banned: number; total_banned: number; banned_ips: string[]; maxretry: number; findtime: number; bantime: number }
export default function Security() {
  const { admin } = useAuth(), toast = useToast(), cache = useQueryClient();
  const canManage = !!admin?.permissions.includes("security.manage");
  const [ip, setIp] = useState("");
  const [pending, setPending] = useState<{ action: "ban" | "unban"; ip: string } | null>(null);
  const [form, setForm] = useState({ maxretry: 5, findtime: 600, bantime: 3600 });
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
    <ConfirmDialog open={!!pending} onClose={() => setPending(null)} title={pending?.action === "ban" ? "مسدودکردن IP" : "رفع مسدودیت IP"} message={`${pending?.ip || ""} — ${pending?.action === "ban" ? "این IP مطابق سیاست Fail2ban مسدود می‌شود." : "این IP از فهرست مسدود SSH حذف می‌شود."}`} confirmLabel="تأیید" loading={action.isPending} onConfirm={() => pending && action.mutate(() => api.post(`/api/security/fail2ban/${pending.action}`, { ip: pending.ip }))} />
  </div>;
}
