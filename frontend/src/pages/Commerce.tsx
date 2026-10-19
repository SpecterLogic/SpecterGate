import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Pencil, Trash2, Copy, Users, Wallet } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { formatBytes, formatDate, formatNumber, toDateTimeLocal, fromDateTimeLocal } from "../lib/format";
import type { Admin, Plan, SubscriptionGroup, VPNUser, SubscriptionInfo } from "../lib/types";
import { Button, Card, Field, Input, Select, Modal, ConfirmDialog, Spinner, StatusBadge } from "../components/UI";
import ResourceAccessPicker from "../components/ResourceAccessPicker";

type Mode = "admins" | "plans" | "subscriptions";
type Item = Admin | Plan | SubscriptionGroup;
type Values = Record<string, string>;
const titles = { admins: "ادمین‌ها و نمایندگان", plans: "پلن‌های فروش", subscriptions: "اشتراک‌های گروهی" };
const roles: Record<string, string> = { superadmin: "مدیر کل", admin: "مدیر", reseller: "نماینده", support: "پشتیبان", viewer: "بازدیدکننده" };
const GB = 1024 ** 3;

function initial(mode: Mode, item?: Item): Values {
  if (mode === "admins") {
    const a = item as Admin | undefined;
    return { username: a?.username ?? "", password: "", role: a?.role ?? "reseller", scope: a?.scope ?? "own", parent_id: String(a?.parent_id ?? ""), max_users: String(a?.max_users ?? ""), traffic_gb: a?.traffic_quota_bytes == null ? "" : String(a.traffic_quota_bytes / GB), require_template: String(a?.require_template ?? false), is_active: String(a?.is_active ?? true) };
  }
  const p = item as (Plan & SubscriptionGroup) | undefined;
  const access = { allowed_inbound_ids: JSON.stringify(p?.allowed_inbound_ids ?? null), allowed_dns_tunnel_ids: JSON.stringify(p?.allowed_dns_tunnel_ids ?? null) };
  return { ...access, name: p?.name ?? "", description: p?.description ?? "", days: String(p?.days ?? 30), traffic_gb: p?.data_limit_bytes == null ? "" : String(p.data_limit_bytes / GB), device_limit: String(p?.device_limit ?? ""), price: String(p?.price ?? 0), is_active: String(p?.is_active ?? true), plan_id: String(p?.plan_id ?? ""), max_members: String(p?.max_members ?? 1), expire_at: toDateTimeLocal(p?.expire_at ?? null), note: p?.note ?? "" };
}

export default function Commerce({ mode }: { mode: Mode }) {
  const { admin } = useAuth();
  const toast = useToast();
  const cache = useQueryClient();
  const canWrite = !!admin?.permissions.includes(mode === "admins" ? "admins.manage" : mode === "plans" ? "plans.manage" : "subscriptions.write");
  const [editor, setEditor] = useState<{ item?: Item; values: Values } | null>(null);
  const [deleting, setDeleting] = useState<Item | null>(null);
  const [members, setMembers] = useState<SubscriptionGroup | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [credit, setCredit] = useState<Admin | null>(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [rotate, setRotate] = useState<SubscriptionGroup | null>(null);
  const list = useQuery({ queryKey: [mode], queryFn: () => api.get<Item[]>(`/api/${mode}`) });
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.get<Plan[]>("/api/plans"), enabled: mode === "subscriptions" && !!admin?.permissions.includes("plans.read") });
  const candidates = useQuery({ queryKey: ["group-candidates", members?.id], queryFn: () => api.get<VPNUser[]>(`/api/subscriptions/${members!.id}/candidates?limit=100`), enabled: !!members });
  const transactions = useQuery({ queryKey: ["transactions", credit?.id], queryFn: () => api.get<{ id: number; amount: number; balance_after: number; note: string | null; created_at: string }[]>(`/api/admins/${credit!.id}/transactions`), enabled: !!credit });
  const permissions = useQuery({ queryKey: ["permission-options"], queryFn: () => api.get<string[]>("/api/admins/meta/permissions"), enabled: mode === "admins" });

  function refresh() {
    for (const key of [mode, "users", "dashboard", "group-candidates", "transactions"]) cache.invalidateQueries({ queryKey: [key] });
  }
  const action = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { refresh(); setEditor(null); setDeleting(null); setRotate(null); setError(""); toast.success("تغییرات ذخیره شد."); },
    onError: (e: Error) => { setError(e.message); toast.error(e.message); },
  });
  function open(item?: Item) { setError(""); setEditor({ item, values: initial(mode, item) }); }
  function field(key: string, label: string, type = "text", extra: { min?: number; max?: number; required?: boolean; step?: string } = {}) {
    return <Field label={label}><Input type={type} value={editor?.values[key] ?? ""} onChange={e => setEditor(current => current && ({ ...current, values: { ...current.values, [key]: e.target.value } }))} {...extra} /></Field>;
  }
  function select(key: string, label: string, options: Record<string, string>) {
    return <Field label={label}><Select value={editor?.values[key] ?? ""} onChange={e => setEditor(current => current && ({ ...current, values: { ...current.values, [key]: e.target.value } }))}>{Object.entries(options).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>;
  }
  function submit(e: FormEvent) {
    e.preventDefault(); if (!editor) return;
    const v = editor.values;
    let body: Record<string, unknown>;
    if (mode === "admins") {
      body = { role: v.role, scope: v.scope, parent_id: v.parent_id ? Number(v.parent_id) : null, max_users: v.max_users ? Number(v.max_users) : null, traffic_quota_bytes: v.traffic_gb ? Math.round(Number(v.traffic_gb) * GB) : null, require_template: v.require_template === "true", is_active: v.is_active === "true" };
      if (!editor.item) body.username = v.username;
      if (v.password) body.password = v.password;
      if ((editor.item as Admin | undefined)?.is_owner) body = v.password ? { password: v.password } : {};
      if (v.permissions !== undefined) body.permissions = v.permissions.split(",").filter(Boolean);
    } else {
      body = { name: v.name, data_limit_bytes: v.traffic_gb === "" ? null : Math.round(Number(v.traffic_gb) * GB), is_active: v.is_active === "true" };
      if (mode === "plans") Object.assign(body, { description: v.description || null, days: Number(v.days), price: Number(v.price), device_limit: v.device_limit ? Number(v.device_limit) : null });
      else Object.assign(body, { plan_id: v.plan_id ? Number(v.plan_id) : null, max_members: Number(v.max_members), expire_at: fromDateTimeLocal(v.expire_at), note: v.note || null });
    }
    if (mode === "subscriptions") Object.assign(body, { allowed_inbound_ids: JSON.parse(v.allowed_inbound_ids ?? "null"), allowed_dns_tunnel_ids: JSON.parse(v.allowed_dns_tunnel_ids ?? "null") });
    action.mutate(() => editor.item ? api.patch(`/api/${mode}/${editor.item.id}`, body) : api.post(`/api/${mode}`, body));
  }
  async function copy(group: SubscriptionGroup) {
    try { const info = await api.get<SubscriptionInfo>(`/sub/${group.token}/info`); await navigator.clipboard.writeText(info.subscription_url); toast.success("لینک اشتراک کپی شد."); }
    catch { toast.error("کپی لینک ممکن نشد؛ صفحه اشتراک را باز کنید."); }
  }
  const ownerEditing = mode === "admins" && (editor?.item as Admin | undefined)?.is_owner;
  return <div className="commerce-page">
    <div className="page-heading"><div><h1>{titles[mode]}</h1><p>{mode === "subscriptions" ? "برای هر لینک، سقف اعضا، حجم مشترک و انقضا تعیین کنید." : mode === "plans" ? "بسته‌های زمان، حجم و قیمت برای فروش و تمدید." : "نقش، محدوده کاربران، سهمیه و اعتبار هر نماینده را مدیریت کنید."}</p></div>{canWrite && <Button icon={<Plus size={17} />} onClick={() => open()}>ایجاد</Button>}</div>
    {list.isLoading ? <Spinner /> : list.error ? <Card><p role="alert">{list.error.message}</p><Button onClick={() => list.refetch()}>تلاش دوباره</Button></Card> : <Card><div className="commerce-table"><table><thead><tr><th>نام</th><th>وضعیت</th><th>{mode === "admins" ? "نقش / کاربران" : mode === "plans" ? "مدت / قیمت" : "اعضا / مصرف"}</th><th>عملیات</th></tr></thead><tbody>{list.data?.map(item => {
      const a = item as Admin; const p = item as Plan; const g = item as SubscriptionGroup;
      return <tr key={item.id}><td>{mode === "admins" ? a.username : p.name}{mode === "admins" && a.is_owner && <small> · مالک</small>}</td><td><StatusBadge status={mode === "subscriptions" ? g.status : item.is_active ? "active" : "disabled"} /></td><td>{mode === "admins" ? `${roles[a.role]} · ${formatNumber(a.user_count)} کاربر · اعتبار ${formatNumber(a.credit)}` : mode === "plans" ? `${formatNumber(p.days)} روز · ${formatNumber(p.price)} · ${p.data_limit_bytes == null ? "حجم نامحدود" : formatBytes(p.data_limit_bytes)}` : `${g.members.length} / ${g.max_members} عضو · ${formatBytes(g.used_traffic_bytes)} از ${g.data_limit_bytes == null ? "نامحدود" : formatBytes(g.data_limit_bytes)}`}</td><td><div className="commerce-actions">
        {canWrite && <Button variant="ghost" size="sm" icon={<Pencil size={15} />} onClick={() => open(item)}>ویرایش</Button>}
        {mode === "admins" && <Button variant="ghost" size="sm" icon={<Wallet size={15} />} onClick={() => { setCredit(a); setAmount(""); setNote(""); }}>اعتبار و تراکنش‌ها</Button>}
        {mode === "subscriptions" && <><Button variant="ghost" size="sm" icon={<Users size={15} />} onClick={() => { setMembers(g); setSelected([]); }}>اعضا</Button><Button variant="ghost" size="sm" icon={<Copy size={15} />} onClick={() => copy(g)}>لینک</Button><Link to={`/s/${g.token}`}>مشاهده</Link>{canWrite && <Button variant="ghost" size="sm" onClick={() => setRotate(g)}>ابطال لینک قبلی</Button>}</>}
        {canWrite && !(mode === "admins" && a.is_owner) && <Button variant="ghost" size="sm" icon={<Trash2 size={15} />} onClick={() => setDeleting(item)}>حذف</Button>}
      </div></td></tr>;
    })}</tbody></table>{list.data?.length === 0 && <p className="commerce-empty">هنوز موردی ثبت نشده است.</p>}</div></Card>}
    <Modal open={!!editor} onClose={() => !action.isPending && setEditor(null)} title={`${editor?.item ? "ویرایش" : "ایجاد"} ${titles[mode]}`} wide>
      <form onSubmit={submit} className="commerce-form">
        {mode === "admins" ? <>
          {!editor?.item && field("username", "نام کاربری", "text", { required: true })}
          {field("password", editor?.item ? "رمز جدید (خالی = بدون تغییر)" : "رمز عبور", "password", { required: !editor?.item })}
          {!ownerEditing && <>{select("role", "نقش", roles)}{select("scope", "محدوده کاربران", { own: "خود و زیرمجموعه", all: "همه", none: "هیچ" })}{field("parent_id", "شناسه ادمین بالادستی", "number", { min: 1 })}{field("max_users", "سقف تعداد کاربر (خالی = نامحدود)", "number", { min: 0 })}{field("traffic_gb", "سهمیه مصرف نماینده (GiB؛ خالی = نامحدود)", "number", { min: 0, step: "any" })}{select("require_template", "ساخت کاربر فقط با پلن", { false: "خیر", true: "بله" })}
          <fieldset className="commerce-permissions"><legend>مجوزهای سفارشی (بدون انتخاب = مجوزهای پیش‌فرض نقش)</legend>{permissions.data?.map(p => {
            const checked = editor?.values.permissions === undefined ? (editor?.item as Admin | undefined)?.permissions.includes(p) ?? false : editor.values.permissions.split(",").includes(p);
            return <label key={p}><input type="checkbox" checked={checked} onChange={e => setEditor(current => { if (!current) return current; const values = new Set(current.values.permissions === undefined ? (current.item as Admin | undefined)?.permissions ?? [] : current.values.permissions.split(",").filter(Boolean)); if (e.target.checked) values.add(p); else values.delete(p); return { ...current, values: { ...current.values, permissions: [...values].join(",") } }; })} />{p}</label>;
          })}</fieldset></>}
        </> : <>
          {field("name", "نام", "text", { required: true })}{field("traffic_gb", "حجم (GiB؛ خالی = نامحدود)", "number", { min: 0, step: "any" })}
          {mode === "plans" ? <>{field("description", "توضیحات")}{field("days", "مدت (روز؛ صفر = بدون انقضا)", "number", { min: 0, max: 3650, required: true })}{field("device_limit", "سقف دستگاه در اطلاعات پلن", "number", { min: 1, max: 100 })}{field("price", "قیمت (واحد اعتبار پنل)", "number", { min: 0, required: true })}</> : <>
            {select("plan_id", "پلن", { "": "بدون پلن", ...Object.fromEntries((plans.data ?? []).filter(p => p.is_active).map(p => [String(p.id), `${p.name} · ${formatNumber(p.price)}`])) })}{field("max_members", "سقف اعضا", "number", { min: 1, max: 100, required: true })}{field("expire_at", "تاریخ انقضا", "datetime-local")}{field("note", "یادداشت")}
          </>}
        </>}
        {!ownerEditing && select("is_active", "وضعیت", { true: "فعال", false: "غیرفعال" })}
        {mode === "subscriptions" && editor && <ResourceAccessPicker value={{ allowed_inbound_ids: JSON.parse(editor.values.allowed_inbound_ids ?? "null"), allowed_dns_tunnel_ids: JSON.parse(editor.values.allowed_dns_tunnel_ids ?? "null") }} onChange={policy => setEditor(current => current && ({ ...current, values: { ...current.values, allowed_inbound_ids: JSON.stringify(policy.allowed_inbound_ids), allowed_dns_tunnel_ids: JSON.stringify(policy.allowed_dns_tunnel_ids) } }))} />}
        {error && <p role="alert" className="field-error">{error}</p>}
        <div className="commerce-form-footer"><Button type="submit" loading={action.isPending}>ذخیره</Button><Button type="button" variant="ghost" onClick={() => setEditor(null)}>انصراف</Button></div>
      </form>
    </Modal>
    <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} title="حذف" message="این مورد حذف شود؟" loading={action.isPending} onConfirm={() => deleting && action.mutate(() => api.delete(`/api/${mode}/${deleting.id}`))} />
    <ConfirmDialog open={!!rotate} onClose={() => setRotate(null)} title="ابطال لینک اشتراک" message="لینک قبلی از کار می‌افتد و باید لینک جدید را به اعضا بدهید." confirmLabel="ایجاد لینک جدید" loading={action.isPending} onConfirm={() => rotate && action.mutate(() => api.post(`/api/subscriptions/${rotate.id}/rotate-token`))} />
    <Modal open={!!members} onClose={() => setMembers(null)} title={`اعضای ${members?.name ?? ""}`}>
      {(() => { const group = (list.data as SubscriptionGroup[] | undefined)?.find(g => g.id === members?.id) ?? members; return <>
        <p>ظرفیت: {group?.members.length} از {group?.max_members}</p>
        {group?.members.map(m => <div className="commerce-member" key={m.id}><span>{m.username} · {formatBytes(m.used_traffic_bytes)} · <StatusBadge status={m.status} /></span>{canWrite && <Button size="sm" variant="ghost" disabled={action.isPending} onClick={() => action.mutate(() => api.delete(`/api/subscriptions/${group.id}/members/${m.id}`))}>حذف از اشتراک</Button>}</div>)}
        {canWrite && <><Field label="افزودن کاربران موجود"><Select multiple value={selected.map(String)} onChange={e => setSelected(Array.from(e.target.selectedOptions, option => Number(option.value)))}>{candidates.data?.filter(u => !group?.members.some(m => m.id === u.id)).map(u => <option key={u.id} value={u.id}>{u.username}</option>)}</Select></Field>{candidates.error && <p role="alert">{candidates.error.message}</p>}<Button disabled={!selected.length} loading={action.isPending} onClick={() => action.mutate(async () => { await api.post(`/api/subscriptions/${group!.id}/members`, { user_ids: selected }); setSelected([]); })}>افزودن اعضا</Button><p><Link to="/users?new=1" onClick={() => setMembers(null)}>ساخت کاربر جدید</Link></p></>}
      </>; })()}
    </Modal>
    <Modal open={!!credit} onClose={() => setCredit(null)} title={`اعتبار ${credit?.username ?? ""}`}>
      <p>موجودی: {formatNumber(((list.data as Admin[] | undefined)?.find(a => a.id === credit?.id) ?? credit)?.credit ?? 0)}</p>
      {admin?.is_owner && <form className="commerce-form" onSubmit={e => { e.preventDefault(); action.mutate(async () => { await api.post(`/api/admins/${credit!.id}/credit`, { amount: Number(amount), note: note || null }); setAmount(""); setNote(""); }); }}><Field label="مبلغ (منفی برای برداشت)"><Input type="number" step="1" required value={amount} onChange={e => setAmount(e.target.value)} /></Field><Field label="شرح تراکنش"><Input value={note} onChange={e => setNote(e.target.value)} /></Field><Button type="submit" loading={action.isPending}>ثبت تراکنش</Button></form>}
      {transactions.isLoading ? <Spinner /> : transactions.error ? <p role="alert">{transactions.error.message}</p> : transactions.data?.map(t => <div key={t.id} className="commerce-member"><span>{formatDate(t.created_at)} · {t.note}</span><strong dir="ltr">{formatNumber(t.amount)} → {formatNumber(t.balance_after)}</strong></div>)}
    </Modal>
  </div>;
}
