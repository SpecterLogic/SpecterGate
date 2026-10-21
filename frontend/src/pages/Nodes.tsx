import { t, tt } from "../lib/i18n";import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  Copy,
  Cpu,
  KeyRound,
  MemoryStick,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Signal,
  Terminal,
  Trash2,
  Wifi,
  WifiOff } from
"lucide-react";
import { api, API_BASE } from "../lib/api";
import { useToast } from "../lib/toast";
import type { Node, OperationResult } from "../lib/types";
import { cn, formatDateTime, formatNumber, formatRelative } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  Spinner,
  StatusBadge,
  Textarea } from
"../components/UI";

interface NodeForm {
  name: string;
  address: string;
  port: string;
  apiAddress: string;
  apiPort: string;
  coefficient: string;
  note: string;
}

const EMPTY_FORM: NodeForm = {
  name: "",
  address: "",
  port: "443",
  apiAddress: "",
  apiPort: "10085",
  coefficient: "1",
  note: ""
};

function nodeToForm(node: Node): NodeForm {
  return {
    name: node.name,
    address: node.address,
    port: String(node.port),
    apiAddress: node.api_address ?? "",
    apiPort: node.api_port ? String(node.api_port) : "",
    coefficient: String(node.traffic_coefficient),
    note: node.note ?? ""
  };
}

export default function NodesPage() {
  const apiOrigin = new URL(API_BASE || '/', window.location.origin).href.replace(/\/$/, '');
  const toast = useToast();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Node | null>(null);
  const [form, setForm] = useState<NodeForm>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Node | null>(null);
  const [guideNode, setGuideNode] = useState<Node | null>(null);

  const nodes = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api.get<Node[]>("/api/nodes"),
    refetchInterval: 30_000
  });

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => {
      if (editing) return api.patch<Node>(`/api/nodes/${editing.id}`, payload);
      return api.post<Node>("/api/nodes", payload);
    },
    onSuccess: (node) => {
      toast.success(editing ? t("نود ذخیره شد.") : tt("نود {0} اضافه شد.", [node.name]));
      setModalOpen(false);
      setEditing(null);
      setFormError("");
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => setFormError(error.message)
  });

  const deleteMutation = useMutation({
    mutationFn: (node: Node) => api.delete<OperationResult>(`/api/nodes/${node.id}`),
    onSuccess: () => {
      toast.success(t("نود حذف شد."));
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const rotateMutation = useMutation({
    mutationFn: (node: Node) => api.post<Node>(`/api/nodes/${node.id}/rotate-key`),
    onSuccess: () => {
      toast.success(t("کلید نود چرخش کرد. عامل نود را به‌روزرسانی کنید."));
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const onlineCount = nodes.data?.filter((node) => node.is_online).length ?? 0;
  const avgCpu = nodes.data?.length ?
  Math.round(nodes.data.reduce((sum, node) => sum + node.cpu_usage, 0) / nodes.data.length) :
  0;
  const inboundCount = nodes.data?.reduce((sum, node) => sum + node.inbound_count, 0) ?? 0;

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setModalOpen(true);
  }

  function openEdit(node: Node) {
    setEditing(node);
    setForm(nodeToForm(node));
    setFormError("");
    setModalOpen(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (!form.name.trim() || !form.address.trim()) {
      setFormError(t("نام و آدرس نود الزامی است."));
      return;
    }
    saveMutation.mutate({
      name: form.name.trim(),
      address: form.address.trim(),
      port: Number(form.port),
      api_address: form.apiAddress.trim() || null,
      api_port: form.apiPort ? Number(form.apiPort) : null,
      traffic_coefficient: Number(form.coefficient) || 1,
      note: form.note.trim() || null
    });
  }

  async function copyKey(node: Node) {
    try {
      await navigator.clipboard.writeText(node.api_key);
      toast.success(t("کلید نود کپی شد."));
    } catch {
      toast.error(t("کپی کلید ممکن نشد."));
    }
  }

  return (
    <div className="nodes-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">{t("زیرساخت توزیع‌شده")}</p>
          <h2>{t("نودها و عامل‌ها")}</h2>
          <p className="page-subtitle">{t("سلامت سرورها، مصرف منابع و اتصال عامل‌های Xray را مدیریت کنید.")}</p>
        </div>
        <div className="page-actions">
          <Button variant="outline" icon={<RefreshCw size={16} />} onClick={() => nodes.refetch()} loading={nodes.isFetching}>{"" + t("به‌روزرسانی") + " "}

          </Button>
          <Button icon={<Plus size={17} />} onClick={openCreate}>{"" + t("افزودن نود") + " "}

          </Button>
        </div>
      </div>

      <div className="mini-stat-grid">
        <Card className="mini-stat">
          <span className="mini-stat-icon teal">
            <Wifi size={18} />
          </span>
          <div>
            <strong>
              {formatNumber(onlineCount)} <small>/ {formatNumber(nodes.data?.length ?? 0)}</small>
            </strong>
            <span>{t("نود آنلاین")}</span>
          </div>
        </Card>
        <Card className="mini-stat">
          <span className="mini-stat-icon violet">
            <Cpu size={18} />
          </span>
          <div>
            <strong>{formatNumber(avgCpu)}{t("٪")}</strong>
            <span>{t("میانگین مصرف CPU")}</span>
          </div>
        </Card>
        <Card className="mini-stat">
          <span className="mini-stat-icon amber">
            <Boxes size={18} />
          </span>
          <div>
            <strong>{formatNumber(inboundCount)}</strong>
            <span>{t("اینباند توزیع‌شده")}</span>
          </div>
        </Card>
      </div>

      {nodes.isLoading ?
      <Card>
          <Spinner />
        </Card> :
      nodes.isError ?
      <Card>
          <EmptyState
          icon={<Server size={24} />}
          title={t("دریافت نودها ناموفق بود")}
          description={(nodes.error as Error).message}
          action={<Button onClick={() => nodes.refetch()}>{t("تلاش دوباره")}</Button>} />

        </Card> :
      (nodes.data?.length ?? 0) === 0 ?
      <Card>
          <EmptyState
          icon={<Server size={26} />}
          title={t("هنوز نودی اضافه نشده")}
          description={t("نود محلی به‌طور خودکار ساخته می‌شود. برای مقیاس‌پذیری می‌توانید سرورهای دیگر را اضافه کنید.")}
          action={<Button onClick={openCreate}>{t("افزودن نود")}</Button>} />

        </Card> :

      <div className="node-grid">
          {nodes.data?.map((node) =>
        <Card key={node.id} className={cn("node-card", !node.is_online && "is-offline")}>
              <div className="node-card-head">
                <span className={cn("node-orb", node.is_online ? "online" : "offline")}>
                  {node.is_online ? <Wifi size={20} /> : <WifiOff size={20} />}
                </span>
                <div className="node-name">
                  <div>
                    <strong>{node.name}</strong>
                    {node.is_local && <Badge tone="info">{t("محلی")}</Badge>}
                  </div>
                  <span dir="ltr">
                    {node.address}:{node.port}
                  </span>
                </div>
                <StatusBadge status={node.is_online ? "online" : "offline"} />
              </div>

              <div className="node-resource-grid">
                <div>
                  <span>
                    <Cpu size={13} /> CPU
                  </span>
                  <strong>{formatNumber(Math.round(node.cpu_usage))}{t("٪")}</strong>
                  <div className="resource-bar">
                    <i style={{ width: `${Math.min(100, node.cpu_usage)}%` }} />
                  </div>
                </div>
                <div>
                  <span>
                    <MemoryStick size={13} /> RAM
                  </span>
                  <strong>{formatNumber(Math.round(node.memory_usage))}{t("٪")}</strong>
                  <div className="resource-bar violet">
                    <i style={{ width: `${Math.min(100, node.memory_usage)}%` }} />
                  </div>
                </div>
              </div>

              <div className="node-facts">
                <div>
                  <span>{t("اینباند")}</span>
                  <strong>{formatNumber(node.inbound_count)}</strong>
                </div>
                <div>
                  <span>{t("ضریب ترافیک")}</span>
                  <strong>×{formatNumber(node.traffic_coefficient)}</strong>
                </div>
                <div>
                  <span>{t("آخرین سیگنال")}</span>
                  <strong>{node.is_local ? t("همین سرور") : formatRelative(node.last_seen_at)}</strong>
                </div>
              </div>

              <div className="node-key">
                <KeyRound size={14} />
                <code dir="ltr">{node.api_key.slice(0, 14)}••••••••</code>
                <button type="button" className="icon-btn" onClick={() => copyKey(node)} title={t("کپی کلید")}>
                  <Copy size={14} />
                </button>
                <button type="button" className="icon-btn" onClick={() => rotateMutation.mutate(node)} title={t("چرخش کلید")}>
                  <RefreshCw size={14} />
                </button>
              </div>

              <div className="node-card-actions">
                <Button variant="ghost" size="sm" icon={<Terminal size={15} />} onClick={() => setGuideNode(node)}>{"" + t("راهنمای عامل") + " "}

            </Button>
                <Button variant="ghost" size="sm" icon={<Pencil size={15} />} onClick={() => openEdit(node)}>{"" + t("ویرایش") + " "}

            </Button>
                {!node.is_local &&
            <button type="button" className="icon-btn danger-hover" title={t("حذف")} onClick={() => setDeleteTarget(node)}>
                    <Trash2 size={16} />
                  </button>
            }
              </div>
            </Card>
        )}
        </div>
      }

      <Card className="agent-info">
        <div className="agent-info-head">
          <span className="agent-icon">
            <Activity size={20} />
          </span>
          <div>
            <strong>{t("عامل نود چیست؟")}</strong>
            <p>{"" + t("هر نود راه دور با عامل سبک، کانفیگ مخصوص خود را از پنل می‌گیرد و ضربان قلب و آمار مصرف را گزارش می‌کند. کلید اختصاصی نود را در هدر") + " "}

              <code>X-Node-Key</code>{" " + t("قرار دهید.") + " "}
            </p>
          </div>
        </div>
        <div className="agent-endpoints">
          <span dir="ltr"><Signal size={13} /> GET /api/agent/config</span>
          <span dir="ltr"><Signal size={13} /> POST /api/agent/heartbeat</span>
          <span dir="ltr"><Signal size={13} /> POST /api/agent/usage</span>
        </div>
      </Card>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? tt("ویرایش {0}", [editing.name]) : t("افزودن نود")}
        description={t("آدرس عمومی نود در لینک‌های اشتراک استفاده می‌شود.")}
        footer={
        <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>{"" + t("انصراف") + " "}

          </Button>
            <Button type="submit" form="node-form" loading={saveMutation.isPending}>
              {editing ? t("ذخیره نود") : t("افزودن نود")}
            </Button>
          </>
        }>

        <form id="node-form" onSubmit={submit} className="form-grid">
          <Field label={t("نام نود")}>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Frankfurt-01"
              required />

          </Field>
          <Field label={t("آدرس عمومی")} hint={t("IP یا دامنه‌ای که کلاینت‌ها به آن وصل می‌شوند")}>
            <Input
              value={form.address}
              onChange={(event) => setForm({ ...form, address: event.target.value })}
              placeholder="de1.example.com"
              dir="ltr"
              required />

          </Field>
          <Field label={t("پورت عمومی")}>
            <Input
              type="number"
              min="1"
              max="65535"
              value={form.port}
              onChange={(event) => setForm({ ...form, port: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("ضریب ترافیک")} hint={t("مثلاً ۱.۵ برای محاسبهٔ ۵۰٪ بیشتر")}>
            <Input
              type="number"
              step="0.1"
              min="0.1"
              max="10"
              value={form.coefficient}
              onChange={(event) => setForm({ ...form, coefficient: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("آدرس API نود (اختیاری)")}>
            <Input
              value={form.apiAddress}
              onChange={(event) => setForm({ ...form, apiAddress: event.target.value })}
              placeholder="10.0.0.12"
              dir="ltr" />

          </Field>
          <Field label={t("پورت API نود (اختیاری)")}>
            <Input
              type="number"
              min="1"
              max="65535"
              value={form.apiPort}
              onChange={(event) => setForm({ ...form, apiPort: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("یادداشت")} className="field-span-2">
            <Textarea
              rows={3}
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
              placeholder={t("مشخصات سرور، دیتاسنتر یا محدودیت‌ها...")} />

          </Field>
          {formError && <div className="form-error field-span-2">{formError}</div>}
        </form>
      </Modal>

      <Modal
        open={guideNode !== null}
        onClose={() => setGuideNode(null)}
        title={tt("راهنمای اتصال عامل · {0}", [guideNode?.name ?? ""])}
        description={t("این کلید را در فایل تنظیمات عامل نود قرار دهید. کلید را در محیط امن نگهداری کنید.")}
        wide
        footer={
        <Button variant="ghost" onClick={() => setGuideNode(null)}>{"" + t("بستن") + " "}

        </Button>
        }>

        <div className="guide-block">
          <span>{t("کلید نود")}</span>
          <div className="guide-key" dir="ltr">
            <code>{guideNode?.api_key}</code>
            <button
              type="button"
              className="icon-btn"
              onClick={() => guideNode && copyKey(guideNode)}
              title={t("کپی کلید")}>

              <Copy size={15} />
            </button>
          </div>
        </div>
        <div className="guide-block">
          <span>{t("ضربان قلب (هر ۶۰ ثانیه)")}</span>
          <pre className="code-block" dir="ltr">
{`curl -X POST ${apiOrigin}/api/agent/heartbeat \\
  -H "X-Node-Key: ${guideNode?.api_key ?? "<NODE_KEY>"}" \\
  -H "Content-Type: application/json" \\
  -d '{"cpu_usage": 18.4, "memory_usage": 42.1, "status": "online"}'`}
          </pre>
        </div>
        <div className="guide-block">
          <span>{t("دریافت خودکار کانفیگ")}</span>
          <pre className="code-block" dir="ltr">
{`curl ${apiOrigin}/api/agent/config \\
  -H "X-Node-Key: ${guideNode?.api_key ?? "<NODE_KEY>"}"`}
          </pre>
          <p className="guide-foot">{"" + t("عامل رسمی:") + " "}
            <code>agent/spectergate_agent.py</code>{" " + t("— کانفیگ را اعتبارسنجی، نصب و Xray را مدیریت می‌کند.") + " "}
          </p>
        </div>
        <div className="guide-block">
          <span>{t("گزارش مصرف کاربران")}</span>
          <pre className="code-block" dir="ltr">
{`curl -X POST ${apiOrigin}/api/agent/usage \\
  -H "X-Node-Key: ${guideNode?.api_key ?? "<NODE_KEY>"}" \\
  -H "Content-Type: application/json" \\
  -d '{"entries": [{"uuid": "<USER_UUID>", "upload": 1048576, "download": 5242880}]}'`}
          </pre>
        </div>
        <p className="guide-foot">{"" + t("آخرین سیگنال این نود:") + " "}
          {guideNode?.last_seen_at ? formatDateTime(guideNode.last_seen_at) : t("هنوز دریافت نشده")}
        </p>
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
        title={t("حذف نود")}
        message={tt("نود «{0}» و ارتباط اینباندهایش حذف می‌شود. این عملیات بازگشت‌پذیر نیست.", [deleteTarget?.name ?? ""])}
        confirmLabel={t("حذف نود")}
        loading={deleteMutation.isPending} />

    </div>);

}
