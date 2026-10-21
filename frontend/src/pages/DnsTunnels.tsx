import { t, tt } from "../lib/i18n";import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Globe2,
  Info,
  KeyRound,
  Layers3,
  Network,
  Pencil,
  Plus,
  Power,
  RadioTower,
  Server,
  Terminal,
  Trash2 } from
"lucide-react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { useAuth } from "../lib/auth";
import type { DnsMultiplexer, DnsTunnel, DnsTunnelSetup, OperationResult } from "../lib/types";
import { cn, formatNumber } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  SectionHeader,
  Spinner,
  StatusBadge,
  Textarea,
  Toggle } from
"../components/UI";

function GatewayStatus({ tunnel }: {tunnel: DnsTunnel;}) {
  const { admin } = useAuth();
  const runtime = useQuery({ queryKey: ["gateway-runtime", tunnel.id], queryFn: () => api.get<{listening: boolean;error: string | null;server_running: boolean;dns_listener: boolean;dns_error: string | null;}>(`/api/dns-tunnels/${tunnel.id}/runtime`), enabled: tunnel.managed_gateway && !!admin?.permissions.includes("dns.manage"), refetchInterval: 5000, retry: false });
  if (!tunnel.managed_gateway) return <small>{t("دروازه خارجی")}</small>;
  return <div><Badge tone={runtime.data?.listening ? "success" : "warning"}>{runtime.data?.listening ? t("دروازه محلی آماده") : t("دروازه محلی در انتظار اجرا")}</Badge><Badge tone={runtime.data?.server_running && runtime.data?.dns_listener ? "success" : "warning"}>{runtime.data?.server_running && runtime.data?.dns_listener ? t("سرور DNSTT و DNS فعال") : t("سرور DNSTT در انتظار اجرا")}</Badge>{(runtime.data?.error || runtime.data?.dns_error) && <p role="alert" className="field-error">{runtime.data.error || runtime.data.dns_error}</p>}</div>;
}

interface TunnelForm {
  managedGateway: boolean;
  name: string;
  domain: string;
  upstreamPort: string;
  targetHost: string;
  targetPort: string;
  mtu: string;
  resolver: string;
  noizdns: boolean;
  isActive: boolean;
  note: string;
}

const EMPTY_FORM: TunnelForm = {
  managedGateway: true,
  name: "",
  domain: "",
  upstreamPort: "5310",
  targetHost: "127.0.0.1",
  targetPort: "1080",
  mtu: "1232",
  resolver: "8.8.8.8:53:0",
  noizdns: true,
  isActive: true,
  note: ""
};

function tunnelToForm(tunnel: DnsTunnel): TunnelForm {
  return {
    managedGateway: tunnel.managed_gateway,
    name: tunnel.name,
    domain: tunnel.domain,
    upstreamPort: String(tunnel.upstream_port),
    targetHost: tunnel.target_host,
    targetPort: String(tunnel.target_port),
    mtu: String(tunnel.mtu),
    resolver: tunnel.resolver,
    noizdns: tunnel.noizdns_enabled,
    isActive: tunnel.is_active,
    note: tunnel.note ?? ""
  };
}

export default function DnsTunnelsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DnsTunnel | null>(null);
  const [form, setForm] = useState<TunnelForm>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DnsTunnel | null>(null);
  const [setupTarget, setSetupTarget] = useState<DnsTunnel | null>(null);
  const [multiplexerOpen, setMultiplexerOpen] = useState(false);
  const [copied, setCopied] = useState("");

  const tunnels = useQuery({
    queryKey: ["dns-tunnels"],
    queryFn: () => api.get<DnsTunnel[]>("/api/dns-tunnels")
  });
  const setup = useQuery({
    queryKey: ["dns-tunnel-setup", setupTarget?.id],
    queryFn: () => api.get<DnsTunnelSetup>(`/api/dns-tunnels/${setupTarget?.id}/setup`),
    enabled: setupTarget !== null
  });
  const multiplexer = useQuery({
    queryKey: ["dns-multiplexer"],
    queryFn: () => api.get<DnsMultiplexer>("/api/dns-tunnels/multiplexer"),
    enabled: multiplexerOpen
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["dns-tunnels"] });
    queryClient.invalidateQueries({ queryKey: ["dns-multiplexer"] });
  }

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => {
      if (editing) return api.patch<DnsTunnel>(`/api/dns-tunnels/${editing.id}`, payload);
      return api.post<DnsTunnel>("/api/dns-tunnels", payload);
    },
    onSuccess: () => {
      toast.success(editing ? t("تونل DNS ذخیره شد.") : t("تونل DNS ساخته شد."));
      setModalOpen(false);
      setEditing(null);
      setFormError("");
      invalidate();
    },
    onError: (error: Error) => setFormError(error.message)
  });

  const toggleMutation = useMutation({
    mutationFn: (tunnel: DnsTunnel) =>
    api.patch<DnsTunnel>(`/api/dns-tunnels/${tunnel.id}`, { is_active: !tunnel.is_active }),
    onSuccess: () => {
      toast.success(t("وضعیت تونل تغییر کرد."));
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const deleteMutation = useMutation({
    mutationFn: (tunnel: DnsTunnel) => api.delete<OperationResult>(`/api/dns-tunnels/${tunnel.id}`),
    onSuccess: () => {
      toast.success(t("تونل DNS حذف شد."));
      setDeleteTarget(null);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message)
  });

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied(""), 1600);
      toast.success(t("کپی شد."));
    } catch {
      toast.error(t("کپی ممکن نشد."));
    }
  }

  function openCreate() {
    setEditing(null);
    const nextPort = 5310 + (tunnels.data?.length ?? 0);
    setForm({ ...EMPTY_FORM, upstreamPort: String(nextPort) });
    setFormError("");
    setModalOpen(true);
  }

  function openEdit(tunnel: DnsTunnel) {
    setEditing(tunnel);
    setForm(tunnelToForm(tunnel));
    setFormError("");
    setModalOpen(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (!form.name.trim() || !form.domain.trim()) {
      setFormError(t("نام و دامنهٔ تونل الزامی است."));
      return;
    }
    saveMutation.mutate({
      name: form.name.trim(),
      domain: form.domain.trim().toLowerCase(),
      upstream_port: Number(form.upstreamPort),
      target_host: form.targetHost.trim(),
      managed_gateway: form.managedGateway,
      target_port: Number(form.targetPort),
      mtu: Number(form.mtu),
      resolver: form.resolver.trim(),
      noizdns_enabled: form.noizdns,
      is_active: form.isActive,
      note: form.note.trim() || null
    });
  }

  const activeCount = tunnels.data?.filter((tunnel) => tunnel.is_active).length ?? 0;

  return (
    <div className="dns-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">DNS Tunneling</p>
          <h2>{t("تونل‌های DNSTT و NoizDNS")}</h2>
          <p className="page-subtitle">{"" + t("کانفیگ سرور، کلیدها، رکوردهای DNS و لینک‌های SlipNet را بسازید؛ با پشتیبانی از چند تونل روی یک پورت.") + " "}

          </p>
        </div>
        <div className="page-actions">
          <Button variant="outline" icon={<Layers3 size={16} />} onClick={() => setMultiplexerOpen(true)}>
            DNS Multiplexer
          </Button>
          <Button icon={<Plus size={17} />} onClick={openCreate}>{"" + t("تونل جدید") + " "}

          </Button>
        </div>
      </div>

      <Card className="dns-banner">
        <div className="dns-banner-main">
          <span className="agent-icon">
            <RadioTower size={20} />
          </span>
          <div>
            <strong>{t("DNS TT، NoizDNS و DNS Multiplexing")}</strong>
            <span>{"" + t("NoizDNS از همان سرور DNSTT استفاده می‌کند و فقط رفتار کلاینت تفاوت دارد. برای چند تونل، پورت ۵۳ UDP را به DNS router بدهید تا بر اساس دامنه به هر تونل مسیر دهد.") + " "}


            </span>
          </div>
        </div>
        <Badge tone={activeCount ? "success" : "warning"} dot>
          {formatNumber(activeCount)}{" " + t("تونل فعال") + " "}
        </Badge>
      </Card>

      {tunnels.isLoading ?
      <Card>
          <Spinner />
        </Card> :
      tunnels.isError ?
      <Card>
          <EmptyState
          icon={<RadioTower size={24} />}
          title={t("دریافت تونل‌ها ناموفق بود")}
          description={(tunnels.error as Error).message}
          action={<Button onClick={() => tunnels.refetch()}>{t("تلاش دوباره")}</Button>} />

        </Card> :
      (tunnels.data?.length ?? 0) === 0 ?
      <Card>
          <EmptyState
          icon={<RadioTower size={26} />}
          title={t("هنوز تونل DNSی ندارید")}
          description={t("یک دامنهٔ زیرمجموعه (مثلاً t.example.com) و رکورد NS بسازید تا ترافیک از دل DNS عبور کند.")}
          action={
          <Button icon={<Plus size={16} />} onClick={openCreate}>{"" + t("ساخت اولین تونل") + " "}

          </Button>
          } />

        </Card> :

      <div className="dns-grid">
          {tunnels.data?.map((tunnel) =>
        <Card key={tunnel.id} className={cn("dns-card", !tunnel.is_active && "is-inactive")}>
              <div className="dns-card-head">
                <span className="protocol-mark protocol-dns">
                  <RadioTower size={19} />
                </span>
                <div className="dns-title">
                  <strong>{tunnel.name}</strong>
                  <code dir="ltr">{tunnel.domain}</code>
                </div>
                <StatusBadge status={tunnel.is_active ? "active" : "disabled"} />
                <GatewayStatus tunnel={tunnel} />
              </div>

              <div className="inbound-tags">
                <Badge tone="info">DNSTT</Badge>
                {tunnel.noizdns_enabled && <Badge tone="violet">NoizDNS</Badge>}
                <Badge tone="neutral">MTU {tunnel.mtu}</Badge>
              </div>

              <div className="dns-specs">
                <div>
                  <span>
                    <Network size={13} />{" " + t("پورت محلی") + " "}
              </span>
                  <strong dir="ltr">{tunnel.upstream_port}/udp</strong>
                </div>
                <div>
                  <span>
                    <Server size={13} />{" " + t("مقصد") + " "}
              </span>
                  <strong dir="ltr">
                    {tunnel.target_host}:{tunnel.target_port}
                  </strong>
                </div>
                <div>
                  <span>
                    <Globe2 size={13} /> Resolver
                  </span>
                  <strong dir="ltr">{tunnel.resolver}</strong>
                </div>
                <div>
                  <span>
                    <KeyRound size={13} />{" " + t("کلید عمومی") + " "}
              </span>
                  <strong dir="ltr">{tunnel.public_key.slice(0, 16)}…</strong>
                </div>
              </div>

              <div className="dns-card-actions">
                <Button variant="ghost" size="sm" icon={<Terminal size={15} />} onClick={() => setSetupTarget(tunnel)}>{"" + t("راه‌اندازی") + " "}

            </Button>
                <Button variant="ghost" size="sm" icon={<Pencil size={15} />} onClick={() => openEdit(tunnel)}>{"" + t("ویرایش") + " "}

            </Button>
                <Button
              variant="ghost"
              size="sm"
              icon={<Power size={15} />}
              onClick={() => toggleMutation.mutate(tunnel)}>

                  {tunnel.is_active ? t("غیرفعال") : t("فعال")}
                </Button>
                <button type="button" className="icon-btn danger-hover" title={t("حذف")} onClick={() => setDeleteTarget(tunnel)}>
                  <Trash2 size={16} />
                </button>
              </div>
            </Card>
        )}
        </div>
      }

      <Card className="dns-info-card">
        <SectionHeader title={t("چطور کار می‌کند؟")} subtitle={t("سه گام راه‌اندازی")} />
        <div className="dns-steps">
          <div>
            <span>{t("۱")}</span>
            <strong>{t("DNS را delegat کنید")}</strong>
            <p>{t("رکورد A برای nameserver و رکورد NS برای دامنهٔ تونل ثبت کنید.")}</p>
          </div>
          <div>
            <span>{t("۲")}</span>
            <strong>{t("سرور DNS را اجرا کنید")}</strong>
            <p>{t("dnstt-server را روی پورت محلی بالا بیاورید و به SOCKS محلی وصل کنید.")}</p>
          </div>
          <div>
            <span>{t("۳")}</span>
            <strong>{t("لینک SlipNet را بدهید")}</strong>
            <p>{t("لینک DNSTT یا NoizDNS در صفحهٔ اشتراک کاربر ساخته می‌شود.")}</p>
          </div>
        </div>
      </Card>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? tt("ویرایش {0}", [editing.name]) : t("ساخت تونل DNS")}
        description={t("دامنه باید یک زیردامنهٔ قابل delegate باشد؛ کلیدها هنگام ساخت خودکار تولید می‌شوند.")}
        wide
        footer={
        <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>{"" + t("انصراف") + " "}

          </Button>
            <Button type="submit" form="dns-form" loading={saveMutation.isPending}>
              {editing ? t("ذخیره تونل") : t("ساخت تونل")}
            </Button>
          </>
        }>

        <form id="dns-form" onSubmit={submit} className="form-grid">
          <Field label={t("نام نمایشی")}>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="DNSTT Germany"
              required />

          </Field>
          <Field label={t("دامنهٔ تونل")} hint={t("مثلاً t.example.com — نباید دامنهٔ اصلی سایت باشد")}>
            <Input
              value={form.domain}
              onChange={(event) => setForm({ ...form, domain: event.target.value })}
              placeholder="t.example.com"
              dir="ltr"
              required />

          </Field>
          <Field label={t("پورت محلی DNSTT")} hint={t("dnstt-server روی این پورت UDP گوش می‌دهد")}>
            <Input
              type="number"
              min="1"
              max="65535"
              value={form.upstreamPort}
              onChange={(event) => setForm({ ...form, upstreamPort: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label="MTU" hint={t("پیش‌فرض ۱۲۳۲؛ برای resolverهای قدیمی‌تر کمتر کنید")}>
            <Input
              type="number"
              min="512"
              max="1400"
              value={form.mtu}
              onChange={(event) => setForm({ ...form, mtu: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("هاست مقصد")}>
            <Input
              value={form.targetHost}
              onChange={(event) => setForm({ ...form, targetHost: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("پورت مقصد")} hint={t("معمولاً SOCKS5 محلی")}>
            <Input
              type="number"
              min="1"
              max="65535"
              value={form.targetPort}
              onChange={(event) => setForm({ ...form, targetPort: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("Resolver کلاینت")} hint={t("قالب host:port:auth برای SlipNet")} className="field-span-2">
            <Input
              value={form.resolver}
              onChange={(event) => setForm({ ...form, resolver: event.target.value })}
              placeholder="8.8.8.8:53:0"
              dir="ltr" />

          </Field>
          <Field label={t("یادداشت")} className="field-span-2">
            <Textarea
              rows={2}
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
              placeholder={t("مشخصات سرور یا محدودیت‌ها...")} />

          </Field>
          <div className="field-span-2 dns-toggles">
            <Toggle checked={form.managedGateway} onChange={(value) => setForm({ ...form, managedGateway: value })} label={t("دروازه SOCKS با کنترل دسترسی و محاسبه مصرف توسط پنل")} />
            <Toggle
              checked={form.noizdns}
              onChange={(value) => setForm({ ...form, noizdns: value })}
              label={t("ساخت لینک NoizDNS")} />

            <Toggle
              checked={form.isActive}
              onChange={(value) => setForm({ ...form, isActive: value })}
              label={form.isActive ? t("تونل فعال") : t("تونل غیرفعال")} />

          </div>
          <p className="field-hint field-span-2">{t("در حالت مدیریت‌شده، هر تونل یک پورت SOCKS محلی اختصاصی دارد. در حالت سرویس خارجی، اعمال مجوزها و محاسبه مصرف اتصال به عهده همان سرویس است.")}</p>
          {formError && <div className="form-error field-span-2">{formError}</div>}
        </form>
      </Modal>

      <Modal
        open={setupTarget !== null}
        onClose={() => setSetupTarget(null)}
        title={tt("راه‌اندازی · {0}", [setupTarget?.domain ?? ""])}
        description={t("این مقادیر را روی سرور DNS اجرا کنید. کلید خصوصی را در جای امن نگه دارید.")}
        wide
        footer={
        <Button variant="ghost" onClick={() => setSetupTarget(null)}>{"" + t("بستن") + " "}

        </Button>
        }>

        {setup.isLoading ?
        <Spinner /> :
        setup.isError ?
        <div className="form-error">{(setup.error as Error).message}</div> :
        setup.data ?
        <div className="dns-setup">
            <div className="setup-block">
              <div className="setup-block-head">
                <span>
                  <Globe2 size={15} />{" " + t("رکوردهای DNS") + " "}
              </span>
                <button type="button" className="icon-btn" onClick={() => copy(setup.data!.dns_records.join("\n"), "records")}>
                  {copied === "records" ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </div>
              <pre className="code-block" dir="ltr">
                {setup.data.dns_records.join("\n")}
              </pre>
            </div>

            <div className="setup-block">
              <div className="setup-block-head">
                <span>
                  <Terminal size={15} />{" " + t("اجرای سرور") + " "}
              </span>
                <button type="button" className="icon-btn" onClick={() => copy(setup.data!.command, "command")}>
                  {copied === "command" ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </div>
              <pre className="code-block" dir="ltr">
                {setup.data.command}
              </pre>
            </div>

            <div className="setup-block">
              <div className="setup-block-head">
                <span>
                  <Server size={15} />{" " + t("واحد systemd") + " "}
              </span>
                <button type="button" className="icon-btn" onClick={() => copy(setup.data!.systemd_unit, "unit")}>
                  {copied === "unit" ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </div>
              <pre className="code-block" dir="ltr">
                {setup.data.systemd_unit}
              </pre>
            </div>

            <div className="setup-notes">
              {setup.data.notes.map((note) =>
            <p key={note}>
                  <Info size={14} /> {note}
                </p>
            )}
            </div>
            <div className="key-result">
              <div>
                <span>Public key</span>
                <code dir="ltr">{setupTarget?.public_key}</code>
              </div>
              <div>
                <span>Key path</span>
                <code dir="ltr">{setup.data.key_path}</code>
              </div>
            </div>
          </div> :
        null}
      </Modal>

      <Modal
        open={multiplexerOpen}
        onClose={() => setMultiplexerOpen(false)}
        title="DNS Multiplexer"
        description={t("یک شنوندهٔ UDP/53 که کوئری‌ها را بر اساس دامنه به تونل‌های محلی مسیر می‌دهد.")}
        wide
        footer={
        <Button variant="ghost" onClick={() => setMultiplexerOpen(false)}>{"" + t("بستن") + " "}

        </Button>
        }>

        {multiplexer.isLoading ?
        <Spinner /> :
        multiplexer.data ?
        <div className="dns-setup">
            <div className="setup-block">
              <div className="setup-block-head">
                <span>
                  <Network size={15} />{" " + t("دستور اجرا") + " "}
              </span>
                <button type="button" className="icon-btn" onClick={() => copy(multiplexer.data!.command, "router-command")}>
                  {copied === "router-command" ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </div>
              <pre className="code-block" dir="ltr">
                {multiplexer.data.command}
              </pre>
            </div>
            <div className="setup-block">
              <div className="setup-block-head">
                <span>
                  <Layers3 size={15} /> config.json
                </span>
                <button
                type="button"
                className="icon-btn"
                onClick={() => copy(JSON.stringify(multiplexer.data!.config, null, 2), "router-config")}>

                  {copied === "router-config" ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </div>
              <pre className="code-block" dir="ltr">
                {JSON.stringify(multiplexer.data.config, null, 2)}
              </pre>
            </div>
            <div className="setup-notes">
              <p>
                <Info size={14} />{" " + t("فایل را در") + " "}<code dir="ltr">/etc/spectergate/dns-router.json</code>{" " + t("ذخیره کنید و سرویس") + ""}{" "}
                <code dir="ltr">spectergate-dns-router.service</code>{" " + t("را اجرا کنید.") + " "}
            </p>
              <p>
                <Info size={14} />{" " + t("در حالت تک‌تونل می‌توانید dnstt-server را مستقیم روی UDP/53 اجرا کنید.") + " "}
            </p>
            </div>
          </div> :

        <div className="form-error">{t("Multiplexer در دسترس نیست.")}</div>
        }
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
        title={t("حذف تونل DNS")}
        message={tt("تونل «{0}» حذف می‌شود و لینک‌های SlipNet آن دیگر در اشتراک ساخته نمی‌شوند.", [deleteTarget?.name ?? ""])}
        confirmLabel={t("حذف قطعی")}
        loading={deleteMutation.isPending} />

    </div>);

}
