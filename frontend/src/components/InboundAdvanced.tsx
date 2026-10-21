import { t } from "../lib/i18n";import { useState } from 'react';
import { Button, Field, Input, Select, Textarea, Toggle } from './UI';
import { api } from '../lib/api';
import { useToast } from '../lib/toast';
import { useQuery } from '@tanstack/react-query';

type Section = Record<string, unknown>;
type Options = Record<string, unknown>;
interface Props {value: string;onChange: (value: string) => void;network: string;security: string;}

export default function InboundAdvanced({ value, onChange, network, security }: Props) {
  const [tab, setTab] = useState('subscription');
  const [busy, setBusy] = useState(false),toast = useToast();
  const users = useQuery({ queryKey: ['inbound-user-picker'], queryFn: () => api.get<{items: {id: number;username: string;}[];}>('/api/users?size=100'), enabled: tab === 'external' });
  let data: Options;
  try {data = JSON.parse(value || '{}') as Options;} catch {return <p role="alert">{t("ساختار تنظیمات پیشرفته معتبر نیست.")}</p>;}
  function read(section: string, key: string, fallback: unknown) {return (section ? (data[section] as Section | undefined)?.[key] : data[key]) ?? fallback;}
  function write(section: string, key: string, next: unknown) {onChange(JSON.stringify(section ? { ...data, [section]: { ...(data[section] as Section || {}), [key]: next } } : { ...data, [key]: next }));}
  async function generate(kind: string) {setBusy(true);try {const result = await api.post<Section>(`/api/inbounds/crypto/${kind}`);const section = kind === 'ech' ? 'tls' : kind === 'mldsa65' ? 'reality' : '';onChange(JSON.stringify(section ? { ...data, [section]: { ...(data[section] as Section || {}), ...result } } : { ...data, ...result }));} catch (e) {toast.error(e instanceof Error ? e.message : t("ساخت کلید ناموفق بود."));} finally {setBusy(false);}}
  function text(section: string, key: string, label: string, fallback = '') {return <Field key={key} label={label}><Input dir="ltr" type={["echServerKeys", "mldsa65Seed", "vless_decryption"].includes(key) ? "password" : "text"} value={String(read(section, key, fallback))} onChange={(e) => write(section, key, e.target.value)} /></Field>;}
  function number(section: string, key: string, label: string, fallback: number, min = 0, max = 1000000) {return <Field key={key} label={label}><Input type="number" min={min} max={max} value={String(read(section, key, fallback))} onChange={(e) => write(section, key, Number(e.target.value))} /></Field>;}
  function toggle(section: string, key: string, label: string, fallback = false) {return <Toggle key={key} label={label} checked={Boolean(read(section, key, fallback))} onChange={(next) => write(section, key, next)} />;}
  function list(section: string, key: string, label: string, fallback: string[] = []) {return <Field key={key} label={label} hint={t("هر مورد در یک خط؛ خط‌های خالی هنگام ذخیره حذف می‌شوند.")}><Textarea dir="ltr" value={(read(section, key, fallback) as string[]).join('\n')} onChange={(e) => write(section, key, e.target.value.split('\n'))} /></Field>;}
  const tabs = [['subscription', t("اشتراک")], ['stream', t("انتقال")], ['tls', 'TLS'], ['reality', 'Reality'], ['external', 'ShadowTLS / MTProto'], ['encryption', t("رمزنگاری VLESS")], ['masks', 'FinalMask'], ['fallbacks', 'Fallbacks'], ['sniffing', 'Sniffing'], ['sockopt', 'Sockopt']];
  return <div className="field-span-2 inbound-advanced">
    <h3>{t("تنظیمات پیشرفتهٔ اینباند")}</h3>
    <div className="commerce-actions" role="tablist" aria-label={t("تنظیمات پیشرفته اینباند")}>{tabs.map(([key, label]) => <Button key={key} type="button" role="tab" aria-selected={tab === key} variant={tab === key ? 'primary' : 'outline'} onClick={() => setTab(key)}>{label}</Button>)}</div>
    <div className="form-grid" role="tabpanel">
      {tab === 'subscription' && <>{number('', 'subscription_order', t("ترتیب در اشتراک"), 0)}{text('', 'share_host', t("آدرس انتشار کانفیگ (اختیاری)"))}<Field label={t("پورت انتشار کانفیگ (اختیاری)")} hint={t("پورت عمومی پشت پراکسی؛ خالی یعنی همان پورت شنود.")}><Input type="number" min={1} max={65535} value={String(data.share_port ?? '')} onChange={(e) => write('', 'share_port', e.target.value ? Number(e.target.value) : null)} /></Field>{toggle('', 'exclude_from_subscription', t("حذف از خروجی اشتراک"))}<p className="field-span-2 field-hint">{t("حذف از اشتراک، حساب‌ها را از سرور حذف نمی‌کند. محدودیت دسترسی کاربر و گروه همچنان مستقل اعمال می‌شود.")}</p></>}
      {tab === 'stream' && <>
        {network !== 'kcp' && toggle('', 'proxy_protocol', t("دریافت PROXY protocol از پراکسی مورد اعتماد"))}
        {network === 'tcp' && <>{toggle('', 'tcp_http_obfuscation', t("HTTP Obfuscation روی RAW/TCP"))}{toggle('', 'disable_xtls_flow', t("غیرفعال‌کردن XTLS Flow"))}</>}
        {network === 'xhttp' && <><Field label={t("حالت XHTTP")}><Select value={String(read('xhttp', 'mode', 'auto'))} onChange={(e) => write('xhttp', 'mode', e.target.value)}>{['auto', 'packet-up', 'stream-up', 'stream-one'].map((mode) => <option key={mode}>{mode}</option>)}</Select></Field>{toggle('xhttp', 'noGRPCHeader', t("حذف هدر gRPC"))}{toggle('xhttp', 'noSSEHeader', t("حذف هدر SSE"))}{number('xhttp', 'scMaxBufferedPosts', t("سقف درخواست‌های بافرشده"), 30, 1, 10000)}</>}
        {network === 'kcp' && <>{number('kcp', 'mtu', 'mKCP MTU', 1350, 576, 1460)}{number('kcp', 'tti', 'mKCP TTI', 50, 10, 5000)}{number('kcp', 'uplinkCapacity', t("ظرفیت آپلود mKCP"), 5, 0, 10000)}{number('kcp', 'downlinkCapacity', t("ظرفیت دانلود mKCP"), 20, 0, 10000)}{number('kcp', 'readBufferSize', t("بافر خواندن (MiB)"), 2, 0, 64)}{number('kcp', 'writeBufferSize', t("بافر نوشتن (MiB)"), 2, 0, 64)}{toggle('kcp', 'congestion', t("کنترل ازدحام mKCP"))}</>}
        <p className="field-span-2 field-hint">{t("تنظیمات دو سمت اتصال باید سازگار باشند. برای mKCP و HTTP Obfuscation از خروجی کامل Xray JSON استفاده کنید. PROXY protocol فقط پشت پراکسی مورد اعتماد فعال شود.")}</p>
      </>}
      {tab === 'tls' && (security !== 'tls' ? <p>{t("برای این بخش، لایهٔ امنیت را روی TLS قرار دهید.")}</p> : <>
        <Button type="button" loading={busy} onClick={() => generate('ech')}>{t("ساخت کلید ECH")}</Button>
        {text('tls', 'echServerKeys', t("کلید خصوصی ECH سرور"))}{text('tls', 'echConfigList', t("ECH Config کلاینت"))}
        {(['minVersion', 'maxVersion'] as const).map((key, i) => <Field key={key} label={i ? t("حداکثر نسخه TLS") : t("حداقل نسخه TLS")}><Select value={String(read('tls', key, i ? '1.3' : '1.2'))} onChange={(e) => write('tls', key, e.target.value)}><option>1.2</option><option>1.3</option></Select></Field>)}
        {text('tls', 'cipherSuites', t("Cipher Suites (جداشده با :)"))}{list('tls', 'curvePreferences', 'Curve Preferences')}{toggle('tls', 'rejectUnknownSni', t("رد کردن SNI ناشناس"))}{toggle('tls', 'disableSystemRoot', t("عدم استفاده از گواهی‌های ریشهٔ سیستم"))}{toggle('tls', 'enableSessionResumption', 'TLS Session Resumption')}
      </>)}
      {tab === 'reality' && (security !== 'reality' ? <p>{t("برای این بخش، لایهٔ امنیت را روی Reality قرار دهید.")}</p> : <>
        <Button type="button" loading={busy} onClick={() => generate('mldsa65')}>{t("ساخت جفت کلید ML-DSA-65")}</Button>
        {text('reality', 'mldsa65Seed', t("Seed خصوصی ML-DSA-65"))}{text('reality', 'mldsa65Verify', t("کلید تأیید ML-DSA-65"))}
        {list('reality', 'serverNames', t("SNIهای مجاز Reality"))}{list('reality', 'shortIds', t("Short IDهای Reality"))}{number('reality', 'xver', t("نسخه PROXY مقصد Reality"), 0, 0, 2)}{number('reality', 'maxTimeDiff', t("حداکثر اختلاف زمان (میلی‌ثانیه)"), 0, 0, 86400000)}{text('reality', 'minClientVer', t("حداقل نسخه کلاینت Reality"))}{text('reality', 'maxClientVer', t("حداکثر نسخه کلاینت Reality"))}{text('reality', 'spiderX', 'SpiderX', '/')}
        {(['limitFallbackUpload', 'limitFallbackDownload'] as const).map((key, i) => <div className="field-span-2" key={key}><h4>{i ? t("محدودیت دانلود fallback") : t("محدودیت آپلود fallback")}</h4><div className="form-grid">{[['afterBytes', t("پس از چند بایت")], ['bytesPerSec', t("بایت در ثانیه")], ['burstBytesPerSec', t("سقف لحظه‌ای بایت در ثانیه")]].map(([field, label]) => <Field label={label} key={field}><Input type="number" min={0} max={9007199254740991} value={String(((data.reality as Section)?.[key] as Section)?.[field] ?? 0)} onChange={(e) => {const reality = data.reality as Section || {};onChange(JSON.stringify({ ...data, reality: { ...reality, [key]: { ...(reality[key] as Section || {}), [field]: Number(e.target.value) } } }));}} /></Field>)}</div></div>)}
        <p className="field-span-2 field-hint">{t("اولین SNI و Short ID از فهرست‌های بالا در خروجی کلاینت استفاده می‌شود؛ فهرست خالی از مقدار بخش اصلی استفاده می‌کند.")}</p>
      </>)}
      {tab === 'fallbacks' && <div className="field-span-2">
        <p className="field-hint">{t("RAW/TCP همراه TLS؛ مقصدها پورت‌های محلی هستند. اینباند داخلی را روی 127.0.0.1 بسازید. برای مسیرها SNI، ALPN یا path تعیین کنید.")}</p>
        {(Array.isArray(data.fallbacks) ? data.fallbacks as Section[] : []).map((row, i) => <div className="form-grid" key={i}>
          {['name', 'alpn', 'path', 'dest', 'xver'].map((key) => <Field key={key} label={key}><Input dir="ltr" type={['dest', 'xver'].includes(key) ? 'number' : 'text'} value={String(row[key] ?? '')} onChange={(e) => {const rows = [...(data.fallbacks as Section[])];rows[i] = { ...row, [key]: ['dest', 'xver'].includes(key) ? Number(e.target.value) : e.target.value };write('', 'fallbacks', rows);}} /></Field>)}
          <Button type="button" variant="danger" onClick={() => write('', 'fallbacks', (data.fallbacks as Section[]).filter((_, n) => n !== i))}>{t("حذف مسیر")}</Button>
        </div>)}
        <Button type="button" onClick={() => write('', 'fallbacks', [...(Array.isArray(data.fallbacks) ? data.fallbacks : []), { name: '', alpn: '', path: '', dest: 8080, xver: 0 }])}>{t("افزودن Fallback")}</Button>
      </div>}
      {tab === 'encryption' && <>
        <p className="field-span-2 field-hint">{t("فقط VLESS روی Xray؛ خروجی کامل Xray JSON لازم است. جفت کلید با احراز هویت ML-KEM-768 ساخته می‌شود. با Fallback سازگار نیست.")}</p>
        <Button type="button" loading={busy} onClick={() => generate('vlessenc')}>{t("ساخت جفت کلید VLESS Encryption")}</Button>
        {text('', 'vless_decryption', t("کلید رمزگشایی سرور"), 'none')}{text('', 'vless_encryption', t("کلید رمزنگاری کلاینت"), 'none')}
      </>}
      {tab === 'external' && <>
        {text('', 'shadowtls_handshake', t("دامنهٔ دست‌دهی ShadowTLS"), 'www.cloudflare.com')}{number('', 'shadowtls_handshake_port', t("پورت دست‌دهی ShadowTLS"), 443, 1, 65535)}
        <Field label={t("کاربر اختصاصی این ورودی MTProto")} hint={t("هر ورودی MTProto یک کاربر و یک پورت عمومی دارد. دسترسی آن کاربر به همین اینباند نیز باید مجاز باشد.")}><Select value={String(data.mtproto_user_id || '')} onChange={(e) => write('', 'mtproto_user_id', e.target.value ? Number(e.target.value) : null)}><option value="">{t("انتخاب کاربر")}</option>{users.data?.items.map((user) => <option value={user.id} key={user.id}>{user.username}</option>)}</Select></Field>
        {text('', 'mtproto_domain', t("دامنهٔ FakeTLS تلگرام"), 'www.cloudflare.com')}
      </>}
      {tab === 'masks' && <div className="field-span-2"><p className="field-hint">{t("FinalMask فقط با Xray؛ هر دو طرف باید تنظیمات یکسان داشته باشند. از خروجی Xray JSON استفاده کنید.")}</p>
        <Button type="button" onClick={() => write('', 'finalmask', { tcp: [{ type: 'sudoku', settings: { password: crypto.randomUUID() } }], udp: [] })}>{t("افزودن Sudoku برای TCP")}</Button> <Button type="button" onClick={() => write('', 'finalmask', { tcp: [], udp: [{ type: 'salamander', settings: { password: crypto.randomUUID() } }] })}>{t("افزودن Salamander برای mKCP")}</Button> <Button type="button" variant="danger" onClick={() => write('', 'finalmask', { tcp: [], udp: [] })}>{t("حذف ماسک‌ها")}</Button>
        <MaskEditor key={JSON.stringify(data.finalmask)} value={data.finalmask ?? { tcp: [], udp: [] }} onChange={(next) => write('', 'finalmask', next)} />
      </div>}
      {tab === 'sniffing' && <>{toggle('sniffing', 'enabled', t("Sniffing فعال"), true)}{toggle('sniffing', 'routeOnly', t("فقط برای مسیریابی"))}{toggle('sniffing', 'metadataOnly', t("فقط فراداده"))}{list('sniffing', 'destOverride', t("پروتکل‌های تشخیص (http / tls / quic / fakedns)"), ['http', 'tls', 'quic'])}{list('sniffing', 'domainsExcluded', t("دامنه‌های مستثنا از Sniffing"))}</>}
      {tab === 'sockopt' && <>{toggle('', 'sockopt_enabled', t("تنظیمات Socket فعال"))}{Boolean(data.sockopt_enabled) && <>{toggle('sockopt', 'tcpFastOpen', 'TCP Fast Open')}{toggle('sockopt', 'tcpMptcp', 'Multipath TCP')}{toggle('sockopt', 'v6only', t("فقط IPv6"))}{number('sockopt', 'tcpKeepAliveIdle', t("TCP Keepalive Idle (ثانیه)"), 300, 0, 86400)}{number('sockopt', 'tcpKeepAliveInterval', t("TCP Keepalive Interval (ثانیه)"), 30, 0, 86400)}{number('sockopt', 'tcpUserTimeout', t("TCP User Timeout (میلی‌ثانیه)"), 0, 0, 86400000)}{text('sockopt', 'tcpCongestion', t("TCP Congestion (مانند bbr)"))}{text('sockopt', 'interface', t("رابط شبکه"))}<Field label={t("راهبرد DNS سوکت")}><Select value={String(read('sockopt', 'domainStrategy', 'AsIs'))} onChange={(e) => write('sockopt', 'domainStrategy', e.target.value)}>{['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'UseIPv4v6', 'UseIPv6v4', 'ForceIP', 'ForceIPv4', 'ForceIPv6'].map((v) => <option key={v}>{v}</option>)}</Select></Field></>}<p className="field-span-2 field-hint">{t("پشتیبانی عملی Socket به سیستم‌عامل نود و مجوز سرویس وابسته است؛ این تنظیمات فقط سمت سرور اعمال می‌شوند.")}</p></>}
    </div>
  </div>;
}

export function serializeAdvanced(value: string): string {
  const data = JSON.parse(value || '{}');
  for (const [section, key] of [['tls', 'curvePreferences'], ['reality', 'serverNames'], ['reality', 'shortIds'], ['sniffing', 'destOverride'], ['sniffing', 'domainsExcluded']]) {
    if (Array.isArray(data[section]?.[key])) data[section][key] = data[section][key].map((s: string) => s.trim()).filter(Boolean);
  }
  if (!data.sockopt_enabled) data.sockopt = null;
  delete data.sockopt_enabled;
  return JSON.stringify(data);
}


function MaskEditor({ value, onChange }: {value: unknown;onChange: (value: unknown) => void;}) {
  const [draft, setDraft] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState(false);
  return <div><Textarea dir="ltr" rows={9} value={draft} onChange={(e) => {setDraft(e.target.value);try {JSON.parse(e.target.value);e.currentTarget.setCustomValidity('');setError(false);} catch {e.currentTarget.setCustomValidity('Invalid JSON');setError(true);}}} onBlur={() => {try {onChange(JSON.parse(draft));} catch {setError(true);}}} />{error && <p role="alert">Invalid JSON</p>}</div>;
}
