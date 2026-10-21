import { t } from "../lib/i18n";import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Globe } from "lucide-react";
import { api } from "../lib/api";
import { Button, Card, Field, Input, Modal, SectionHeader, Select } from "../components/UI";
import { useToast } from "../lib/toast";

interface HostEntry {
  domain: string;
  ips: string[];
}

interface DnsConfig {
  servers: string[];
  hosts: HostEntry[];
  query_strategy: "UseIP" | "UseIPv4" | "UseIPv6";
  disable_cache: boolean;
  disable_fallback: boolean;
  client_ip?: string | null;
  tag?: string;
}

const PRESETS = [
{ name: t("کلودفلر (DoH + IP)"), servers: ["https://1.1.1.1/dns-query", "1.1.1.1", "1.0.0.1"] },
{ name: t("گوگل (DoH + IP)"), servers: ["https://dns.google/dns-query", "8.8.8.8", "8.8.4.4"] },
{ name: t("Quad9 (امنیت و فیلتر بدافزار)"), servers: ["https://dns.quad9.net/dns-query", "9.9.9.9"] },
{ name: t("شکن (رفع تحریم ایران)"), servers: ["178.22.122.100", "185.51.200.2"] },
{ name: t("الکترو (Electro تحریم‌شکن)"), servers: ["78.157.42.101", "78.157.42.100"] }];


export function DnsHosts() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [newServer, setNewServer] = useState("");
  const [searchHost, setSearchHost] = useState("");
  const [hostModalOpen, setHostModalOpen] = useState(false);
  const [hostDomain, setHostDomain] = useState("");
  const [hostIps, setHostIps] = useState("");

  const { data: config, isLoading } = useQuery<DnsConfig>({
    queryKey: ["dns-hosts-config"],
    queryFn: () => api.get<DnsConfig>("/api/dns-hosts")
  });

  const saveMutation = useMutation({
    mutationFn: (updated: DnsConfig) => api.put<DnsConfig>("/api/dns-hosts", updated),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dns-hosts-config"] });
      toast.success(t("تنظیمات DNS و هاست‌ها با موفقیت ذخیره شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در ذخیره تنظیمات"));
    }
  });

  const addHostMutation = useMutation({
    mutationFn: (entry: HostEntry) => api.post<HostEntry[]>("/api/dns-hosts/hosts", entry),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dns-hosts-config"] });
      setHostModalOpen(false);
      setHostDomain("");
      setHostIps("");
      toast.success(t("نگاشت دامنه با موفقیت ثبت شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در ثبت نگاشت"));
    }
  });

  const deleteHostMutation = useMutation({
    mutationFn: (domain: string) => api.delete<HostEntry[]>(`/api/dns-hosts/hosts/${encodeURIComponent(domain)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dns-hosts-config"] });
      toast.success(t("نگاشت با موفقیت حذف شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در حذف نگاشت"));
    }
  });

  if (isLoading || !config) {
    return <div className="page-loading">{t("در حال بارگذاری تنظیمات DNS...")}</div>;
  }

  const handleAddServer = () => {
    const trimmed = newServer.trim();
    if (!trimmed) return;
    if (config.servers.includes(trimmed)) {
      toast.error(t("این سرور قبلاً اضافه شده است."));
      return;
    }
    const updated = { ...config, servers: [...config.servers, trimmed] };
    saveMutation.mutate(updated);
    setNewServer("");
  };

  const handleRemoveServer = (index: number) => {
    const updatedServers = config.servers.filter((_, i) => i !== index);
    if (updatedServers.length === 0) {
      toast.error(t("حداقل یک سرور DNS الزامی است."));
      return;
    }
    saveMutation.mutate({ ...config, servers: updatedServers });
  };

  const handleApplyPreset = (presetServers: string[]) => {
    saveMutation.mutate({ ...config, servers: presetServers });
  };

  const handleSaveHost = (e: React.FormEvent) => {
    e.preventDefault();
    const domain = hostDomain.trim().toLowerCase();
    const ips = hostIps.
    split(/[\n,]+/).
    map((s) => s.trim()).
    filter(Boolean);

    if (!domain) {
      toast.error(t("دامنه الزامی است."));
      return;
    }
    if (ips.length === 0) {
      toast.error(t("حداقل یک آدرس IP الزامی است."));
      return;
    }

    addHostMutation.mutate({ domain, ips });
  };

  const filteredHosts = config.hosts.filter(
    (h) => h.domain.toLowerCase().includes(searchHost.toLowerCase()) || h.ips.some((ip) => ip.includes(searchHost))
  );

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("هاست‌ها و DNS جامع")}</h1>
          <p className="page-subtitle">{"" + t("پیکربندی سرورهای DNS هسته، استراتژی حل نام و نگاشت استاتیک دامنه به IP (Hosts)") + " "}

          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* DNS Servers Card */}
        <Card>
          <SectionHeader
            title={t("سرورهای DNS هسته")}
            subtitle={t("سرورهایی که Xray برای تفکیک نام دامنه‌ها به آن‌ها مراجعه می‌کند")} />


          <div className="flex flex-wrap gap-2 mb-4">
            <span className="text-xs text-muted self-center ml-2">{t("الگوهای سریع:")}</span>
            {PRESETS.map((p) =>
            <button
              key={p.name}
              type="button"
              className="btn btn-outline btn-sm text-xs"
              onClick={() => handleApplyPreset(p.servers)}>

                {p.name}
              </button>
            )}
          </div>

          <div className="flex gap-2 mb-4">
            <Input
              dir="ltr"
              placeholder={t("مثال: https://1.1.1.1/dns-query یا 1.1.1.1")}
              value={newServer}
              onChange={(e) => setNewServer(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddServer())} />

            <Button type="button" variant="secondary" onClick={handleAddServer} icon={<Plus size={16} />}>{"" + t("افزودن") + " "}

            </Button>
          </div>

          <div className="space-y-2">
            {config.servers.map((srv, idx) =>
            <div
              key={idx}
              className="flex items-center justify-between p-2.5 bg-card-secondary rounded-lg border border-border">

                <div className="flex items-center gap-2">
                  <Globe size={16} className="text-primary" />
                  <span className="font-mono text-sm" dir="ltr">
                    {srv}
                  </span>
                </div>
                <button
                type="button"
                className="text-danger hover:text-danger-hover p-1"
                onClick={() => handleRemoveServer(idx)}
                title={t("حذف سرور")}>

                  <Trash2 size={16} />
                </button>
              </div>
            )}
          </div>
        </Card>

        {/* DNS Options Card */}
        <Card>
          <SectionHeader
            title={t("تنظیمات استراتژی و رفتار DNS")}
            subtitle={t("نحوه حل نام‌ها، استفاده از کش و ارجحیت آدرس‌های آی‌پی")} />


          <div className="space-y-4">
            <Field label={t("استراتژی کوئری (Query Strategy)")} hint={t("ارتباط با آی‌پی‌های نسخه ۴ و ۶")}>
              <Select
                value={config.query_strategy}
                onChange={(e) =>
                saveMutation.mutate({
                  ...config,
                  query_strategy: e.target.value as any
                })
                }>

                <option value="UseIP">{t("UseIP (ترجیح هوشمند / همزمان بر اساس شبکه)")}</option>
                <option value="UseIPv4">{t("UseIPv4 (فقط آدرس‌های IPv4 حل شوند)")}</option>
                <option value="UseIPv6">{t("UseIPv6 (فقط آدرس‌های IPv6 حل شوند)")}</option>
              </Select>
            </Field>

            <Field label={t("کلاینت IP ساختگی (Client IP اختیاری)")} hint={t("برای ارسال به سرورهای DoH جهت بهینه‌سازی مسیر جغرافیایی")}>
              <Input
                dir="ltr"
                placeholder={t("مثال: 1.2.3.4")}
                value={config.client_ip || ""}
                onChange={(e) =>
                saveMutation.mutate({
                  ...config,
                  client_ip: e.target.value.trim() || null
                })
                } />

            </Field>

            <div className="pt-2 border-t border-border space-y-3">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={config.disable_cache}
                  onChange={(e) =>
                  saveMutation.mutate({
                    ...config,
                    disable_cache: e.target.checked
                  })
                  }
                  className="rounded" />

                <div>
                  <span className="font-medium text-sm">{t("غیرفعال‌سازی کش DNS")}</span>
                  <p className="text-xs text-muted">{t("هر درخواست بدون ذخیره در رم مستقیماً مجدداً ارسال شود")}</p>
                </div>
              </label>

              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={config.disable_fallback}
                  onChange={(e) =>
                  saveMutation.mutate({
                    ...config,
                    disable_fallback: e.target.checked
                  })
                  }
                  className="rounded" />

                <div>
                  <span className="font-medium text-sm">{t("غیرفعال‌سازی سرور جایگزین (Fallback)")}</span>
                  <p className="text-xs text-muted">{t("در صورت عدم پاسخ سرور اصلی، کوئری به سایر سرورها فرستاده نشود")}</p>
                </div>
              </label>
            </div>
          </div>
        </Card>
      </div>

      {/* Static Hosts Mapping Card */}
      <Card className="mt-6">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
          <div>
            <h2 className="text-lg font-bold">{t("نگاشت استاتیک هاست‌ها (Static Hosts)")}</h2>
            <p className="text-sm text-muted">{"" + t("مسیردهی یا پاسخ مستقیم به نام دامنه‌ها بدون ارسال کوئری به سرورهای DNS بیرونی") + " "}

            </p>
          </div>
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setHostModalOpen(true)}>{"" + t("افزودن نگاشت جدید") + " "}

          </Button>
        </div>

        <div className="mb-4 max-w-sm">
          <Input
            placeholder={t("جستجو در دامنه‌ها یا IPها...")}
            value={searchHost}
            onChange={(e) => setSearchHost(e.target.value)} />

        </div>

        {filteredHosts.length === 0 ?
        <div className="text-center py-8 text-muted bg-card-secondary rounded-lg border border-border">
            {config.hosts.length === 0 ? t("هنوز هیچ نگاشت هاستی تعریف نشده است. با دکمه بالا اولین نگاشت را بسازید.") : t("نتیجه‌ای برای جستجوی شما یافت نشد.")

          }
          </div> :

        <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted text-right">
                  <th className="pb-3 pr-2">{t("دامنه یا الگو")}</th>
                  <th className="pb-3">{t("آدرس‌های IP متناظر")}</th>
                  <th className="pb-3 pl-2 text-left">{t("عملیات")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredHosts.map((h) =>
              <tr key={h.domain} className="hover:bg-card-secondary/50">
                    <td className="py-3 pr-2 font-mono" dir="ltr">
                      {h.domain}
                    </td>
                    <td className="py-3 font-mono" dir="ltr">
                      <div className="flex flex-wrap gap-1">
                        {h.ips.map((ip, i) =>
                    <span key={i} className="badge badge-secondary text-xs">
                            {ip}
                          </span>
                    )}
                      </div>
                    </td>
                    <td className="py-3 pl-2 text-left">
                      <button
                    type="button"
                    className="text-danger hover:text-danger-hover p-1"
                    onClick={() => deleteHostMutation.mutate(h.domain)}
                    title={t("حذف نگاشت")}>

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

      {/* Modal for adding/editing host */}
      <Modal open={hostModalOpen} onClose={() => setHostModalOpen(false)} title={t("افزودن نگاشت هاست جدید")}>
        <form onSubmit={handleSaveHost} className="space-y-4">
          <Field
            label={t("دامنه یا الگو")}
            hint={t("می‌توانید از نام ساده (example.com) یا پیشوند (domain:example.com) استفاده کنید")}>

            <Input
              dir="ltr"
              placeholder={t("مثال: example.com یا domain:google.com")}
              required
              value={hostDomain}
              onChange={(e) => setHostDomain(e.target.value)} />

          </Field>

          <Field
            label={t("آدرس‌های IP")}
            hint={t("یک یا چند آی‌پی معتبر وارد کنید (با خط جدید یا ویرگول جدا کنید)")}>

            <Input
              dir="ltr"
              placeholder={t("مثال: 93.184.216.34, 93.184.216.35")}
              required
              value={hostIps}
              onChange={(e) => setHostIps(e.target.value)} />

          </Field>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setHostModalOpen(false)}>{"" + t("انصراف") + " "}

            </Button>
            <Button type="submit" loading={addHostMutation.isPending}>{"" + t("ثبت نگاشت") + " "}

            </Button>
          </div>
        </form>
      </Modal>
    </div>);

}
