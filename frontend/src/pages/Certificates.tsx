import { t, tt } from "../lib/i18n";import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, ShieldCheck, Copy, Check, RefreshCw, KeyRound, ExternalLink } from "lucide-react";
import { api } from "../lib/api";
import { Button, Card, Field, Input, Modal, SectionHeader, Textarea } from "../components/UI";
import { useToast } from "../lib/toast";

interface SslCert {
  id: number;
  domain: string;
  issuer: string;
  cert_path: string;
  key_path: string;
  issued_at: string;
  expires_at: string | null;
  auto_renew: boolean;
  is_active: boolean;
  days_remaining: number | null;
}

export function Certificates() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  // Modals
  const [issueModalOpen, setIssueModalOpen] = useState(false);
  const [issueDomain, setIssueDomain] = useState("");
  const [issueEmail, setIssueEmail] = useState("");

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadDomain, setUploadDomain] = useState("");
  const [uploadCertPem, setUploadCertPem] = useState("");
  const [uploadKeyPem, setUploadKeyPem] = useState("");

  const { data: certs = [], isLoading } = useQuery<SslCert[]>({
    queryKey: ["ssl-certificates"],
    queryFn: () => api.get<SslCert[]>("/api/certificates")
  });

  const issueMutation = useMutation({
    mutationFn: (data: {domain: string;email?: string;}) => api.post<SslCert>("/api/certificates/issue", data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["ssl-certificates"] });
      setIssueModalOpen(false);
      setIssueDomain("");
      setIssueEmail("");
      toast.success(tt("گواهی SSL برای {0} با موفقیت صادر شد.", [res.domain]));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در صدور گواهی Let's Encrypt"));
    }
  });

  const uploadMutation = useMutation({
    mutationFn: (data: {domain: string;cert_pem: string;key_pem: string;}) =>
    api.post<SslCert>("/api/certificates/upload", data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["ssl-certificates"] });
      setUploadModalOpen(false);
      setUploadDomain("");
      setUploadCertPem("");
      setUploadKeyPem("");
      toast.success(tt("گواهی SSL برای {0} با موفقیت بارگذاری شد.", [res.domain]));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در بارگذاری گواهی دستی"));
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/certificates/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssl-certificates"] });
      toast.success(t("گواهی با موفقیت حذف شد."));
    },
    onError: (err: any) => {
      toast.error(err?.message || t("خطا در حذف گواهی"));
    }
  });

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPath(text);
    toast.success(t("مسیر در کلیپ‌بورد کپی شد."));
    setTimeout(() => setCopiedPath(null), 2500);
  };

  if (isLoading) {
    return <div className="page-loading">{t("در حال بارگذاری گواهی‌های SSL...")}</div>;
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("مدیریت گواهی‌های SSL")}</h1>
          <p className="page-subtitle">{"" + t("صدور خودکار گواهی Let's Encrypt، بارگذاری کلید و زنجیرهٔ دستی و استفاده مستقیم در اینباندهای TLS") + " "}

          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={<KeyRound size={16} />} onClick={() => setUploadModalOpen(true)}>{"" + t("بارگذاری دستی گواهی") + " "}

          </Button>
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setIssueModalOpen(true)}>{"" + t("صدور خودکار Let's Encrypt") + " "}

          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {certs.length === 0 ?
        <Card className="text-center py-12">
            <ShieldCheck size={48} className="mx-auto text-muted mb-3" />
            <h3 className="text-base font-bold mb-1">{t("هنوز هیچ گواهی SSL ثبت نشده است")}</h3>
            <p className="text-sm text-muted mb-4">{"" + t("می‌توانید برای دامنه‌های متصل به سرور به‌صورت خودکار گواهی Let's Encrypt بگیرید یا کلیدهای خود را بارگذاری کنید.") + " "}

          </p>
            <div className="flex justify-center gap-2">
              <Button variant="outline" onClick={() => setUploadModalOpen(true)}>{"" + t("بارگذاری دستی") + " "}

            </Button>
              <Button variant="primary" onClick={() => setIssueModalOpen(true)}>{"" + t("صدور خودکار Let's Encrypt") + " "}

            </Button>
            </div>
          </Card> :

        certs.map((c) => {
          const isNearExpiry = c.days_remaining !== null && c.days_remaining <= 14;
          const isExpired = c.days_remaining !== null && c.days_remaining <= 0;

          return (
            <Card key={c.id} className="integration-card">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                  <div className="flex items-center gap-3">
                    <div className="p-3 bg-primary/10 text-primary rounded-xl">
                      <ShieldCheck size={24} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-base font-bold" dir="ltr">
                          {c.domain}
                        </span>
                        <span className="badge badge-secondary text-xs">{c.issuer}</span>
                        {isExpired ?
                      <span className="badge badge-danger text-xs">{t("منقضی شده")}</span> :
                      isNearExpiry ?
                      <span className="badge badge-warning text-xs">{t("نزدیک به انقضا (")}
                        {c.days_remaining}{" " + t("روز مانده)") + " "}
                      </span> :

                      <span className="badge badge-success text-xs">{t("معتبر (")}
                        {c.days_remaining}{" " + t("روز مانده)") + " "}
                      </span>
                      }
                      </div>
                      <p className="text-xs text-muted mt-1">{"" + t("صادرکننده:") + " "}
                      {c.issuer}{" " + t("· وضعیت تمدید خودکار:") + " "}{c.auto_renew ? t("فعال") : t("غیرفعال")}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 self-end md:self-auto">
                    <Button
                    variant="ghost"
                    className="text-danger"
                    onClick={() => deleteMutation.mutate(c.id)}
                    icon={<Trash2 size={16} />}
                    title={t("حذف گواهی")}>{"" + t("حذف") + " "}


                  </Button>
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-border grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono">
                  <div className="flex items-center justify-between p-2.5 bg-card-secondary rounded-lg">
                    <div className="truncate mr-2" dir="ltr">
                      <span className="text-muted block text-[10px]">{t("فایل گواهی (Fullchain):")}</span>
                      {c.cert_path}
                    </div>
                    <button
                    type="button"
                    className="p-1 hover:text-primary"
                    onClick={() => handleCopy(c.cert_path)}
                    title={t("کپی مسیر")}>

                      {copiedPath === c.cert_path ? <Check size={14} className="text-success" /> : <Copy size={14} />}
                    </button>
                  </div>

                  <div className="flex items-center justify-between p-2.5 bg-card-secondary rounded-lg">
                    <div className="truncate mr-2" dir="ltr">
                      <span className="text-muted block text-[10px]">{t("فایل کلید خصوصی (Private Key):")}</span>
                      {c.key_path}
                    </div>
                    <button
                    type="button"
                    className="p-1 hover:text-primary"
                    onClick={() => handleCopy(c.key_path)}
                    title={t("کپی مسیر")}>

                      {copiedPath === c.key_path ? <Check size={14} className="text-success" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>
              </Card>);

        })
        }
      </div>

      {/* Modal for Auto Issue */}
      <Modal open={issueModalOpen} onClose={() => setIssueModalOpen(false)} title={t("صدور خودکار گواهی Let's Encrypt")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!issueDomain.trim()) return;
            issueMutation.mutate({ domain: issueDomain.trim(), email: issueEmail.trim() || undefined });
          }}
          className="space-y-4">

          <Field
            label={t("نام دامنه")}
            hint={t("دامنه‌ای که رکوردهای DNS آن به این سرور هدایت شده و پورت ۸۰ آن باز است")}>

            <Input
              dir="ltr"
              placeholder={t("مثال: vpn.example.com")}
              required
              value={issueDomain}
              onChange={(e) => setIssueDomain(e.target.value)} />

          </Field>

          <Field label={t("آدرس ایمیل (اختیاری)")} hint={t("برای دریافت هشدارهای انقضا از Let's Encrypt")}>
            <Input
              dir="ltr"
              type="email"
              placeholder="admin@example.com"
              value={issueEmail}
              onChange={(e) => setIssueEmail(e.target.value)} />

          </Field>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setIssueModalOpen(false)}>{"" + t("انصراف") + " "}

            </Button>
            <Button type="submit" loading={issueMutation.isPending}>{"" + t("دریافت گواهی") + " "}

            </Button>
          </div>
        </form>
      </Modal>

      {/* Modal for Manual Upload */}
      <Modal open={uploadModalOpen} onClose={() => setUploadModalOpen(false)} title={t("بارگذاری دستی گواهی و کلید")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!uploadDomain.trim() || !uploadCertPem.trim() || !uploadKeyPem.trim()) {
              toast.error(t("تکمیل تمام فیلدها الزامی است."));
              return;
            }
            uploadMutation.mutate({
              domain: uploadDomain.trim(),
              cert_pem: uploadCertPem.trim(),
              key_pem: uploadKeyPem.trim()
            });
          }}
          className="space-y-4">

          <Field label={t("نام دامنه")}>
            <Input
              dir="ltr"
              placeholder={t("مثال: panel.example.com")}
              required
              value={uploadDomain}
              onChange={(e) => setUploadDomain(e.target.value)} />

          </Field>

          <Field label={t("زنجیره گواهی (Fullchain CRT/PEM)")} hint={t("محتوای متنی شامل -----BEGIN CERTIFICATE-----")}>
            <Textarea
              dir="ltr"
              rows={4}
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
              required
              value={uploadCertPem}
              onChange={(e) => setUploadCertPem(e.target.value)} />

          </Field>

          <Field label={t("کلید خصوصی (Private Key PEM)")} hint={t("محتوای متنی شامل -----BEGIN PRIVATE KEY-----")}>
            <Textarea
              dir="ltr"
              rows={4}
              placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...&#10;-----END RSA PRIVATE KEY-----"
              required
              value={uploadKeyPem}
              onChange={(e) => setUploadKeyPem(e.target.value)} />

          </Field>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setUploadModalOpen(false)}>{"" + t("انصراف") + " "}

            </Button>
            <Button type="submit" loading={uploadMutation.isPending}>{"" + t("ذخیره گواهی") + " "}

            </Button>
          </div>
        </form>
      </Modal>
    </div>);

}
