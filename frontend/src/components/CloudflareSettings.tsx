import { t } from "../lib/i18n";import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useToast } from '../lib/toast';
import { Button, Card, Field, Input, Select, Toggle } from './UI';
type Config = {zone_id?: string;auto_cdn?: boolean;inbound_ids?: number[];interval_hours?: number;token_configured?: boolean;};
export default function CloudflareSettings() {
  const toast = useToast(),cache = useQueryClient();
  const query = useQuery({ queryKey: ['cloudflare-config'], queryFn: () => api.get<Config>('/api/integrations/cloudflare') });
  const inbounds = useQuery({ queryKey: ['cloudflare-inbounds'], queryFn: () => api.get<{id: number;remark: string;}[]>('/api/inbounds') });
  const [draft, setDraft] = useState<Config | null>(null),[token, setToken] = useState(''),[domain, setDomain] = useState(''),[address, setAddress] = useState(''),[selected, setSelected] = useState('');
  const [results, setResults] = useState<{ip: string;latency_ms: number;}[]>([]);
  const data = draft ?? query.data ?? {};
  const action = useMutation({ mutationFn: async (kind: string) => {
      if (kind === 'save') {const result = await api.put('/api/integrations/cloudflare', { zone_id: data.zone_id, auto_cdn: !!data.auto_cdn, inbound_ids: data.inbound_ids ?? [], interval_hours: data.interval_hours ?? 6, ...(token ? { token } : {}) });setToken('');setDraft(null);return result;}
      if (kind === 'record') return api.post('/api/integrations/cloudflare/record', { domain, address, proxied: true });
      if (kind === 'detect') {const result = await api.post<{address: string;}>('/api/integrations/cloudflare/detect-origin');setAddress(result.address);return result;}
      const result = await api.post<{candidates: {ip: string;latency_ms: number;}[];}>(`/api/integrations/cloudflare/scan/${selected}`);setResults(result.candidates);return result;
    }, onSuccess: () => {cache.invalidateQueries({ queryKey: ['cloudflare-config'] });toast.success(t("عملیات Cloudflare انجام شد."));}, onError: (e: Error) => toast.error(e.message) });
  return <Card className="integration-card"><h3>{t("Cloudflare و IPهای CDN")}</h3><p className="field-hint">{t("توکن محدود به همین Zone با مجوزهای Zone Read و DNS Edit بسازید. برای عبور واقعی کانفیگ، دامنه و وب‌سرور ورودی باید از قبل درست پیکربندی شده باشند.")}</p>
 {query.error && <p role="alert">{query.error.message}</p>}
 <div className="form-grid"><Field label="Zone ID"><Input dir="ltr" value={data.zone_id ?? ''} onChange={(e) => setDraft({ ...data, zone_id: e.target.value })} /></Field><Field label="API Token" hint={data.token_configured ? t("توکن ذخیره شده است؛ خالی یعنی حفظ توکن.") : ''}><Input type="password" autoComplete="new-password" value={token} onChange={(e) => setToken(e.target.value)} /></Field></div>
 <Toggle label={t("انتخاب دوره‌ای IP مناسب CDN")} checked={!!data.auto_cdn} onChange={(auto_cdn) => setDraft({ ...data, auto_cdn })} />
 <Field label={t("فاصلهٔ بررسی (ساعت)")}><Input type="number" min={1} max={168} value={data.interval_hours ?? 6} onChange={(e) => setDraft({ ...data, interval_hours: Number(e.target.value) })} /></Field>
 <Field label={t("اینباندهای بررسی خودکار")}><Select multiple value={(data.inbound_ids ?? []).map(String)} onChange={(e) => setDraft({ ...data, inbound_ids: Array.from(e.target.selectedOptions, (x) => Number(x.value)) })}>{inbounds.data?.map((row) => <option value={row.id} key={row.id}>{row.remark}</option>)}</Select></Field>
 <Button loading={action.isPending} onClick={() => action.mutate('save')}>{t("ذخیرهٔ اتصال Cloudflare")}</Button>
 <div className="form-grid"><Field label={t("دامنهٔ کانفیگ")}><Input dir="ltr" placeholder="vpn.example.com" value={domain} onChange={(e) => setDomain(e.target.value)} /></Field><Field label={t("IP عمومی سرور مقصد")}><Input dir="ltr" value={address} onChange={(e) => setAddress(e.target.value)} /></Field></div>
 <Button variant="outline" loading={action.isPending} onClick={() => action.mutate('detect')}>{t("تشخیص IP همین سرور")}</Button> <Button loading={action.isPending} disabled={!domain || !address} onClick={() => action.mutate('record')}>{t("ساخت/به‌روزرسانی رکورد پروکسی‌شده")}</Button>
 <Field label={t("انتخاب دستی اینباند برای تست CDN")}><Select value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">{t("انتخاب اینباند")}</option>{inbounds.data?.map((row) => <option value={row.id} key={row.id}>{row.remark}</option>)}</Select></Field>
 <Button loading={action.isPending} disabled={!selected} onClick={() => action.mutate('scan')}>{t("تست و انتخاب IP با تأیید TLS")}</Button>
 <p className="field-hint">{t("اندازه‌گیری از سرور انجام می‌شود؛ نتیجهٔ شبکهٔ کاربر ممکن است متفاوت باشد. در شکست تست، IP قبلی حفظ می‌شود.")}</p>
 {results.map((row) => <p key={row.ip}><code>{row.ip}</code> — {row.latency_ms} ms</p>)}
 </Card>;
}
