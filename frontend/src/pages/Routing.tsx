import { t, tt } from "../lib/i18n";import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { Node } from "../lib/types";
import { Wand2 } from "lucide-react";
import { Button, Card, Field, Input, Select, Textarea, Toggle, SectionHeader, Spinner } from "../components/UI";

type Outbound = string;
interface Rule {outbound: Outbound;domains: string[];ips: string[];inbound_ids: number[];protocols?: string[];network?: string | null;port?: string | null;}
interface Policy {outbounds: {tag: string;name: string;}[];default_outbound: Outbound;domain_strategy: string;block_bittorrent: boolean;block_ips: string[];block_domains: string[];direct_ips: string[];direct_domains: string[];ipv4_domains: string[];warp_enabled: boolean;warp_endpoint: string;warp_public_key: string;warp_addresses: string[];warp_reserved: number[];warp_mtu: number;rules: Rule[];private_key_configured: boolean;}
const split = (value: string) => value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);

export default function Routing({ mode = "rules" }: {mode?: "rules" | "warp";}) {
  const [searchParams] = useSearchParams();
  const { admin } = useAuth();
  const toast = useToast();
  const cache = useQueryClient();
  const [node, setNode] = useState(searchParams.get("node_id") || "");
  const canManage = !!admin?.permissions.includes("routing.manage");
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [privateKey, setPrivateKey] = useState("");
  const [addresses, setAddresses] = useState("");
  const [reserved, setReserved] = useState("0,0,0");
  const suffix = node ? `?node_id=${node}` : "";
  const result = useQuery({ queryKey: ["routing", node], queryFn: () => api.get<Policy>(`/api/routing${suffix}`), enabled: !!admin?.permissions.includes("routing.read") });
  const nodes = useQuery({ queryKey: ["nodes"], queryFn: () => api.get<Node[]>("/api/nodes"), enabled: !!admin?.permissions.includes("routing.read") });
  const resources = useQuery({ queryKey: ["resource-options"], queryFn: () => api.get<{inbounds: {id: number;name: string;tag: string;node_id: number | null;}[];}>("/api/users/access-options"), enabled: !!admin?.permissions.includes("routing.read") });
  useEffect(() => {if (result.data) {setPolicy(result.data);setPrivateKey("");setAddresses(result.data.warp_addresses.join("\n"));setReserved(result.data.warp_reserved.join(","));}}, [result.data]);
  const autoRegisterWarp = useMutation({
    mutationFn: () =>
    api.post<{
      ok: boolean;
      warp_private_key: string;
      warp_public_key: string;
      warp_endpoint: string;
      warp_addresses: string[];
      warp_reserved: number[];
      message?: string;
    }>(`/api/routing/warp/auto-register${suffix}`),
    onSuccess: (data) => {
      setPolicy((current) =>
      current && {
        ...current,
        warp_enabled: true,
        warp_endpoint: data.warp_endpoint,
        warp_public_key: data.warp_public_key,
        warp_addresses: data.warp_addresses,
        warp_reserved: data.warp_reserved
      }
      );
      setPrivateKey(data.warp_private_key);
      setAddresses(data.warp_addresses.join("\n"));
      setReserved(data.warp_reserved.join(","));
      toast.success(data.message || t("حساب جدید WARP ثبت شد و اطلاعات پر گردید."));
    },
    onError: (e: Error) => toast.error(e.message)
  });

  const save = useMutation({ mutationFn: () => api.put(`/api/routing${suffix}`, { ...policy, ...Object.fromEntries(["block_ips", "block_domains", "direct_ips", "direct_domains", "ipv4_domains"].map((key) => [key, ((policy as unknown as Record<string, string[]>)[key] || []).map((s) => s.trim()).filter(Boolean)])), warp_addresses: split(addresses), warp_reserved: reserved.split(",").map(Number), rules: policy?.rules.map((r) => ({ ...r, domains: r.domains.map((s) => s.trim()).filter(Boolean), ips: r.ips.map((s) => s.trim()).filter(Boolean) })), ...(privateKey ? { warp_private_key: privateKey } : {}) }), onSuccess: () => {setPrivateKey("");cache.invalidateQueries({ queryKey: ["routing", node] });toast.success(t("مسیریابی ذخیره شد؛ در همگام‌سازی بعدی هسته اعمال می‌شود."));}, onError: (e: Error) => toast.error(e.message) });
  function patchRule(index: number, patch: Partial<Rule>) {setPolicy((current) => current && { ...current, rules: current.rules.map((rule, i) => i === index ? { ...rule, ...patch } : rule) });}
  if (!admin?.permissions.includes("routing.read")) return <p>{t("این بخش فقط در دسترس مالک پنل است.")}</p>;
  const options = resources.data?.inbounds.filter((i) => node ? i.node_id === Number(node) : !i.node_id || nodes.data?.some((n) => n.id === i.node_id && n.is_local)) ?? [];
  return <div className="commerce-page">
    <SectionHeader title={mode === "warp" ? t("حساب WARP") : t("قوانین مسیریابی")} subtitle={mode === "warp" ? t("مشخصات حساب WireGuard / WARP برای خروجی همین سرور.") : t("تعیین کنید ترافیک هر دامنه، IP یا اینباند از کدام خروجی عبور کند.")} action={<Link className="text-link" to="/outbounds">{t("خروجی‌ها ←")}</Link>} />
    {!canManage && <p className="field-hint">{t("دسترسی شما در این بخش فقط مشاهده است. برای تغییر، مجوز مدیریت مسیریابی لازم است.")}</p>}
    <Field label={t("نود")}><Select value={node} onChange={(e) => {setNode(e.target.value);setPolicy(null);setPrivateKey("");}}><option value="">{t("سرور محلی")}</option>{nodes.data?.filter((n) => !n.is_local).map((n) => <option value={n.id} key={n.id}>{n.name}</option>)}</Select></Field>
    {result.error ? <p role="alert">{result.error.message}</p> : !policy ? <Spinner /> : <form onSubmit={(e) => {e.preventDefault();save.mutate();}}><fieldset className="settings-fieldset" disabled={!canManage}>
      {mode === "warp" && <>
      <Card className="integration-card"><SectionHeader title={t("مشخصات حساب WARP")} action={<Button type="button" variant="outline" size="sm" icon={<Wand2 size={15} />} loading={autoRegisterWarp.isPending} onClick={() => autoRegisterWarp.mutate()}>{t("ثبت خودکار حساب WARP (۱-کلیک)")}</Button>} />
        <div className="commerce-form">

          <Toggle checked={policy.warp_enabled} onChange={(warp_enabled) => setPolicy({ ...policy, warp_enabled })} label={t("خروجی WARP فعال")} />
          <Field label="Endpoint"><Input dir="ltr" required value={policy.warp_endpoint} onChange={(e) => setPolicy({ ...policy, warp_endpoint: e.target.value })} /></Field>
          <Field label={t("کلید عمومی Peer")}><Input dir="ltr" value={policy.warp_public_key} onChange={(e) => setPolicy({ ...policy, warp_public_key: e.target.value })} /></Field>
          <Field label={t("کلید خصوصی حساب WARP")} hint={policy.private_key_configured ? t("کلید ذخیره شده است؛ خالی یعنی بدون تغییر.") : t("از پروفایل WireGuard حساب WARP خودتان وارد کنید.")}><Input dir="ltr" type="password" autoComplete="new-password" value={privateKey} onChange={(e) => setPrivateKey(e.target.value)} /></Field>
          <Field label={t("آدرس‌های تونل (CIDR؛ هر خط یک آدرس)")}><Textarea dir="ltr" value={addresses} onChange={(e) => setAddresses(e.target.value)} /></Field>
          <Field label={t("Reserved (سه بایت جداشده با ویرگول)")}><Input dir="ltr" value={reserved} onChange={(e) => setReserved(e.target.value)} /></Field>
          <Field label="MTU"><Input type="number" min="1280" max="1500" required value={policy.warp_mtu} onChange={(e) => setPolicy({ ...policy, warp_mtu: Number(e.target.value) })} /></Field>
        </div>
        <p className="field-hint">{t("کلید خصوصی رمزگذاری می‌شود و فقط به هسته همان نود تحویل داده می‌شود. مشخصات حساب باید از پروفایل معتبر خودتان باشد؛ ذخیره تنظیمات به معنی تأیید اتصال زنده WARP نیست.")}</p>
      </Card>
      </>}
      {mode === "rules" && <>

      <Card className="integration-card"><SectionHeader title={t("مسیریابی پایه")} subtitle={t("این قواعد پس از محافظت از API و مقصدهای خصوصی، پیش از قوانین سفارشی بررسی می‌شوند.")} />
        <div className="commerce-form">
          <Field label={t("راهبرد دامنه در Routing")}><Select value={policy.domain_strategy} onChange={(e) => setPolicy({ ...policy, domain_strategy: e.target.value })}>{['AsIs', 'IPIfNonMatch', 'IPOnDemand'].map((v) => <option key={v}>{v}</option>)}</Select></Field>
          <Toggle label={t("مسدودسازی BitTorrent")} checked={policy.block_bittorrent} onChange={(block_bittorrent) => setPolicy({ ...policy, block_bittorrent })} />
          {([['block_ips', t("IPهای مسدود")], ['block_domains', t("دامنه‌های مسدود")], ['direct_ips', t("IPهای مستقیم")], ['direct_domains', t("دامنه‌های مستقیم")], ['ipv4_domains', t("دامنه‌های خروجی IPv4")]] as const).map(([key, label]) => <Field key={key} label={label} hint={t("هر خط یک شرط؛ مانند geoip:ir یا geosite:google یا domain:example.com")}><Textarea dir="ltr" value={(policy[key] || []).join('\n')} onChange={(e) => setPolicy({ ...policy, [key]: e.target.value.split('\n') })} /></Field>)}
          <p className="field-hint">{t("تشخیص BitTorrent به Sniffing فعال نیاز دارد. قواعد geoip/geosite به فایل‌های دادهٔ همان نود وابسته‌اند؛ خروجی IPv4 به دسترسی IPv4 سرور و نتیجهٔ DNS وابسته است.")}</p>
        </div>
      </Card>
      {policy.rules.map((rule, index) => <Card key={index} className="integration-card"><SectionHeader title={tt("قانون {0}", [index + 1])} action={<Button type="button" variant="ghost" onClick={() => setPolicy({ ...policy, rules: policy.rules.filter((_, i) => i !== index) })}>{t("حذف قانون")}</Button>} />
        <div className="commerce-form">
          <Field label={t("خروجی قانون")}><Select value={rule.outbound} onChange={(e) => patchRule(index, { outbound: e.target.value as Outbound })}><option value="direct">Direct</option><option value="warp">WARP</option><option value="blocked">Block</option><option value="ipv4">IPv4</option>{policy.outbounds?.map((o) => <option key={o.tag} value={o.tag}>{o.name}</option>)}</Select></Field>
          <Field label={t("اینباندها (خالی یعنی همه)")}><Select multiple value={rule.inbound_ids.map(String)} onChange={(e) => patchRule(index, { inbound_ids: Array.from(e.target.selectedOptions, (o) => Number(o.value)) })}>{options.map((i) => <option key={i.id} value={i.id}>{i.name} · {i.tag}</option>)}</Select></Field>
          <Field label={t("دامنه‌ها")} hint={t("هر خط یک شرط؛ برای نمونه domain:example.com یا geosite:category-ads-all")}><Textarea dir="ltr" value={rule.domains.join("\n")} onChange={(e) => patchRule(index, { domains: e.target.value.split("\n") })} /></Field>
          <Field label={t("IP و CIDR")} hint={t("برای نمونه 203.0.113.0/24؛ شرط‌های دامنه، IP و اینباند با هم اعمال می‌شوند.")}><Textarea dir="ltr" value={rule.ips.join("\n")} onChange={(e) => patchRule(index, { ips: e.target.value.split("\n") })} /></Field>
          <Field label={t("شبکهٔ قانون")}><Select value={rule.network || ''} onChange={(e) => patchRule(index, { network: e.target.value || null })}><option value="">{t("همه")}</option><option value="tcp">TCP</option><option value="udp">UDP</option><option value="tcp,udp">TCP + UDP</option></Select></Field>
          <Field label={t("پورت مقصد")} hint={t("مانند 443 یا 80,8000-9000")}><Input dir="ltr" value={rule.port || ''} onChange={(e) => patchRule(index, { port: e.target.value || null })} /></Field>
          <Field label={t("پروتکل‌های تشخیص‌داده‌شده")}><Select multiple value={rule.protocols || []} onChange={(e) => patchRule(index, { protocols: Array.from(e.target.selectedOptions, (o) => o.value) })}>{['http', 'tls', 'quic', 'bittorrent'].map((v) => <option key={v}>{v}</option>)}</Select></Field>
        </div>
      </Card>)}
      </>}
      <div className="commerce-actions">{mode === "rules" && <Button type="button" variant="outline" onClick={() => setPolicy({ ...policy, rules: [...policy.rules, { outbound: "direct", domains: [], ips: [], inbound_ids: [] }] })}>{t("افزودن قانون")}</Button>}<Button type="submit" loading={save.isPending}>{t("ذخیره مسیریابی")}</Button></div>
    </fieldset></form>}
  </div>;
}
