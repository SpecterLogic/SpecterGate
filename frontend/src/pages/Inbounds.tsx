import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Boxes,
  Calendar,
  CheckSquare,
  FileJson,
  Globe2,
  KeyRound,
  Network,
  Pencil,
  Play,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Server,
  Shield,
  Square,
  Trash2,
  Wand2,
} from "lucide-react";
import InboundAdvanced, { serializeAdvanced } from "../components/InboundAdvanced";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import type { Inbound, Network as NetworkType, Node, Protocol, Security, XrayApplyResult, XrayStatus } from "../lib/types";
import { cn, formatBytes, formatNumber, protocolLabel } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
  StatusBadge,
  Toggle,
} from "../components/UI";

interface InboundForm {
  advanced: string;
  tag: string;
  remark: string;
  protocol: Protocol;
  nodeId: string;
  port: string;
  listen: string;
  network: NetworkType;
  security: Security;
  sni: string;
  host: string;
  path: string;
  serviceName: string;
  flow: string;
  fingerprint: string;
  alpn: string;
  realityDest: string;
  realityPublicKey: string;
  realityPrivateKey: string;
  realityShortId: string;
  tlsCertPath: string;
  tlsKeyPath: string;
  isActive: boolean;
  dataLimitGb: string;
  expireAt: string;
  resetIntervalDays: string;
}

const EMPTY_FORM: InboundForm = {
  advanced: "{}",
  tag: "",
  remark: "",
  protocol: "vless",
  nodeId: "",
  port: "8443",
  listen: "0.0.0.0",
  network: "tcp",
  security: "reality",
  sni: "www.cloudflare.com",
  host: "",
  path: "/",
  serviceName: "",
  flow: "xtls-rprx-vision",
  fingerprint: "chrome",
  alpn: "h2,http/1.1",
  realityDest: "www.cloudflare.com:443",
  realityPublicKey: "",
  realityPrivateKey: "",
  realityShortId: "",
  tlsCertPath: "",
  tlsKeyPath: "",
  isActive: true,
  dataLimitGb: "",
  expireAt: "",
  resetIntervalDays: "",
};

function inboundToForm(inbound: Inbound): InboundForm {
  return {
    advanced: JSON.stringify({ ...JSON.parse(inbound.extra_json || "{}"), sockopt_enabled: !!JSON.parse(inbound.extra_json || "{}").sockopt }),
    tag: inbound.tag,
    remark: inbound.remark,
    protocol: inbound.protocol,
    nodeId: inbound.node_id ? String(inbound.node_id) : "",
    port: String(inbound.port),
    listen: inbound.listen,
    network: inbound.network,
    security: inbound.security,
    sni: inbound.sni ?? "",
    host: inbound.host ?? "",
    path: inbound.path ?? "/",
    serviceName: inbound.service_name ?? "",
    flow: inbound.flow ?? "",
    fingerprint: inbound.fingerprint ?? "chrome",
    alpn: inbound.alpn ?? "",
    realityDest: inbound.reality_dest ?? "",
    realityPublicKey: inbound.reality_public_key ?? "",
    realityPrivateKey: inbound.reality_private_key ?? "",
    realityShortId: inbound.reality_short_id ?? "",
    tlsCertPath: inbound.tls_cert_path ?? "",
    tlsKeyPath: inbound.tls_key_path ?? "",
    isActive: inbound.is_active,
    dataLimitGb: inbound.data_limit_bytes ? String(Math.round((inbound.data_limit_bytes / (1024 * 1024 * 1024)) * 10) / 10) : "",
    expireAt: inbound.expire_at ? inbound.expire_at.slice(0, 10) : "",
    resetIntervalDays: inbound.reset_interval_days ? String(inbound.reset_interval_days) : "",
  };
}

function toPayload(form: InboundForm): Record<string, unknown> {
  return {
    extra_json: serializeAdvanced(form.advanced),
    tag: form.tag.trim(),
    remark: form.remark.trim(),
    protocol: form.protocol,
    node_id: form.nodeId ? Number(form.nodeId) : null,
    port: Number(form.port),
    listen: form.listen || "0.0.0.0",
    network: form.network,
    security: form.security,
    sni: form.sni.trim() || null,
    host: form.host.trim() || null,
    path: form.path.trim() || null,
    service_name: form.serviceName.trim() || null,
    flow: form.flow.trim() || null,
    fingerprint: form.fingerprint.trim() || null,
    alpn: form.alpn.trim() || null,
    reality_dest: form.realityDest.trim() || null,
    reality_public_key: form.realityPublicKey.trim() || null,
    reality_private_key: form.realityPrivateKey.trim() || null,
    reality_short_id: form.realityShortId.trim() || null,
    tls_cert_path: form.tlsCertPath.trim() || null,
    tls_key_path: form.tlsKeyPath.trim() || null,
    is_active: form.isActive,
    data_limit_bytes: form.dataLimitGb.trim() ? Math.round(parseFloat(form.dataLimitGb) * 1024 * 1024 * 1024) : null,
    expire_at: form.expireAt ? new Date(form.expireAt).toISOString() : null,
    reset_interval_days: form.resetIntervalDays.trim() ? parseInt(form.resetIntervalDays) : null,
  };
}

const PROTOCOLS: { value: Protocol; label: string }[] = [
  { value: "vless", label: "VLESS" },
  { value: "vmess", label: "VMess" },
  { value: "trojan", label: "Trojan" },
  { value: "shadowsocks", label: "Shadowsocks" },
];

export default function InboundsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Inbound | null>(null);
  const [form, setForm] = useState<InboundForm>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Inbound | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [applyResult, setApplyResult] = useState<XrayApplyResult | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const inbounds = useQuery({
    queryKey: ["inbounds"],
    queryFn: () => api.get<Inbound[]>("/api/inbounds"),
  });
  const nodes = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api.get<Node[]>("/api/nodes"),
  });
  const xray = useQuery({
    queryKey: ["xray-status"],
    queryFn: () => api.get<XrayStatus>("/api/xray/status"),
    refetchInterval: 30_000,
  });
  const preview = useQuery({
    queryKey: ["xray-config"],
    queryFn: () => api.get<{ config: unknown; warnings: string[]; inbound_count: number; client_count: number }>("/api/xray/config"),
    enabled: previewOpen,
  });

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => {
      if (editing) return api.patch<Inbound>(`/api/inbounds/${editing.id}`, payload);
      return api.post<Inbound>("/api/inbounds", payload);
    },
    onSuccess: (inbound) => {
      toast.success(editing ? "اینباند ذخیره شد." : `اینباند ${inbound.tag} ساخته شد.`);
      setModalOpen(false);
      setEditing(null);
      setFormError("");
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => setFormError(error.message),
  });

  const toggleMutation = useMutation({
    mutationFn: (inbound: Inbound) => api.patch<Inbound>(`/api/inbounds/${inbound.id}`, { is_active: !inbound.is_active }),
    onSuccess: () => {
      toast.success("وضعیت اینباند تغییر کرد.");
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const resetTrafficMutation = useMutation({
    mutationFn: (inboundId: number) => api.post(`/api/inbounds/${inboundId}/reset-traffic`),
    onSuccess: () => {
      toast.success("ترافیک اینباند با موفقیت ریست شد.");
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const bulkStatusMutation = useMutation({
    mutationFn: (active: boolean) => api.post("/api/inbounds/bulk/status", { inbound_ids: selectedIds, is_active: active }),
    onSuccess: () => {
      toast.success("وضعیت اینباندهای انتخابی به‌روزرسانی شد.");
      setSelectedIds([]);
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const bulkResetMutation = useMutation({
    mutationFn: () => api.post("/api/inbounds/bulk/reset-traffic", { inbound_ids: selectedIds }),
    onSuccess: () => {
      toast.success("ترافیک اینباندهای انتخابی ریست شد.");
      setSelectedIds([]);
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: () => api.post("/api/inbounds/bulk/delete", { inbound_ids: selectedIds }),
    onSuccess: () => {
      toast.success("اینباندهای انتخابی حذف شدند.");
      setSelectedIds([]);
      setBulkDeleteOpen(false);
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (inbound: Inbound) => api.delete(`/api/inbounds/${inbound.id}`),
    onSuccess: () => {
      toast.success("اینباند حذف شد.");
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["inbounds"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const keysMutation = useMutation({
    mutationFn: () => api.post<{ private_key: string; public_key: string; short_id: string }>("/api/xray/keys"),
    onSuccess: (keys) => {
      setForm((current) => ({
        ...current,
        realityPrivateKey: keys.private_key,
        realityPublicKey: keys.public_key,
        realityShortId: keys.short_id,
      }));
      toast.success("کلیدهای Reality تولید شد.");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const applyMutation = useMutation({
    mutationFn: () => api.post<XrayApplyResult>("/api/xray/apply?restart=true"),
    onSuccess: (result) => {
      setApplyResult(result);
      queryClient.invalidateQueries({ queryKey: ["xray-status"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const localNode = useMemo(() => nodes.data?.find((node) => node.is_local), [nodes.data]);
  const activeCount = inbounds.data?.filter((inbound) => inbound.is_active).length ?? 0;

  function toggleSelect(id: number) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]));
  }

  function selectAll() {
    if (!inbounds.data) return;
    if (selectedIds.length === inbounds.data.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(inbounds.data.map((i) => i.id));
    }
  }

  function openCreate() {
    setEditing(null);
    setForm({ ...EMPTY_FORM, nodeId: localNode ? String(localNode.id) : "" });
    setFormError("");
    setModalOpen(true);
  }

  function openEdit(inbound: Inbound) {
    setEditing(inbound);
    setForm(inboundToForm(inbound));
    setFormError("");
    setModalOpen(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (!form.tag.trim() || !form.remark.trim()) {
      setFormError("تگ و نام نمایشی اینباند الزامی است.");
      return;
    }
    const port = Number(form.port);
    if (!port || port < 1 || port > 65535) {
      setFormError("پورت باید بین ۱ تا ۶۵۵۳۵ باشد.");
      return;
    }
    try {
      saveMutation.mutate(toPayload(form));
    } catch {
      setFormError("تنظیمات پیشرفته اینباند نامعتبر است.");
    }
  }

  function changeProtocol(protocol: Protocol) {
    setForm((current) => ({
      ...current,
      protocol,
      security: protocol !== "vless" && current.security === "reality" ? "none" : current.security,
      flow: protocol === "vless" && current.network === "tcp" && current.security !== "none" ? "xtls-rprx-vision" : "",
    }));
  }

  function changeNetwork(network: NetworkType) {
    setForm((current) => ({
      ...current,
      network,
      security: current.security === "reality" && !["tcp", "grpc", "xhttp"].includes(network) ? "none" : current.security,
      advanced: JSON.stringify({
        ...JSON.parse(current.advanced),
        ...(network === "kcp" ? { proxy_protocol: false } : {}),
        ...(network !== "tcp" ? { tcp_http_obfuscation: false } : {}),
      }),
      flow: current.protocol === "vless" && network === "tcp" && current.security === "reality" ? "xtls-rprx-vision" : "",
    }));
  }

  return (
    <div className="inbounds-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">قابلیت‌های ارتباطی</p>
          <h2>اینباندها و پروتکل‌ها</h2>
          <p className="page-subtitle">
            {formatNumber(activeCount)} مسیر فعال از {formatNumber(inbounds.data?.length ?? 0)} اینباند پیکربندی‌شده.
          </p>
        </div>
        <div className="page-actions">
          <Button variant="outline" icon={<FileJson size={16} />} onClick={() => setPreviewOpen(true)}>
            پیش‌نمایش کانفیگ
          </Button>
          <Button icon={<Plus size={17} />} onClick={openCreate}>
            اینباند جدید
          </Button>
        </div>
      </div>

      <Card className={cn("xray-banner", xray.data?.running ? "is-running" : "is-stopped")}>
        <div className="xray-banner-status">
          <span className="xray-orb">
            <Play size={18} />
          </span>
          <div>
            <strong>{xray.data?.running ? "سرویس Xray در حال اجرا است" : "سرویس Xray متوقف است"}</strong>
            <span>{xray.data?.message ?? "در حال دریافت وضعیت..."}</span>
          </div>
        </div>
        <div className="xray-banner-actions">
          <Button variant="ghost" size="sm" onClick={() => xray.refetch()} loading={xray.isFetching} icon={<RefreshCw size={15} />}>
            وضعیت
          </Button>
          <Button
            size="sm"
            variant={xray.data?.running ? "outline" : "primary"}
            loading={applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
            icon={<Wand2 size={15} />}
          >
            اعمال کانفیگ
          </Button>
        </div>
      </Card>

      {/* Bulk actions bar */}
      {selectedIds.length > 0 && (
        <div className="card bulk-actions-bar" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", marginBottom: "16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <Badge tone="violet">{formatNumber(selectedIds.length)} اینباند انتخاب‌شده</Badge>
            <Button size="sm" variant="ghost" onClick={() => setSelectedIds([])}>
              لغو انتخاب
            </Button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Button size="sm" variant="outline" icon={<Power size={14} />} loading={bulkStatusMutation.isPending} onClick={() => bulkStatusMutation.mutate(true)}>
              فعال‌سازی
            </Button>
            <Button size="sm" variant="outline" icon={<Power size={14} />} loading={bulkStatusMutation.isPending} onClick={() => bulkStatusMutation.mutate(false)}>
              غیرفعال‌سازی
            </Button>
            <Button size="sm" variant="outline" icon={<RotateCcw size={14} />} loading={bulkResetMutation.isPending} onClick={() => bulkResetMutation.mutate()}>
              ریست ترافیک
            </Button>
            <Button size="sm" variant="danger" icon={<Trash2 size={14} />} onClick={() => setBulkDeleteOpen(true)}>
              حذف گروهی
            </Button>
          </div>
        </div>
      )}

      {inbounds.isLoading ? (
        <Card>
          <Spinner />
        </Card>
      ) : inbounds.isError ? (
        <Card>
          <EmptyState
            icon={<Boxes size={24} />}
            title="دریافت اینباندها ناموفق بود"
            description={(inbounds.error as Error).message}
            action={<Button onClick={() => inbounds.refetch()}>تلاش دوباره</Button>}
          />
        </Card>
      ) : (inbounds.data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={<Boxes size={26} />}
            title="هنوز اینباندی ندارید"
            description="یک مسیر VLESS Reality یا VMess WebSocket بسازید تا کاربران بتوانند متصل شوند."
            action={
              <Button icon={<Plus size={16} />} onClick={openCreate}>
                ساخت اولین اینباند
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "8px" }}>
            <Button variant="ghost" size="sm" icon={selectedIds.length === inbounds.data?.length ? <CheckSquare size={15} /> : <Square size={15} />} onClick={selectAll}>
              {selectedIds.length === inbounds.data?.length ? "لغو انتخاب همه" : "انتخاب همه"}
            </Button>
          </div>

          <div className="inbound-grid">
            {inbounds.data?.map((inbound) => {
              const isSelected = selectedIds.includes(inbound.id);
              const status = inbound.status || (inbound.is_active ? "active" : "disabled");
              return (
                <Card key={inbound.id} className={cn("inbound-card", !inbound.is_active && "is-inactive", isSelected && "border-primary")}>
                  <div className="inbound-head">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(inbound.id)}
                      style={{ cursor: "pointer", width: "16px", height: "16px" }}
                      aria-label="انتخاب اینباند"
                    />
                    <span className={cn("protocol-mark", `protocol-${inbound.protocol}`)}>
                      {inbound.protocol === "shadowsocks" ? "SS" : inbound.protocol.toUpperCase()}
                    </span>
                    <div className="inbound-title">
                      <strong>{inbound.remark}</strong>
                      <span dir="ltr">
                        {inbound.tag} · :{inbound.port}
                      </span>
                    </div>
                    {status === "active" ? (
                      <Badge tone="success">فعال</Badge>
                    ) : status === "expired" ? (
                      <Badge tone="danger">منقضی‌شده</Badge>
                    ) : status === "limited" ? (
                      <Badge tone="warning">سقف ترافیک</Badge>
                    ) : (
                      <Badge tone="neutral">غیرفعال</Badge>
                    )}
                  </div>

                  <div className="inbound-tags">
                    <Badge tone="info">{protocolLabel(inbound.protocol)}</Badge>
                    <Badge tone={inbound.security === "reality" ? "violet" : inbound.security === "tls" ? "success" : "neutral"}>
                      {inbound.security === "none" ? "بدون امنیت" : inbound.security.toUpperCase()}
                    </Badge>
                    <Badge tone="neutral">{inbound.network}</Badge>
                  </div>

                  <div className="inbound-specs">
                    <div>
                      <span>
                        <Server size={13} /> نود
                      </span>
                      <strong>{inbound.node_name ?? "Local"}</strong>
                    </div>
                    <div>
                      <span>
                        <Globe2 size={13} /> SNI / Host
                      </span>
                      <strong dir="ltr">{inbound.sni || inbound.host || "—"}</strong>
                    </div>
                    <div>
                      <span>
                        <Network size={13} /> مسیر
                      </span>
                      <strong dir="ltr">{inbound.network === "grpc" ? inbound.service_name : inbound.path || "—"}</strong>
                    </div>
                    <div>
                      <span>
                        <Shield size={13} /> مصرف / سقف
                      </span>
                      <strong>
                        {formatBytes(inbound.total_bytes)}
                        {inbound.data_limit_bytes ? ` / ${formatBytes(inbound.data_limit_bytes)}` : " (نامحدود)"}
                      </strong>
                    </div>
                  </div>

                  {/* Traffic limit progress bar if quota set */}
                  {inbound.data_limit_bytes && inbound.data_limit_bytes > 0 && (
                    <div style={{ marginTop: "8px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--color-text-secondary, #9ca3af)", marginBottom: "4px" }}>
                        <span>درصد مصرف سقف ترافیک</span>
                        <span>{inbound.usage_percent ?? 0}%</span>
                      </div>
                      <div style={{ width: "100%", height: "6px", backgroundColor: "#374151", borderRadius: "3px", overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.min(100, inbound.usage_percent ?? 0)}%`,
                            height: "100%",
                            backgroundColor: (inbound.usage_percent ?? 0) >= 90 ? "#ef4444" : (inbound.usage_percent ?? 0) >= 75 ? "#f59e0b" : "#10b981",
                            transition: "width 0.3s ease",
                          }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Expiration and Reset Info */}
                  {(inbound.expire_at || inbound.reset_interval_days) && (
                    <div style={{ display: "flex", gap: "12px", fontSize: "11px", color: "var(--color-text-secondary, #9ca3af)", marginTop: "6px" }}>
                      {inbound.expire_at && (
                        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                          <Calendar size={12} /> انقضا: {new Date(inbound.expire_at).toLocaleDateString("fa-IR")}
                        </span>
                      )}
                      {inbound.reset_interval_days && (
                        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                          <RotateCcw size={12} /> ریست خودکار: هر {inbound.reset_interval_days} روز
                        </span>
                      )}
                    </div>
                  )}

                  {inbound.security === "reality" && (
                    <div className="reality-strip" dir="ltr">
                      <KeyRound size={13} />
                      <span>{inbound.reality_public_key || "بدون کلید عمومی"}</span>
                      <span className="short-id">{inbound.reality_short_id}</span>
                    </div>
                  )}

                  <div className="inbound-actions">
                    <Button variant="ghost" size="sm" icon={<Pencil size={15} />} onClick={() => openEdit(inbound)}>
                      ویرایش
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Power size={15} />}
                      onClick={() => toggleMutation.mutate(inbound)}
                    >
                      {inbound.is_active ? "غیرفعال" : "فعال"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<RotateCcw size={14} />}
                      title="ریست ترافیک مصرفی اینباند"
                      onClick={() => resetTrafficMutation.mutate(inbound.id)}
                    >
                      ریست
                    </Button>
                    <button type="button" className="icon-btn danger-hover" title="حذف" onClick={() => setDeleteTarget(inbound)}>
                      <Trash2 size={16} />
                    </button>
                  </div>
                </Card>
              );
            })}
          </div>
        </>
      )}

      {/* Inbound Create / Edit Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? `ویرایش ${editing.tag}` : "ساخت اینباند جدید"}
        description="تنظیمات ارتباطی را مشخص کنید. تغییرات پس از «اعمال کانفیگ» روی هسته اعمال می‌شوند."
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              انصراف
            </Button>
            <Button type="submit" form="inbound-form" loading={saveMutation.isPending}>
              {editing ? "ذخیره اینباند" : "ساخت اینباند"}
            </Button>
          </>
        }
      >
        <form id="inbound-form" onSubmit={submit} className="form-grid">
          <Field label="نام نمایشی">
            <Input
              value={form.remark}
              onChange={(event) => setForm({ ...form, remark: event.target.value })}
              placeholder="Reality – Frankfurt"
              required
            />
          </Field>
          <Field label="تگ یکتا" hint="در کانفیگ Xray استفاده می‌شود">
            <Input
              value={form.tag}
              onChange={(event) => setForm({ ...form, tag: event.target.value })}
              placeholder="vless-reality-de"
              dir="ltr"
              required
            />
          </Field>

          <Field label="پروتکل">
            <Select value={form.protocol} onChange={(event) => changeProtocol(event.target.value as Protocol)}>
              {PROTOCOLS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="نود میزبان">
            <Select value={form.nodeId} onChange={(event) => setForm({ ...form, nodeId: event.target.value })}>
              <option value="">نود محلی</option>
              {nodes.data?.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.name} {node.is_local ? "(محلی)" : ""}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="پورت">
            <Input
              type="number"
              min="1"
              max="65535"
              value={form.port}
              onChange={(event) => setForm({ ...form, port: event.target.value })}
              dir="ltr"
              required
            />
          </Field>
          <Field label="آدرس شنود">
            <Input
              value={form.listen}
              onChange={(event) => setForm({ ...form, listen: event.target.value })}
              dir="ltr"
            />
          </Field>

          <Field label="شبکه">
            <Select value={form.network} onChange={(event) => changeNetwork(event.target.value as NetworkType)}>
              <option value="tcp">RAW / TCP</option>
              <option value="kcp">mKCP (UDP)</option>
              <option value="ws">WebSocket</option>
              <option value="grpc">gRPC</option>
              <option value="httpupgrade">HTTP Upgrade</option>
              <option value="xhttp">XHTTP</option>
            </Select>
          </Field>
          <Field label="لایه امنیتی">
            <Select
              value={form.security}
              onChange={(event) => {
                const security = event.target.value as Security;
                setForm({
                  ...form,
                  security,
                  flow:
                    security === "reality" && form.protocol === "vless" && form.network === "tcp"
                      ? "xtls-rprx-vision"
                      : "",
                });
              }}
            >
              <option value="reality" disabled={form.protocol !== "vless" || !["tcp", "grpc", "xhttp"].includes(form.network)}>
                Reality
              </option>
              <option value="tls">TLS</option>
              <option value="none">بدون امنیت</option>
            </Select>
          </Field>

          {/* Traffic Limit and Expiration Inputs */}
          <Field label="سقف حجم اینباند (گیگابایت)" hint="خالی = ترافیک نامحدود">
            <Input
              type="number"
              step="0.5"
              min="0"
              value={form.dataLimitGb}
              onChange={(event) => setForm({ ...form, dataLimitGb: event.target.value })}
              placeholder="مثلاً ۱۰۰۰ برای ۱ ترابایت"
              dir="ltr"
            />
          </Field>

          <Field label="تاریخ انقضای اینباند" hint="خالی = بدون تاریخ انقضا">
            <Input
              type="date"
              value={form.expireAt}
              onChange={(event) => setForm({ ...form, expireAt: event.target.value })}
              dir="ltr"
            />
          </Field>

          <Field label="دوره ریست خودکار ترافیک (روز)" hint="مثلاً ۳۰ برای ریست ماهانه، خالی = غیرفعال">
            <Input
              type="number"
              min="1"
              max="365"
              value={form.resetIntervalDays}
              onChange={(event) => setForm({ ...form, resetIntervalDays: event.target.value })}
              placeholder="مثلاً ۳۰"
              dir="ltr"
            />
          </Field>

          {form.security !== "none" && (
            <Field label="SNI">
              <Input
                value={form.sni}
                onChange={(event) => setForm({ ...form, sni: event.target.value })}
                placeholder="www.cloudflare.com"
                dir="ltr"
              />
            </Field>
          )}
          {form.security === "reality" && (
            <>
              <Field label="مقصد Reality" hint="مثلاً www.cloudflare.com:443">
                <Input
                  value={form.realityDest}
                  onChange={(event) => setForm({ ...form, realityDest: event.target.value })}
                  dir="ltr"
                />
              </Field>
              <Field label="Flow" hint="برای VLESS روی TCP معمولاً vision">
                <Input
                  value={form.flow}
                  onChange={(event) => setForm({ ...form, flow: event.target.value })}
                  dir="ltr"
                />
              </Field>
              <div className="key-box field-span-2">
                <div className="key-box-head">
                  <div>
                    <strong>کلیدهای Reality</strong>
                    <span>اگر خالی بمانند، هنگام ذخیره خودکار تولید می‌شوند.</span>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    icon={<KeyRound size={15} />}
                    loading={keysMutation.isPending}
                    onClick={() => keysMutation.mutate()}
                  >
                    تولید کلید
                  </Button>
                </div>
                <div className="form-grid key-grid">
                  <Field label="Public Key">
                    <Input
                      value={form.realityPublicKey}
                      onChange={(event) => setForm({ ...form, realityPublicKey: event.target.value })}
                      dir="ltr"
                      placeholder="خودکار"
                    />
                  </Field>
                  <Field label="Private Key">
                    <Input
                      type="password"
                      autoComplete="new-password"
                      value={form.realityPrivateKey}
                      onChange={(event) => setForm({ ...form, realityPrivateKey: event.target.value })}
                      dir="ltr"
                      placeholder="خودکار"
                    />
                  </Field>
                  <Field label="Short ID">
                    <Input
                      value={form.realityShortId}
                      onChange={(event) => setForm({ ...form, realityShortId: event.target.value })}
                      dir="ltr"
                      placeholder="خودکار"
                    />
                  </Field>
                </div>
              </div>
            </>
          )}

          {form.security === "tls" && (
            <>
              <Field label="پروانه TLS (مسیر)">
                <Input
                  value={form.tlsCertPath}
                  onChange={(event) => setForm({ ...form, tlsCertPath: event.target.value })}
                  placeholder="/etc/ssl/fullchain.pem"
                  dir="ltr"
                />
              </Field>
              <Field label="کلید TLS (مسیر)">
                <Input
                  value={form.tlsKeyPath}
                  onChange={(event) => setForm({ ...form, tlsKeyPath: event.target.value })}
                  placeholder="/etc/ssl/privkey.pem"
                  dir="ltr"
                />
              </Field>
              <Field label="ALPN" hint="برای TLS مثلاً h2,http/1.1">
                <Input value={form.alpn} onChange={(event) => setForm({ ...form, alpn: event.target.value })} dir="ltr" />
              </Field>
            </>
          )}

          {(form.network === "ws" || form.network === "httpupgrade" || form.network === "xhttp") && (
            <>
              <Field label="Host هدر">
                <Input
                  value={form.host}
                  onChange={(event) => setForm({ ...form, host: event.target.value })}
                  placeholder="cdn.example.com"
                  dir="ltr"
                />
              </Field>
              <Field label="Path">
                <Input
                  value={form.path}
                  onChange={(event) => setForm({ ...form, path: event.target.value })}
                  placeholder="/spectergate"
                  dir="ltr"
                />
              </Field>
            </>
          )}
          {form.network === "grpc" && (
            <Field label="نام سرویس gRPC" className="field-span-2">
              <Input
                value={form.serviceName}
                onChange={(event) => setForm({ ...form, serviceName: event.target.value })}
                placeholder="spectergate"
                dir="ltr"
              />
            </Field>
          )}

          <div className="field-span-2 form-toggle-row">
            <div>
              <strong>وضعیت اینباند</strong>
              <span>اینباند غیرفعال در کانفیگ Xray و لینک‌های اشتراک قرار نمی‌گیرد.</span>
            </div>
            <Toggle
              checked={form.isActive}
              onChange={(value) => setForm({ ...form, isActive: value })}
              label={form.isActive ? "فعال" : "غیرفعال"}
            />
          </div>

          <InboundAdvanced value={form.advanced} onChange={(advanced) => setForm({ ...form, advanced })} network={form.network} security={form.security} />
          {formError && <div className="form-error field-span-2">{formError}</div>}
        </form>
      </Modal>

      {/* Single Delete Confirm Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title="حذف اینباند"
        message={`آیا از حذف اینباند «${deleteTarget?.tag}» اطمینان دارید؟ تمام کاربران مرتبط اتصال به این اینباند را از دست خواهند داد.`}
        confirmLabel="حذف اینباند"
        danger
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget);
        }}
      />

      {/* Bulk Delete Confirm Dialog */}
      <ConfirmDialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        title="حذف گروهی اینباندها"
        message={`آیا از حذف تمام ${formatNumber(selectedIds.length)} اینباند انتخاب‌شده اطمینان دارید؟ این عمل غیرقابل بازگشت است.`}
        confirmLabel="حذف تمام انتخاب‌شده‌ها"
        danger
        loading={bulkDeleteMutation.isPending}
        onConfirm={() => bulkDeleteMutation.mutate()}
      />

      {/* Xray Config Preview Modal */}
      <Modal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title="پیش‌نمایش کانفیگ Xray"
        description="خروجی JSON بر اساس اینباندهای فعال روی نود محلی."
        wide
        footer={
          <Button
            icon={<Wand2 size={16} />}
            loading={applyMutation.isPending}
            onClick={() => {
              setPreviewOpen(false);
              applyMutation.mutate();
            }}
          >
            اعمال این کانفیگ
          </Button>
        }
      >
        {preview.isLoading ? (
          <Spinner />
        ) : preview.isError ? (
          <div className="form-error">{(preview.error as Error).message}</div>
        ) : (
          <>
            <div className="preview-meta">
              <Badge tone="info">{formatNumber(preview.data?.inbound_count ?? 0)} اینباند</Badge>
              <Badge tone="violet">{formatNumber(preview.data?.client_count ?? 0)} کلاینت</Badge>
              {preview.data?.warnings.map((warning) => (
                <Badge key={warning} tone="warning">
                  {warning}
                </Badge>
              ))}
            </div>
            <pre className="code-block" dir="ltr">
              {JSON.stringify(preview.data?.config, null, 2)}
            </pre>
          </>
        )}
      </Modal>

      {/* Result Dialog after applying config */}
      {applyResult && (
        <Modal
          open={applyResult !== null}
          onClose={() => setApplyResult(null)}
          title={applyResult.ok ? "کانفیگ با موفقیت اعمال شد" : "خطا در اعمال کانفیگ"}
          footer={<Button onClick={() => setApplyResult(null)}>متوجه شدم</Button>}
        >
          <div className="apply-result-content">
            <p>{applyResult.message}</p>
            {applyResult.warnings && applyResult.warnings.length > 0 && (
              <div className="apply-warnings">
                <strong>هشدارها:</strong>
                <ul>
                  {applyResult.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
