import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { ShieldCheck } from "lucide-react";
import { Badge, Button, Card, Field, Input, Modal, SectionHeader } from "./UI";

export default function TwoFactorSettings() {
  const { admin } = useAuth();
  const toast = useToast();
  const [setupData, setSetupData] = useState<{ secret: string; uri: string; qr_svg: string; recovery_codes: string[] } | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [disable2FaOpen, setDisable2FaOpen] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");

  const setup2FaMutation = useMutation({
    mutationFn: () => api.post<{ secret: string; uri: string; qr_svg: string; recovery_codes: string[] }>("/api/auth/2fa/setup"),
    onSuccess: (data) => {
      setSetupData(data);
      setConfirmCode("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const enable2FaMutation = useMutation({
    mutationFn: () =>
      api.post("/api/auth/2fa/enable", {
        secret: setupData?.secret,
        code: confirmCode.trim(),
        recovery_codes: setupData?.recovery_codes || [],
      }),
    onSuccess: () => {
      toast.success("احراز هویت دومرحله‌ای با موفقیت فعال شد.");
      setSetupData(null);
      setConfirmCode("");
      window.location.reload();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const disable2FaMutation = useMutation({
    mutationFn: () => api.post("/api/auth/2fa/disable", { password: disablePassword }),
    onSuccess: () => {
      toast.success("احراز هویت دومرحله‌ای غیرفعال شد.");
      setDisable2FaOpen(false);
      setDisablePassword("");
      window.location.reload();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return <>
        {/* Two-Factor Authentication (2FA) */}
    <Card className="integration-card">
      <SectionHeader
        title="احراز هویت دومرحله‌ای (2FA / TOTP)"
        subtitle="امنیت حساب مدیریت با کدهای متغیر ۶ رقمی نرم‌افزارهای Authenticator."
        action={<Badge tone={admin?.totp_enabled ? "success" : "neutral"}>{admin?.totp_enabled ? "فعال" : "غیرفعال"}</Badge>}
      />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0" }}>
        <div>
          <p style={{ margin: "0 0 4px", fontWeight: 500 }}>
            {admin?.totp_enabled
              ? "ورود دومرحله‌ای برای این حساب فعال است. هنگام ورود، کد تأیید ۶ رقمی الزامی خواهد بود."
              : "ورود دومرحله‌ای هنوز فعال نشده است. فعال‌سازی آن امنیت پنل شما را ارتقا می‌دهد."}
          </p>
          <small className="field-hint">سازگار با Google Authenticator، Bitwarden، Aegis، و تمام برنامه‌های TOTP.</small>
        </div>
        <div>
          {admin?.totp_enabled ? (
            <Button variant="danger" size="sm" onClick={() => setDisable2FaOpen(true)}>
              غیرفعال‌سازی 2FA
            </Button>
          ) : (
            <Button variant="primary" size="sm" icon={<ShieldCheck size={15} />} loading={setup2FaMutation.isPending} onClick={() => setup2FaMutation.mutate()}>
              راه‌اندازی و فعال‌سازی 2FA
            </Button>
          )}
        </div>
      </div>
    </Card>

    {/* 2FA Setup Modal */}
    <Modal
      open={setupData !== null}
      onClose={() => setSetupData(null)}
      title="فعال‌سازی احراز هویت دومرحله‌ای"
      description="بارکد زیر را با نرم‌افزار Authenticator خود اسکن کرده و کد ۶ رقمی را وارد کنید."
      footer={
        <>
          <Button variant="ghost" onClick={() => setSetupData(null)}>انصراف</Button>
          <Button loading={enable2FaMutation.isPending} disabled={!confirmCode.trim()} onClick={() => enable2FaMutation.mutate()}>
            تأیید و فعال‌سازی
          </Button>
        </>
      }
    >
      {setupData && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px", alignItems: "center" }}>
          <div
            style={{ width: "200px", height: "200px", background: "white", padding: "8px", borderRadius: "8px" }}
            dangerouslySetInnerHTML={{ __html: setupData.qr_svg }}
          />
          <div style={{ width: "100%", textAlign: "center" }}>
            <span className="field-hint" style={{ display: "block", marginBottom: "4px" }}>کلید متنی (در صورت عدم امکان اسکن):</span>
            <code dir="ltr" style={{ fontSize: "14px", fontWeight: "bold", padding: "4px 8px", background: "#374151", borderRadius: "4px" }}>
              {setupData.secret}
            </code>
          </div>
          <div style={{ width: "100%", background: "#1f2937", padding: "12px", borderRadius: "8px" }}>
            <strong style={{ fontSize: "12px", display: "block", marginBottom: "6px" }}>کدهای پشتیبان یک‌بار مصرف (این کدها را یادداشت کنید):</strong>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
              {setupData.recovery_codes.map((code) => (
                <code key={code} dir="ltr" style={{ fontSize: "12px", background: "#111827", padding: "2px 6px", borderRadius: "3px" }}>
                  {code}
                </code>
              ))}
            </div>
          </div>
          <div style={{ width: "100%" }}>
            <Field label="کد ۶ رقمی نرم‌افزار Authenticator">
              <Input
                value={confirmCode}
                onChange={(e) => setConfirmCode(e.target.value)}
                placeholder="۱۲۳۴۵۶"
                dir="ltr"
                autoFocus
              />
            </Field>
          </div>
        </div>
      )}
    </Modal>

    {/* 2FA Disable Modal */}
    <Modal
      open={disable2FaOpen}
      onClose={() => setDisable2FaOpen(false)}
      title="غیرفعال‌سازی ورود دومرحله‌ای"
      description="برای غیرفعال‌سازی، لطفاً رمز عبور حساب خود را تأیید کنید."
      footer={
        <>
          <Button variant="ghost" onClick={() => setDisable2FaOpen(false)}>انصراف</Button>
          <Button variant="danger" loading={disable2FaMutation.isPending} disabled={!disablePassword} onClick={() => disable2FaMutation.mutate()}>
            غیرفعال‌سازی
          </Button>
        </>
      }
    >
      <Field label="رمز عبور فعلی">
        <Input
          type="password"
          value={disablePassword}
          onChange={(e) => setDisablePassword(e.target.value)}
          placeholder="رمز عبور فعلی را وارد کنید"
          dir="ltr"
          autoFocus
        />
      </Field>
    </Modal>

  </>;
}
