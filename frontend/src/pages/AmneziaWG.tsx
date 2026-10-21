import { t } from "../lib/i18n";import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { API_BASE, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Field, Input, SectionHeader, Select, Textarea } from "../components/UI";

type Params = {enabled: boolean;port: number;server_address: string;jc: number;jmin: number;jmax: number;s1: number;s2: number;h1: number;h2: number;h3: number;h4: number;};

export default function AmneziaWG() {
  const { admin } = useAuth(),toast = useToast(),cache = useQueryClient();
  const [userId, setUserId] = useState("");
  const [search, setSearch] = useState("");
  const [uri, setUri] = useState("");
  const [form, setForm] = useState<Params | null>(null);
  const canReadParams = !!admin?.permissions.includes("inbounds.read");
  const canManage = !!admin?.permissions.includes("inbounds.manage");
  const canGrant = !!admin?.permissions.includes("settings.manage");
  const status = useQuery({ queryKey: ["awg-status"], queryFn: () => api.get<{ready: boolean;port: number;}>("/api/amneziawg/status"), refetchInterval: 10000 });
  const users = useQuery({ queryKey: ["awg-users", search], queryFn: () => api.get<{items: {id: number;username: string;}[];}>(`/api/users?size=100&search=${encodeURIComponent(search)}`) });
  const params = useQuery({ queryKey: ["awg-params"], queryFn: () => api.get<Params>("/api/amneziawg/params"), enabled: canReadParams });
  const data = form ?? params.data;
  const action = useMutation({ mutationFn: (operation: () => Promise<unknown>) => operation(), onSuccess: () => {cache.invalidateQueries({ queryKey: ["awg-params"] });cache.invalidateQueries({ queryKey: ["awg-status"] });toast.success(t("عملیات ثبت شد؛ همگام‌سازی سرویس ممکن است چند ثانیه طول بکشد."));}, onError: (error: Error) => toast.error(error.message) });
  const selected = Number(userId);
  const validUser = Number.isInteger(selected) && selected > 0;
  return <div className="commerce-page">
    <SectionHeader title="AmneziaWG" subtitle={t("دسترسی مستقل کاربران، کانفیگ IPv4 و تنظیمات مبهم‌سازی.")} />
    <Card className="integration-card"><Badge tone={status.data?.ready ? "success" : "warning"}>{status.data?.ready ? t("سرویس آماده است") : t("سرویس آماده نیست")}</Badge>
      {status.error && <p role="alert">{status.error.message}</p>}
      {!status.data?.ready && <p>{t("برای فعال‌شدن این قابلیت، سرویس AmneziaWG باید روی سرور نصب شده باشد. راهنمای نصب در مستندات پنل آمده است.")}</p>}
    </Card>
    <Card className="integration-card"><SectionHeader title={t("دسترسی کاربر")} subtitle={t("کاربر را انتخاب کنید. دانلود کانفیگ به‌تنهایی دسترسی جدید ایجاد نمی‌کند.")} />
      <Field label={t("جست‌وجوی کاربر")}><Input value={search} onChange={(e) => {setSearch(e.target.value);setUserId("");setUri("");}} /></Field>
      <Field label={t("کاربر")}><Select value={userId} onChange={(e) => {setUserId(e.target.value);setUri("");}}><option value="">{t("انتخاب کنید")}</option>{users.data?.items.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}</Select></Field>
      {users.error && <p role="alert">{users.error.message}</p>}
      <div className="xray-actions">
        {canGrant && <Button disabled={!validUser || !status.data?.ready || action.isPending} onClick={() => action.mutate(() => api.post(`/api/amneziawg/client/${selected}/grant`))}>{t("اعطای دسترسی")}</Button>}
        {canGrant && <Button variant="danger" disabled={!validUser || action.isPending} onClick={() => action.mutate(() => api.delete(`/api/amneziawg/client/${selected}/grant`))}>{t("لغو دسترسی")}</Button>}
        <Button variant="outline" disabled={!validUser || action.isPending} onClick={() => action.mutate(async () => {
          const response = await fetch(`${API_BASE}/api/amneziawg/client/${selected}/config`, { credentials: "include" });
          if (!response.ok) {const result = await response.json();throw new Error(result.detail || t("دریافت کانفیگ ناموفق بود."));}
          const url = URL.createObjectURL(await response.blob());const anchor = document.createElement("a");anchor.href = url;anchor.download = `user-${selected}-awg.conf`;anchor.click();setTimeout(() => URL.revokeObjectURL(url), 1000);
        })}>{t("دانلود کانفیگ")}</Button>
        <Button variant="outline" disabled={!validUser || action.isPending} onClick={() => action.mutate(async () => {const result = await api.get<{uri: string;}>(`/api/amneziawg/client/${selected}/vpn`);setUri(result.uri);})}>{t("لینک و QR")}</Button>
      </div>
      {uri && <><Textarea readOnly value={uri} dir="ltr" /><div style={{ background: "white", padding: 16, width: "fit-content" }}><QRCodeSVG value={uri} size={220} /></div></>}
    </Card>
    {params.error && <Card><p role="alert">{params.error.message}</p>{canManage && <Button disabled={action.isPending} onClick={() => action.mutate(() => api.post("/api/amneziawg/randomize"))}>{t("تولید پارامترهای معتبر")}</Button>}</Card>}
    {canReadParams && data && <Card className="integration-card"><SectionHeader title={t("پارامترهای سرویس")} subtitle={t("تغییر پارامترها نیازمند دریافت دوبارهٔ کانفیگ کاربران است. تغییر پورت باید با نصب مجدد سرویس و فایروال هماهنگ شود.")} />
      <form onSubmit={(e) => {e.preventDefault();action.mutate(() => api.put("/api/amneziawg/params", data));}}>
        <fieldset disabled={!canManage || action.isPending} className="settings-fieldset">
          <label><input type="checkbox" checked={data.enabled} onChange={(e) => setForm({ ...data, enabled: e.target.checked })} />{" " + t("فعال‌بودن دسترسی AmneziaWG") + ""}</label>
          <div className="form-grid">{(["port", "jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4"] as const).map((key) => <Field label={key.toUpperCase()} key={key}><Input type="number" min={1} value={data[key]} onChange={(e) => setForm({ ...data, [key]: Number(e.target.value) })} /></Field>)}</div>
          {canManage && <Button type="submit">{t("ذخیرهٔ پارامترها")}</Button>}
        </fieldset>
      </form>
    </Card>}
  </div>;
}
