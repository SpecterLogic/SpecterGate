import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { Node } from "../lib/types";
import { Badge, Button, Card, Field, Input, Select, SectionHeader, Spinner } from "../components/UI";

interface Proxy { tag: string; name: string; protocol: "socks" | "http"; address: string; port: number; username: string; password_configured?: boolean; password?: string }
interface Policy { default_outbound: string; outbounds: Proxy[]; warp_enabled: boolean; private_key_configured: boolean }
export default function Outbounds() {
  const { admin } = useAuth(), toast = useToast(), cache = useQueryClient();
  const canManage = !!admin?.permissions.includes("routing.manage");
  const [node, setNode] = useState("");
  const [rows, setRows] = useState<Proxy[]>([]);
  const [selected, setSelected] = useState("direct");
  const suffix = node ? `?node_id=${node}` : "";
  const query = useQuery({ queryKey: ["routing", node], queryFn: () => api.get<Policy>(`/api/routing${suffix}`) });
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => api.get<Node[]>("/api/nodes"), enabled: !!admin?.permissions.includes("nodes.read") });
  useEffect(() => { if (query.data) { setRows(query.data.outbounds || []); setSelected(query.data.default_outbound); } }, [query.data]);
  const save = useMutation({ mutationFn: () => api.put(`/api/routing/outbounds${suffix}`, { outbounds: rows.map(({ password_configured, password, ...row }) => ({ ...row, ...(password ? { password } : {}) })), default_outbound: selected }), onSuccess: () => { cache.invalidateQueries({ queryKey: ["routing", node] }); toast.success("خروجی‌ها ذخیره شدند؛ هسته در همگام‌سازی بعدی اعمال می‌کند."); }, onError: (error: Error) => toast.error(error.message) });
  function patch(index: number, changes: Partial<Proxy>) { setRows(current => current.map((row, i) => i === index ? { ...row, ...changes } : row)); }
  return <div className="commerce-page">
    <SectionHeader title="خروجی‌ها (Outbounds)" subtitle="مسیر خروج ترافیک را انتخاب کنید؛ قوانین انتخاب ترافیک در صفحهٔ مسیریابی قرار دارند." action={<Link className="text-link" to="/routing">قوانین مسیریابی ←</Link>} />
    {!canManage && <p className="field-hint">دسترسی شما در این بخش فقط مشاهده است. برای تغییر، مجوز مدیریت خروجی‌ها لازم است.</p>}
    <Field label="سرور خروجی"><Select value={node} onChange={e => setNode(e.target.value)}><option value="">سرور محلی</option>{nodes.data?.filter(n => !n.is_local).map(n => <option key={n.id} value={n.id}>{n.name}</option>)}</Select></Field>
    {query.isLoading ? <Spinner /> : query.error ? <p role="alert">{query.error.message}</p> : <form onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <div className="outbound-catalog">{[{ tag: "direct", name: "Direct", text: "خروج مستقیم از سرور" }, { tag: "ipv4", name: "IPv4", text: "خروج با DNS اجباری IPv4" }, { tag: "blocked", name: "Block", text: "مسدودکردن ترافیک انتخاب‌شده" }, { tag: "warp", name: "WARP", text: query.data?.warp_enabled ? "حساب WARP فعال است" : "به حساب WireGuard / WARP نیاز دارد" }].map(item => <Card className="outbound-tile" key={item.tag}><strong>{item.name}</strong><p>{item.text}</p><Badge tone={selected === item.tag ? "success" : "neutral"}>{selected === item.tag ? "پیش‌فرض" : item.tag === "warp" && !query.data?.warp_enabled ? "تنظیم نشده" : "آماده"}</Badge></Card>)}</div>
      <Card className="integration-card"><Field label="خروجی پیش‌فرض"><Select disabled={!canManage} value={selected} onChange={e => setSelected(e.target.value)}><option value="direct">Direct</option><option value="ipv4">IPv4</option><option value="blocked">Block</option><option value="warp" disabled={!query.data?.warp_enabled}>WARP</option>{rows.map(row => <option key={row.tag} value={row.tag}>{row.name} ({row.tag})</option>)}</Select></Field><Link className="text-link" to={`/outbounds/warp${node ? `?node_id=${node}` : ""}`}>تنظیم حساب WARP ←</Link></Card>
      {rows.map((row, index) => <Card key={index} className="integration-card"><SectionHeader title={row.name || "خروجی جدید"} action={canManage && <Button type="button" variant="ghost" onClick={() => setRows(rows.filter((_, i) => i !== index))}>حذف</Button>} />
        <div className="commerce-form"><Field label="نام نمایشی"><Input required disabled={!canManage} value={row.name} onChange={e => patch(index, { name: e.target.value })} /></Field><Field label="شناسهٔ خروجی" hint="با proxy- شروع شود؛ نام انگلیسی یکتا."><Input dir="ltr" required pattern="proxy-[a-zA-Z0-9_-]{1,40}" disabled={!canManage} value={row.tag} onChange={e => patch(index, { tag: e.target.value })} /></Field><Field label="نوع خروجی"><Select disabled={!canManage} value={row.protocol} onChange={e => patch(index, { protocol: e.target.value as Proxy["protocol"] })}><option value="socks">SOCKS5</option><option value="http">HTTP Proxy</option></Select></Field><Field label="آدرس سرور"><Input dir="ltr" required disabled={!canManage} value={row.address} onChange={e => patch(index, { address: e.target.value })} /></Field><Field label="پورت"><Input type="number" required min={1} max={65535} disabled={!canManage} value={row.port} onChange={e => patch(index, { port: Number(e.target.value) })} /></Field><Field label="نام کاربری، اختیاری"><Input dir="ltr" disabled={!canManage} value={row.username} onChange={e => patch(index, { username: e.target.value })} /></Field>{canManage && <Field label="رمز خروجی" hint={row.password_configured ? "رمز ذخیره شده است؛ خالی یعنی حفظ رمز." : "برای خروجی دارای نام کاربری وارد کنید."}><Input type="password" autoComplete="new-password" value={row.password || ""} onChange={e => patch(index, { password: e.target.value })} /></Field>}</div>
      </Card>)}
      {canManage && <div className="commerce-actions"><Button type="button" variant="outline" onClick={() => setRows([...rows, { tag: `proxy-${Date.now().toString(36)}`, name: "", protocol: "socks", address: "", port: 1080, username: "" }])}>افزودن خروجی</Button><Button type="submit" loading={save.isPending}>ذخیرهٔ خروجی‌ها</Button></div>}
    </form>}
  </div>;
}
