import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { Button, Card, ConfirmDialog, SectionHeader } from "../components/UI";

type Session = { session_id: string; user_id: number; username: string; client_ip: string; last_seen_at: string };
export default function Sessions() {
  const {admin} = useAuth(), toast = useToast(), cache = useQueryClient();
  const [pending, setPending] = useState<Session | null>(null);
  const canTerminate = !!admin?.permissions.includes("users.write") && !!admin?.permissions.includes("xray.manage");
  const query = useQuery({queryKey: ["online-sessions"], queryFn: () => api.get<Session[]>("/api/monitoring/sessions"), refetchInterval: 5000});
  const state = useQuery({queryKey: ["sessions-source"], queryFn: () => api.get<{available: boolean; targeted_control: boolean}>("/api/monitoring/status"), refetchInterval: 10000});
  const terminate = useMutation({mutationFn: (session: Session) => api.post(`/api/monitoring/sessions/${session.session_id}/terminate`), onSuccess: () => {setPending(null); cache.invalidateQueries({queryKey: ["online-sessions"]}); toast.success("اتصال‌های این کاربر از IP انتخاب‌شده قطع و برای ده دقیقه مسدود شدند.");}, onError: (error: Error) => toast.error(error.message)});
  return <div className="commerce-page"><SectionHeader title="IPهای آنلاین" subtitle="اطلاعات هستهٔ محلی Xray؛ شمارش IP معادل شمارش دستگاه فیزیکی نیست." />
    <Card className="integration-card"><p>داده‌ها حدود هر پنج ثانیه بررسی می‌شوند. چند دستگاه پشت NAT ممکن است یک IP داشته باشند. این صفحه وضعیت نودهای راه دور و WireGuard را نمایش نمی‌دهد.</p>
      {!state.data?.available && <p role="status">اطلاعات تازه از هستهٔ محلی در دسترس نیست.</p>}
      {state.data && !state.data.targeted_control && <p role="status">برای قطع مستقل اتصال‌ها و اعمال سقف IP، هستهٔ مدیریت‌شدهٔ SpecterGate را نصب یا ارتقا دهید.</p>}
      {query.error && <p role="alert">{query.error.message}</p>}
      {query.data?.map(session => <div className="commerce-member" key={session.session_id}><span>{session.username}</span><code dir="ltr">{session.client_ip}</code>{canTerminate && <Button disabled={!state.data?.targeted_control} variant="danger" onClick={() => setPending(session)}>قطع و مسدودسازی موقت</Button>}</div>)}
      {!query.isLoading && !query.data?.length && <p>IP آنلاینی در محدودهٔ دسترسی شما ثبت نشده است.</p>}
    </Card>
    <ConfirmDialog open={!!pending} onClose={() => setPending(null)} title="قطع اتصال و مسدودسازی موقت" message="اتصال‌های همین کاربر از IP انتخاب‌شده بسته و برای ده دقیقه مسدود می‌شوند. پردازش هسته و اتصال سایر کاربران برقرار می‌مانند." confirmLabel="قطع و اعمال" loading={terminate.isPending} onConfirm={() => pending && terminate.mutate(pending)} />
  </div>;
}
