import { useState } from 'react';
import { Button, Field, Input, Select, Textarea, Toggle } from './UI';

type Section = Record<string, unknown>;
type Options = Record<string, unknown>;
interface Props { value: string; onChange: (value: string) => void; network: string; security: string }

export default function InboundAdvanced({ value, onChange, network, security }: Props) {
  const [tab, setTab] = useState('subscription');
  let data: Options;
  try { data = JSON.parse(value || '{}') as Options; } catch { return <p role="alert">ساختار تنظیمات پیشرفته معتبر نیست.</p>; }
  function read(section: string, key: string, fallback: unknown) { return (section ? (data[section] as Section | undefined)?.[key] : data[key]) ?? fallback; }
  function write(section: string, key: string, next: unknown) { onChange(JSON.stringify(section ? { ...data, [section]: { ...(data[section] as Section || {}), [key]: next } } : { ...data, [key]: next })); }
  function text(section: string, key: string, label: string, fallback = '') { return <Field key={key} label={label}><Input dir="ltr" value={String(read(section, key, fallback))} onChange={e => write(section, key, e.target.value)} /></Field>; }
  function number(section: string, key: string, label: string, fallback: number, min = 0, max = 1000000) { return <Field key={key} label={label}><Input type="number" min={min} max={max} value={String(read(section, key, fallback))} onChange={e => write(section, key, Number(e.target.value))} /></Field>; }
  function toggle(section: string, key: string, label: string, fallback = false) { return <Toggle key={key} label={label} checked={Boolean(read(section, key, fallback))} onChange={next => write(section, key, next)} />; }
  function list(section: string, key: string, label: string, fallback: string[] = []) { return <Field key={key} label={label} hint="هر مورد در یک خط؛ خط‌های خالی هنگام ذخیره حذف می‌شوند."><Textarea dir="ltr" value={(read(section, key, fallback) as string[]).join('\n')} onChange={e => write(section, key, e.target.value.split('\n'))} /></Field>; }
  const tabs = [['subscription', 'اشتراک'], ['stream', 'انتقال'], ['tls', 'TLS'], ['reality', 'Reality'], ['sniffing', 'Sniffing'], ['sockopt', 'Sockopt']];
  return <div className="field-span-2 inbound-advanced">
    <h3>تنظیمات پیشرفتهٔ اینباند</h3>
    <div className="commerce-actions" role="tablist" aria-label="تنظیمات پیشرفته اینباند">{tabs.map(([key, label]) => <Button key={key} type="button" role="tab" aria-selected={tab === key} variant={tab === key ? 'primary' : 'outline'} onClick={() => setTab(key)}>{label}</Button>)}</div>
    <div className="form-grid" role="tabpanel">
      {tab === 'subscription' && <>{number('', 'subscription_order', 'ترتیب در اشتراک', 0)}{text('', 'share_host', 'آدرس انتشار کانفیگ (اختیاری)')}<Field label="پورت انتشار کانفیگ (اختیاری)" hint="پورت عمومی پشت پراکسی؛ خالی یعنی همان پورت شنود."><Input type="number" min={1} max={65535} value={String(data.share_port ?? '')} onChange={e => write('', 'share_port', e.target.value ? Number(e.target.value) : null)} /></Field>{toggle('', 'exclude_from_subscription', 'حذف از خروجی اشتراک')}<p className="field-span-2 field-hint">حذف از اشتراک، حساب‌ها را از سرور حذف نمی‌کند. محدودیت دسترسی کاربر و گروه همچنان مستقل اعمال می‌شود.</p></>}
      {tab === 'stream' && <>
        {network !== 'kcp' && toggle('', 'proxy_protocol', 'دریافت PROXY protocol از پراکسی مورد اعتماد')}
        {network === 'tcp' && <>{toggle('', 'tcp_http_obfuscation', 'HTTP Obfuscation روی RAW/TCP')}{toggle('', 'disable_xtls_flow', 'غیرفعال‌کردن XTLS Flow')}</>}
        {network === 'xhttp' && <><Field label="حالت XHTTP"><Select value={String(read('xhttp', 'mode', 'auto'))} onChange={e => write('xhttp', 'mode', e.target.value)}>{['auto', 'packet-up', 'stream-up', 'stream-one'].map(mode => <option key={mode}>{mode}</option>)}</Select></Field>{toggle('xhttp', 'noGRPCHeader', 'حذف هدر gRPC')}{toggle('xhttp', 'noSSEHeader', 'حذف هدر SSE')}{number('xhttp', 'scMaxBufferedPosts', 'سقف درخواست‌های بافرشده', 30, 1, 10000)}</>}
        {network === 'kcp' && <>{number('kcp', 'mtu', 'mKCP MTU', 1350, 576, 1460)}{number('kcp', 'tti', 'mKCP TTI', 50, 10, 5000)}{number('kcp', 'uplinkCapacity', 'ظرفیت آپلود mKCP', 5, 0, 10000)}{number('kcp', 'downlinkCapacity', 'ظرفیت دانلود mKCP', 20, 0, 10000)}{number('kcp', 'readBufferSize', 'بافر خواندن (MiB)', 2, 0, 64)}{number('kcp', 'writeBufferSize', 'بافر نوشتن (MiB)', 2, 0, 64)}{toggle('kcp', 'congestion', 'کنترل ازدحام mKCP')}</>}
        <p className="field-span-2 field-hint">تنظیمات دو سمت اتصال باید سازگار باشند. برای mKCP و HTTP Obfuscation از خروجی کامل Xray JSON استفاده کنید. PROXY protocol فقط پشت پراکسی مورد اعتماد فعال شود.</p>
      </>}
      {tab === 'tls' && (security !== 'tls' ? <p>برای این بخش، لایهٔ امنیت را روی TLS قرار دهید.</p> : <>
        {(['minVersion', 'maxVersion'] as const).map((key, i) => <Field key={key} label={i ? 'حداکثر نسخه TLS' : 'حداقل نسخه TLS'}><Select value={String(read('tls', key, i ? '1.3' : '1.2'))} onChange={e => write('tls', key, e.target.value)}><option>1.2</option><option>1.3</option></Select></Field>)}
        {text('tls', 'cipherSuites', 'Cipher Suites (جداشده با :)')}{list('tls', 'curvePreferences', 'Curve Preferences')}{toggle('tls', 'rejectUnknownSni', 'رد کردن SNI ناشناس')}{toggle('tls', 'disableSystemRoot', 'عدم استفاده از گواهی‌های ریشهٔ سیستم')}{toggle('tls', 'enableSessionResumption', 'TLS Session Resumption')}
      </>)}
      {tab === 'reality' && (security !== 'reality' ? <p>برای این بخش، لایهٔ امنیت را روی Reality قرار دهید.</p> : <>
        {list('reality', 'serverNames', 'SNIهای مجاز Reality')}{list('reality', 'shortIds', 'Short IDهای Reality')}{number('reality', 'xver', 'نسخه PROXY مقصد Reality', 0, 0, 2)}{number('reality', 'maxTimeDiff', 'حداکثر اختلاف زمان (میلی‌ثانیه)', 0, 0, 86400000)}{text('reality', 'minClientVer', 'حداقل نسخه کلاینت Reality')}{text('reality', 'maxClientVer', 'حداکثر نسخه کلاینت Reality')}{text('reality', 'spiderX', 'SpiderX', '/')}
        {(['limitFallbackUpload', 'limitFallbackDownload'] as const).map((key, i) => <div className="field-span-2" key={key}><h4>{i ? 'محدودیت دانلود fallback' : 'محدودیت آپلود fallback'}</h4><div className="form-grid">{[['afterBytes', 'پس از چند بایت'], ['bytesPerSec', 'بایت در ثانیه'], ['burstBytesPerSec', 'سقف لحظه‌ای بایت در ثانیه']].map(([field, label]) => <Field label={label} key={field}><Input type="number" min={0} max={9007199254740991} value={String(((data.reality as Section)?.[key] as Section)?.[field] ?? 0)} onChange={e => { const reality = data.reality as Section || {}; onChange(JSON.stringify({ ...data, reality: { ...reality, [key]: { ...(reality[key] as Section || {}), [field]: Number(e.target.value) } } })); }} /></Field>)}</div></div>)}
        <p className="field-span-2 field-hint">اولین SNI و Short ID از فهرست‌های بالا در خروجی کلاینت استفاده می‌شود؛ فهرست خالی از مقدار بخش اصلی استفاده می‌کند.</p>
      </>)}
      {tab === 'sniffing' && <>{toggle('sniffing', 'enabled', 'Sniffing فعال', true)}{toggle('sniffing', 'routeOnly', 'فقط برای مسیریابی')}{toggle('sniffing', 'metadataOnly', 'فقط فراداده')}{list('sniffing', 'destOverride', 'پروتکل‌های تشخیص (http / tls / quic / fakedns)', ['http', 'tls', 'quic'])}{list('sniffing', 'domainsExcluded', 'دامنه‌های مستثنا از Sniffing')}</>}
      {tab === 'sockopt' && <>{toggle('', 'sockopt_enabled', 'تنظیمات Socket فعال')}{Boolean(data.sockopt_enabled) && <>{toggle('sockopt', 'tcpFastOpen', 'TCP Fast Open')}{toggle('sockopt', 'tcpMptcp', 'Multipath TCP')}{toggle('sockopt', 'v6only', 'فقط IPv6')}{number('sockopt', 'tcpKeepAliveIdle', 'TCP Keepalive Idle (ثانیه)', 300, 0, 86400)}{number('sockopt', 'tcpKeepAliveInterval', 'TCP Keepalive Interval (ثانیه)', 30, 0, 86400)}{number('sockopt', 'tcpUserTimeout', 'TCP User Timeout (میلی‌ثانیه)', 0, 0, 86400000)}{text('sockopt', 'tcpCongestion', 'TCP Congestion (مانند bbr)')}{text('sockopt', 'interface', 'رابط شبکه')}<Field label="راهبرد DNS سوکت"><Select value={String(read('sockopt', 'domainStrategy', 'AsIs'))} onChange={e => write('sockopt', 'domainStrategy', e.target.value)}>{['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'UseIPv4v6', 'UseIPv6v4', 'ForceIP', 'ForceIPv4', 'ForceIPv6'].map(v => <option key={v}>{v}</option>)}</Select></Field></>}<p className="field-span-2 field-hint">پشتیبانی عملی Socket به سیستم‌عامل نود و مجوز سرویس وابسته است؛ این تنظیمات فقط سمت سرور اعمال می‌شوند.</p></>}
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
