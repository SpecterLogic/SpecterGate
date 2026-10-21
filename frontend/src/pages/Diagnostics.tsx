import { t, tt } from "../lib/i18n";import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeftRight, CheckCircle2, AlertCircle, Plus, Trash2, Zap, Layers, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { Button, Card, Field, Input, Modal, SectionHeader, Select } from "../components/UI";
import { useToast } from "../lib/toast";

interface TestRouteResult {
  outbound: string;
  rule_index: number | null;
  rule_name: string;
  reason: string;
  matched: boolean;
}

interface PingResult {
  reachable: boolean;
  host: string;
  port: number;
  latency_ms: number | null;
  resolved_ip: string | null;
  error: string | null;
}

interface OutboundBalancer {
  tag: string;
  name: string;
  selector: string[];
  strategy: "random" | "roundRobin" | "leastPing";
}

export function Diagnostics() {
  const toast = useToast();
  const queryClient = useQueryClient();

  // Test Route state
  const [routeDomain, setRouteDomain] = useState("youtube.com");
  const [routeIp, setRouteIp] = useState("");
  const [routePort, setRoutePort] = useState("443");
  const [routeNetwork, setRouteNetwork] = useState<"tcp" | "udp">("tcp");
  const [inboundTag, setInboundTag] = useState("");
  const [protocol, setProtocol] = useState("");
  const [routeResult, setRouteResult] = useState<TestRouteResult | null>(null);

  // Ping state
  const [pingHost, setPingHost] = useState("1.1.1.1");
  const [pingPort, setPingPort] = useState("443");
  const [pingResult, setPingResult] = useState<PingResult | null>(null);

  // Balancers state
  const [balancerModalOpen, setBalancerModalOpen] = useState(false);
  const [bTag, setBTag] = useState("");
  const [bName, setBName] = useState("");
  const [bSelector, setBSelector] = useState("warp, direct");
  const [bStrategy, setBStrategy] = useState<"random" | "roundRobin" | "leastPing">("random");

  const { data: balancers = [], isLoading: balancersLoading } = useQuery<OutboundBalancer[]>({
    queryKey: ["outbound-balancers"],
    queryFn: () => api.get<OutboundBalancer[]>("/api/diagnostics/balancers")
  });

  const testRouteMutation = useMutation({
    mutationFn: (payload: any) => api.post<TestRouteResult>("/api/diagnostics/test-route", payload),
    onSuccess: (res) => {
      setRouteResult(res);
      toast.success(t("مسیر با موفقیت تحلیل شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در تست مسیر"));
    }
  });

  const pingMutation = useMutation({
    mutationFn: (payload: any) => api.post<PingResult>("/api/diagnostics/ping", payload),
    onSuccess: (res) => {
      setPingResult(res);
      if (res.reachable) {
        toast.success(tt("اتصال برقرار شد ({0} ms)", [res.latency_ms]));
      } else {
        toast.error(tt("اتصال ناموفق بود: {0}", [res.error || t("خطای ناشناخته")]));
      }
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در بررسی تأخیر اتصال"));
    }
  });

  const saveBalancersMutation = useMutation({
    mutationFn: (items: OutboundBalancer[]) => api.put<OutboundBalancer[]>("/api/diagnostics/balancers", items),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["outbound-balancers"] });
      setBalancerModalOpen(false);
      setBTag("");
      setBName("");
      toast.success(t("تنظیمات بالانسر خروجی ذخیره شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در ذخیره بالانسر"));
    }
  });

  const handleAddBalancer = (e: React.FormEvent) => {
    e.preventDefault();
    let tag = bTag.trim().toLowerCase();
    if (!tag.startsWith("balancer-")) {
      tag = `balancer-${tag}`;
    }
    const selector = bSelector.
    split(/[\n,]+/).
    map((s) => s.trim()).
    filter(Boolean);

    if (selector.length === 0) {
      toast.error(t("حداقل یک خروجی در سلکتور الزامی است."));
      return;
    }

    const updated = [...balancers.filter((b) => b.tag !== tag), { tag, name: bName.trim() || tag, selector, strategy: bStrategy }];
    saveBalancersMutation.mutate(updated);
  };

  const handleDeleteBalancer = (tag: string) => {
    const updated = balancers.filter((b) => b.tag !== tag);
    saveBalancersMutation.mutate(updated);
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("ابزار عیب‌یابی و بالانسر خروجی")}</h1>
          <p className="page-subtitle">{"" + t("بررسی مسیر با هستهٔ محلیِ در حال اجرا، تست اتصال TCP مستقیم و مدیریت بالانسر خروجی") + " "}

          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Routing Path Simulator Card */}
        <Card>
          <SectionHeader
            title={t("تست مسیر و مسیریابی واقعی (Routing Path)")}
            subtitle={t("نتیجه از قواعد اعمال‌شدهٔ هسته دریافت می‌شود؛ آزمون اتصال انتها‌به‌انتها نیست. ابتدا تنظیمات را روی هسته اعمال کنید.")} />


          <form
            onSubmit={(e) => {
              e.preventDefault();
              testRouteMutation.mutate({
                target_domain: routeDomain.trim() || undefined,
                target_ip: routeIp.trim() || undefined,
                target_port: routePort ? Number(routePort) : undefined,
                network: routeNetwork,
                inbound_tag: inboundTag.trim() || undefined,
                protocol: protocol || undefined
              });
            }}
            className="space-y-4">

            <div className="form-grid"><Field label={t("تگ ورودی (اختیاری)")}><Input dir="ltr" value={inboundTag} onChange={(e) => setInboundTag(e.target.value)} /></Field><Field label={t("پروتکل تشخیص‌داده‌شده (اختیاری)")}><Select value={protocol} onChange={(e) => setProtocol(e.target.value)}><option value="">{t("مشخص نشده")}</option>{["http", "tls", "quic", "bittorrent"].map((value) => <option key={value} value={value}>{value}</option>)}</Select></Field></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label={t("دامنه هدف")}>
                <Input
                  dir="ltr"
                  placeholder={t("مثال: youtube.com")}
                  value={routeDomain}
                  onChange={(e) => setRouteDomain(e.target.value)} />

              </Field>
              <Field label={t("آدرس IP هدف (اختیاری)")}>
                <Input
                  dir="ltr"
                  placeholder={t("مثال: 142.250.190.46")}
                  value={routeIp}
                  onChange={(e) => setRouteIp(e.target.value)} />

              </Field>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label={t("پورت مقصد")}>
                <Input
                  dir="ltr"
                  type="number"
                  placeholder="443"
                  value={routePort}
                  onChange={(e) => setRoutePort(e.target.value)} />

              </Field>
              <Field label={t("پروتکل شبکه")}>
                <Select value={routeNetwork} onChange={(e) => setRouteNetwork(e.target.value as any)}>
                  <option value="tcp">TCP</option>
                  <option value="udp">UDP</option>
                </Select>
              </Field>
            </div>

            <Button type="submit" variant="primary" loading={testRouteMutation.isPending} icon={<ArrowLeftRight size={16} />}>{"" + t("تحلیل و تست مسیر") + " "}

            </Button>
          </form>

          {routeResult &&
          <div className="mt-6 p-4 rounded-xl border border-border bg-card-secondary space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted">{t("خروجی انتخاب‌شده:")}</span>
                <span className={`badge ${routeResult.outbound === "blocked" ? "badge-danger" : "badge-success"} text-sm font-mono`}>
                  {routeResult.outbound}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted">{t("قانون اعمال‌شده:")}</span>
                <span className="font-medium">{routeResult.rule_name}</span>
              </div>
              <div className="text-xs text-muted pt-2 border-t border-border">
                <strong>{t("علت تطابق:")}</strong> {routeResult.reason}
              </div>
            </div>
          }
        </Card>

        {/* Connectivity & Ping Card */}
        <Card>
          <SectionHeader
            title={t("تست پینگ و اتصال سرور (Ping & Latency)")}
            subtitle={t("سنجش تأخیر اتصال TCP مستقیم از مبدأ این سرور به مقاصد خارجی")} />


          <form
            onSubmit={(e) => {
              e.preventDefault();
              pingMutation.mutate({
                host: pingHost.trim(),
                port: Number(pingPort) || 443
              });
            }}
            className="space-y-4">

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="sm:col-span-2">
                <Field label={t("هاست یا IP")}>
                  <Input
                    dir="ltr"
                    placeholder={t("مثال: 1.1.1.1 یا google.com")}
                    required
                    value={pingHost}
                    onChange={(e) => setPingHost(e.target.value)} />

                </Field>
              </div>
              <div>
                <Field label={t("پورت")}>
                  <Input
                    dir="ltr"
                    type="number"
                    value={pingPort}
                    onChange={(e) => setPingPort(e.target.value)} />

                </Field>
              </div>
            </div>

            <Button type="submit" variant="secondary" loading={pingMutation.isPending} icon={<Zap size={16} />}>{"" + t("بررسی تأخیر ارتباط") + " "}

            </Button>
          </form>

          {pingResult &&
          <div className="mt-6 p-4 rounded-xl border border-border bg-card-secondary space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted">{t("وضعیت اتصال:")}</span>
                {pingResult.reachable ?
              <span className="badge badge-success flex items-center gap-1 text-xs">
                    <CheckCircle2 size={14} />{" " + t("متصل (Reachable)") + " "}
              </span> :

              <span className="badge badge-danger flex items-center gap-1 text-xs">
                    <AlertCircle size={14} />{" " + t("ناموفق (Unreachable)") + " "}
              </span>
              }
              </div>

              {pingResult.reachable &&
            <div className="flex items-center justify-between text-xs">
                  <span className="text-muted">{t("تأخیر رفت و برگشت (Latency):")}</span>
                  <span className="font-mono font-bold text-success text-sm">{pingResult.latency_ms} ms</span>
                </div>
            }

              {pingResult.resolved_ip &&
            <div className="flex items-center justify-between text-xs font-mono" dir="ltr">
                  <span className="text-muted">Resolved IP:</span>
                  <span>{pingResult.resolved_ip}</span>
                </div>
            }

              {pingResult.error &&
            <div className="text-xs text-danger pt-2 border-t border-border">
                  {pingResult.error}
                </div>
            }
            </div>
          }
        </Card>
      </div>

      {/* Outbound Balancers Card */}
      <Card className="mt-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
          <div>
            <h2 className="text-lg font-bold">{t("استخرهای بالانسر خروجی (Subscription & Outbound Balancers)")}</h2>
            <p className="text-sm text-muted">{"" + t("ترکیب چند خروجی (مانند Direct، WARP یا پراکسی‌های خارجی) با استراتژی‌های تصادفی یا کمترین پینگ") + " "}

            </p>
          </div>
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setBalancerModalOpen(true)}>{"" + t("افزودن بالانسر جدید") + " "}

          </Button>
        </div>

        {balancers.length === 0 ?
        <div className="text-center py-8 text-muted bg-card-secondary rounded-lg border border-border">{"" + t("هنوز هیچ بالانسر خروجی تعریف نشده است. با دکمه بالا اولین استخر خروجی را ایجاد کنید.") + " "}

        </div> :

        <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted text-right">
                  <th className="pb-3 pr-2">{t("تگ بالانسر")}</th>
                  <th className="pb-3">{t("عنوان")}</th>
                  <th className="pb-3">{t("استراتژی توزیع")}</th>
                  <th className="pb-3">{t("خروجی‌های عضو (Selector)")}</th>
                  <th className="pb-3 pl-2 text-left">{t("عملیات")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {balancers.map((b) =>
              <tr key={b.tag} className="hover:bg-card-secondary/50">
                    <td className="py-3 pr-2 font-mono text-xs" dir="ltr">
                      {b.tag}
                    </td>
                    <td className="py-3 font-medium">{b.name}</td>
                    <td className="py-3">
                      <span className="badge badge-secondary text-xs">
                        {b.strategy === "leastPing" ? t("کمترین پینگ") : b.strategy === "roundRobin" ? t("چرخشی (Round-Robin)") : t("تصادفی (Random)")}
                      </span>
                    </td>
                    <td className="py-3 font-mono" dir="ltr">
                      <div className="flex flex-wrap gap-1">
                        {b.selector.map((s, i) =>
                    <span key={i} className="badge badge-outline text-xs">
                            {s}
                          </span>
                    )}
                      </div>
                    </td>
                    <td className="py-3 pl-2 text-left">
                      <button
                    type="button"
                    className="text-danger hover:text-danger-hover p-1"
                    onClick={() => handleDeleteBalancer(b.tag)}
                    title={t("حذف بالانسر")}>

                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
              )}
              </tbody>
            </table>
          </div>
        }
      </Card>

      {/* Modal for Balancer */}
      <Modal open={balancerModalOpen} onClose={() => setBalancerModalOpen(false)} title={t("افزودن بالانسر خروجی جدید")}>
        <form onSubmit={handleAddBalancer} className="space-y-4">
          <Field label={t("شناسه بالانسر (Tag)")} hint={t("شناسه انگلیسی یکتا با پیشوند balancer-")}>
            <Input
              dir="ltr"
              placeholder="balancer-main"
              required
              value={bTag}
              onChange={(e) => setBTag(e.target.value)} />

          </Field>

          <Field label={t("عنوان نمایشی")}>
            <Input
              placeholder={t("مثال: بالانسر سریع استریم")}
              required
              value={bName}
              onChange={(e) => setBName(e.target.value)} />

          </Field>

          <Field label={t("استراتژی توزیع بار (Strategy)")}>
            <Select value={bStrategy} onChange={(e) => setBStrategy(e.target.value as any)}>
              <option value="random">{t("تصادفی (Random)")}</option>
              <option value="roundRobin">{t("چرخشی (Round-Robin)")}</option>
              <option value="leastPing">{t("کمترین پینگ و تأخیر (Least Ping)")}</option>
            </Select>
          </Field>

          <Field
            label={t("خروجی‌های عضو (Selector Tags)")}
            hint={t("تگ خروجی‌هایی که مایلید بار بین آن‌ها پخش شود (با ویرگول جدا کنید)")}>

            <Input
              dir="ltr"
              placeholder={t("مثال: direct, warp, proxy-socks")}
              required
              value={bSelector}
              onChange={(e) => setBSelector(e.target.value)} />

          </Field>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setBalancerModalOpen(false)}>{"" + t("انصراف") + " "}

            </Button>
            <Button type="submit" loading={saveBalancersMutation.isPending}>{"" + t("ثبت بالانسر") + " "}

            </Button>
          </div>
        </form>
      </Modal>
    </div>);

}
