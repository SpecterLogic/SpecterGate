import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Download,
  ExternalLink,
  Gauge,
  HardDrive,
  Info,
  LifeBuoy,
  Link2,
  RadioTower,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import type { SubscriptionInfo } from "../lib/types";
import { cn, daysLeft, formatBytes, formatDate, formatNumber, protocolLabel, statusLabel } from "../lib/format";
import { Badge, Button, Card, Spinner, Select, Modal } from "../components/UI";
import { Brand } from "../components/Layout";

export default function SubscriptionPage() {
  const { token } = useParams<{ token: string }>();
  const toast = useToast();
  const [copied, setCopied] = useState<string | null>(null);
  const [format, setFormat] = useState("base64");
  const [qr, setQr] = useState<{ name: string; uri: string } | null>(null);
  const [nativeConfig, setNativeConfig] = useState<string | null>(null);

  const info = useQuery({
    queryKey: ["subscription-info", token],
    queryFn: () => api.get<SubscriptionInfo>(`/sub/${token}/info`),
    retry: false,
  });
  const nativeUrl = info.data?.format_urls?.wireguard;
  useEffect(() => {
    setNativeConfig(null);
    if (format !== "wireguard" || !nativeUrl) return;
    const controller = new AbortController();
    fetch(nativeUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error("WireGuard config unavailable");
      setNativeConfig(await response.text());
    }).catch(error => { if (error.name !== "AbortError") toast.error("دریافت کانفیگ WireGuard ممکن نشد."); });
    return () => controller.abort();
  }, [format, nativeUrl]);

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied(null), 1800);
      toast.success("کپی شد.");
    } catch {
      toast.error("کپی ممکن نشد.");
    }
  }

  if (info.isLoading) {
    return (
      <div className="subscription-page">
        <div className="sub-loading">
          <Spinner label="در حال دریافت اشتراک..." />
        </div>
      </div>
    );
  }

  if (info.isError || !info.data) {
    return (
      <div className="subscription-page">
        <div className="sub-topbar">
          <Brand />
        </div>
        <Card className="sub-error-card">
          <span className="sub-error-icon">
            <AlertTriangle size={26} />
          </span>
          <h1>اشتراک پیدا نشد</h1>
          <p>لینک اشتراک نامعتبر است یا توسط مدیر ابطال شده. لطفاً لینک جدید را از پشتیبانی دریافت کنید.</p>
        </Card>
      </div>
    );
  }

  const data = info.data;
  const usagePercent = data.data_limit_bytes ? Math.min(100, (data.used_traffic_bytes / data.data_limit_bytes) * 100) : 0;
  const remaining = data.data_limit_bytes ? Math.max(0, data.data_limit_bytes - data.used_traffic_bytes) : null;
  const remainingDays = daysLeft(data.expire_at);
  const isActive = data.status === "active";
  const formatUrl = data.format_urls?.[format] ?? data.subscription_url;

  return (
    <div className="subscription-page">
      <div className="sub-glow sub-glow-a" />
      <div className="sub-glow sub-glow-b" />

      <header className="sub-topbar">
        <Brand />
        <div className="sub-topbar-actions">
          <Badge tone={isActive ? "success" : "danger"} dot>
            {statusLabel(data.status)}
          </Badge>
          {data.support_url && (
            <a href={data.support_url} target="_blank" rel="noreferrer" className="sub-support">
              <LifeBuoy size={16} />
              پشتیبانی
            </a>
          )}
        </div>
      </header>

      <main className="sub-main">
        {data.announcement && (
          <div className="sub-announcement">
            <ShieldCheck size={17} />
            <span>{data.announcement}</span>
          </div>
        )}

        <section className="sub-hero">
          <div className="sub-hero-copy">
            <span className="sub-eyebrow">اشتراک شما در {data.panel_title}</span>
            <h1>
              سلام، <span>{data.username}</span>
            </h1>
            <p>{data.panel_description || "لینک‌های اتصال و وضعیت حساب شما در این صفحه به‌روز می‌شود."}</p>
            <div className="sub-quick-facts">
              <div>
                <UserRound size={16} />
                <span>وضعیت</span>
                <strong>{statusLabel(data.status)}</strong>
              </div>
              <div>
                <Clock size={16} />
                <span>انقضا</span>
                <strong>{formatDate(data.expire_at)}</strong>
              </div>
              <div>
                <Gauge size={16} />
                <span>باقی‌مانده</span>
                <strong>{remaining === null ? "نامحدود" : formatBytes(remaining)}</strong>
              </div>
            </div>
          </div>

          {isActive ? (
            <div className="sub-qr-card">
              <div className="qr-frame">
                {format === "wireguard" && !nativeConfig ? <Spinner /> : <QRCodeSVG
                  value={format === "wireguard" ? nativeConfig! : formatUrl}
                  size={154}
                  bgColor="#ffffff"
                  fgColor="#0b1120"
                  level="M"
                  marginSize={1}
                />}
              </div>
              <span>برای افزودن سریع، اسکن کنید</span>
              <Select aria-label="فرمت اشتراک" value={format} onChange={e => setFormat(e.target.value)}>{Object.entries({ base64: "V2Ray / Base64", raw: "لینک‌های خام", json: "Xray JSON", clash: "Clash Meta", singbox: "Sing-box", ...(data.format_urls?.wireguard ? { wireguard: "WireGuard IPv4 (.conf)" } : {}), outline: "Outline (Shadowsocks)", dnstt: "DNSTT / SlipNet", noizdns: "NoizDNS / SlipNet" }).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</Select>
              <a href={formatUrl} className="text-link">دریافت فرمت انتخابی</a>
              <button type="button" className="copy-inline" onClick={() => copy(formatUrl, "sub")}>
                {copied === "sub" ? <Check size={14} /> : <Copy size={14} />}
                {copied === "sub" ? "کپی شد" : "کپی لینک اشتراک"}
              </button>
            </div>
          ) : (
            <div className="sub-qr-card sub-qr-disabled">
              <span className="sub-qr-alert">
                <AlertTriangle size={26} />
              </span>
              <strong>این اشتراک فعال نیست</strong>
              <p>پس از تمدید یا فعال‌سازی، کد QR و لینک‌های اتصال در همین صفحه نمایش داده می‌شوند.</p>
            </div>
          )}
        </section>

        {!isActive && (
          <div className="sub-warning">
            <AlertTriangle size={20} />
            <div>
              <strong>
                {data.status === "expired"
                  ? "اشتراک شما منقضی شده است"
                  : data.status === "limited"
                    ? "حجم اشتراک شما به پایان رسیده"
                    : "اشتراک شما غیرفعال شده است"}
              </strong>
              <span>برای تمدید یا فعال‌سازی با پشتیبانی در ارتباط باشید.</span>
            </div>
          </div>
        )}

        <section className="sub-usage-grid">
          <Card className="sub-usage-card">
            <div className="sub-card-head">
              <div>
                <h2>مصرف ترافیک</h2>
                <p>آمار تجمعی از ابتدای اشتراک</p>
              </div>
              <span className="sub-card-icon">
                <HardDrive size={19} />
              </span>
            </div>
            <div className="sub-usage-value">
              <strong>{formatBytes(data.used_traffic_bytes)}</strong>
              <span>از {data.data_limit_bytes ? formatBytes(data.data_limit_bytes) : "نامحدود"}</span>
            </div>
            <div className="sub-progress">
              <span style={{ width: `${usagePercent}%` }} className={cn(usagePercent > 90 && "danger")} />
            </div>
            <div className="sub-usage-foot">
              <span>
                <i className="legend-dot upload" /> آپلود {formatBytes(data.upload_bytes)}
              </span>
              <span>
                <i className="legend-dot download" /> دانلود {formatBytes(data.download_bytes)}
              </span>
              <span>{formatNumber(Math.round(usagePercent))}٪ مصرف</span>
            </div>
          </Card>

          <Card className="sub-expiry-card">
            <div className="sub-card-head">
              <div>
                <h2>زمان باقی‌مانده</h2>
                <p>اعتبار فعلی اشتراک</p>
              </div>
              <span className="sub-card-icon violet">
                <Clock size={19} />
              </span>
            </div>
            <div className="sub-days">
              <strong>{remainingDays === null ? "∞" : formatNumber(Math.max(0, remainingDays))}</strong>
              <span>{remainingDays === null ? "بدون انقضا" : "روز باقی‌مانده"}</span>
            </div>
            <div className="sub-expiry-foot">
              <span>تاریخ انقضا</span>
              <strong>{formatDate(data.expire_at)}</strong>
            </div>
          </Card>
        </section>

        <section className="sub-links-section">
          <div className="sub-section-head">
            <div>
              <h2>لینک‌های اتصال</h2>
              <p>{formatNumber(data.links.length)} مسیر فعال برای این اشتراک</p>
            </div>
            {isActive && (
              <div className="sub-downloads">
                <a className="btn btn-outline btn-sm" href={data.clash_url}>
                  <Download size={15} />
                  <span>Clash</span>
                </a>
                <a className="btn btn-primary btn-sm" href={data.subscription_url}>
                  <Download size={15} />
                  <span>اشتراک Xray</span>
                </a>
              </div>
            )}
          </div>

          {data.links.length === 0 ? (
            <Card className="sub-empty">
              <Link2 size={24} />
              <h3>هنوز مسیری فعال نیست</h3>
              <p>مدیر پنل باید حداقل یک اینباند فعال برای اشتراک شما پیکربندی کند.</p>
            </Card>
          ) : (
            <div className="sub-link-list">
              {data.links.map((link, index) => (
                <Card className="sub-link-card" key={`${link.remark}-${index}`}>
                  <div className="sub-link-main">
                    <span className={cn("protocol-mark", `protocol-${link.protocol}`)}>
                      {link.protocol === "shadowsocks" ? "SS" : link.protocol.toUpperCase()}
                    </span>
                    <div>
                      <strong>{link.remark}</strong>
                      <code dir="ltr">{link.uri.length > 92 ? `${link.uri.slice(0, 92)}...` : link.uri}</code>
                    </div>
                  </div>
                  <div className="sub-link-actions">
                    <Badge tone="neutral">{protocolLabel(link.protocol)}</Badge>
                    <Button size="sm" variant="ghost" onClick={() => setQr({ name: link.remark, uri: link.uri })}>QR</Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={copied === `link-${index}` ? <Check size={15} /> : <Copy size={15} />}
                      onClick={() => copy(link.uri, `link-${index}`)}
                    >
                      {copied === `link-${index}` ? "کپی شد" : "کپی"}
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </section>

        {(data.dns_links?.length ?? 0) > 0 && (
          <section className="sub-links-section">
            <div className="sub-section-head">
              <div>
                <h2>تونل‌های DNS</h2>
                <p>لینک‌های SlipNet برای DNSTT و NoizDNS؛ مخصوص شبکه‌هایی که DNS آزاد دارند.</p>
              </div>
              <Badge tone="violet">
                <RadioTower size={13} /> {formatNumber(data.dns_links.length)} مسیر
              </Badge>
            </div>
            <div className="sub-link-list">
              {data.dns_links.map((link, index) => (
                <Card className="sub-link-card" key={`${link.protocol}-${link.id}-${index}`}>
                  <div className="sub-link-main">
                    <span className={cn("protocol-mark", "protocol-dns")}>
                      <RadioTower size={17} />
                    </span>
                    <div>
                      <strong>{link.remark}</strong>
                      <code dir="ltr">{link.uri.slice(0, 88)}…</code>
                    </div>
                  </div>
                  <div className="sub-link-actions">
                    <Badge tone={link.protocol === "noizdns" ? "violet" : "info"}>
                      {link.protocol === "noizdns" ? "NoizDNS" : "DNSTT"}
                    </Badge>
                    <Button size="sm" variant="ghost" onClick={() => setQr({ name: link.remark, uri: link.uri })}>QR</Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={copied === `dns-${index}` ? <Check size={15} /> : <Copy size={15} />}
                      onClick={() => copy(link.uri, `dns-${index}`)}
                    >
                      {copied === `dns-${index}` ? "کپی شد" : "کپی"}
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
            <div className="sub-dns-note">
              <Info size={15} />
              <span>
                این لینک‌ها را در SlipNet وارد کنید. برای NoizDNS همان سرور DNSTT استفاده می‌شود و فقط حالت کلاینت
                تغییر می‌کند.
              </span>
            </div>
          </section>
        )}

        <section className="sub-help">
          <div>
            <ShieldCheck size={20} />
            <div>
              <strong>چطور اشتراک را اضافه کنم؟</strong>
              <span>لینک اشتراک را در برنامهٔ V2rayNG، Streisand، Hiddify یا Clash وارد کنید.</span>
            </div>
          </div>
          {data.support_url && (
            <a href={data.support_url} target="_blank" rel="noreferrer" className="text-link">
              دریافت راهنمایی <ExternalLink size={13} />
            </a>
          )}
        </section>
      </main>

      <Modal open={!!qr} onClose={() => setQr(null)} title={qr?.name ?? "کد اتصال"}><div style={{ padding: 16, background: "white", textAlign: "center", borderRadius: 12 }}>{qr && <QRCodeSVG value={qr.uri} size={240} marginSize={2} />}</div></Modal>
      <footer className="sub-footer">
        <span>{data.panel_title} · SpecterGate Panel</span>
        <span>لینک اشتراک خود را در اختیار دیگران قرار ندهید.</span>
      </footer>
    </div>
  );
}
