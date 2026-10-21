import { t } from "../lib/i18n";import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, API_BASE } from '../lib/api';
import { useToast } from '../lib/toast';
import { Button, Card, ConfirmDialog, Toggle } from './UI';
const stages: Record<string, string> = { 'checking-signature': t("بررسی امضای انتشار"), 'building': t("آماده‌سازی نسخه"), 'backing-up': t("گرفتن بکاپ رمزگذاری‌شده"), 'installing': t("نصب و راه‌اندازی"), 'complete': t("به‌روزرسانی کامل شد"), 'up-to-date': t("نسخه به‌روز است"), 'no-stable-release': t("انتشار پایدار موجود نیست"), 'failed-preserved-or-rolled-back': t("به‌روزرسانی ناموفق بود؛ گزارش سرویس را بررسی کنید"), 'invalid-request': t("درخواست نامعتبر"), 'missing-release-key': t("کلید تأیید انتشار نصب نیست") };
export default function Updates() {
  const cache = useQueryClient(),toast = useToast(),[confirm, setConfirm] = useState(false);
  const query = useQuery({ queryKey: ['updates'], queryFn: () => api.get<{installed: boolean;current_version: string;automatic: boolean;status: {stage?: string;version?: string;};}>('/api/updates'), refetchInterval: 10000 });
  const backups = useQuery({ queryKey: ['update-backups'], queryFn: () => api.get<{name: string;bytes: number;}[]>('/api/updates/backups'), refetchInterval: 30000 });
  const action = useMutation({ mutationFn: async (auto: boolean | null) => auto === null ? api.post('/api/updates/request', { version: 'latest' }) : api.put('/api/updates', { automatic: auto }), onSuccess: () => {setConfirm(false);cache.invalidateQueries({ queryKey: ['updates'] });toast.success(t("درخواست ثبت شد."));}, onError: (e: Error) => toast.error(e.message) });
  return <Card className="integration-card"><h3>{t("به‌روزرسانی امن پنل")}</h3><p>{"" + t("نسخهٔ فعلی:") + " "}<code>{query.data?.current_version}</code></p><p className="field-hint">{t("فقط انتشار پایدار با امضای معتبر پذیرفته می‌شود. ابتدا رمز بکاپ را تنظیم کنید. نصب نسخه سرویس را ری‌استارت می‌کند و ممکن است اتصال‌ها موقتاً قطع شوند.")}</p>{!query.data?.installed && <p>{t("سرویس به‌روزرسانی مخصوص نصب Linux است؛ در این محیط نصب نشده است.")}</p>}
 <Toggle label={t("بررسی روزانه و نصب خودکار انتشار امضاشده")} checked={!!query.data?.automatic} onChange={(value) => action.mutate(value)} />
 <p role="status">{query.data?.status?.stage ? stages[query.data.status.stage] ?? query.data.status.stage : t("هنوز درخواستی اجرا نشده است.")}</p>
 <Button disabled={!query.data?.installed} loading={action.isPending} onClick={() => setConfirm(true)}>{t("بررسی و نصب آخرین نسخهٔ پایدار")}</Button>
 {backups.data?.map((row) => <p key={row.name}><a className="text-link" href={`${API_BASE}/api/updates/backups/${encodeURIComponent(row.name)}`}>{"" + t("دانلود بکاپ پیش از ارتقا:") + " "}{row.name}</a></p>)}
 <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} title={t("نصب نسخهٔ جدید")} message={t("پس از بررسی امضا و گرفتن بکاپ، نسخهٔ جدید نصب و سرویس ری‌استارت می‌شود. در شکست بررسی یا ساخت، نصب فعلی حفظ می‌شود؛ در شکست راه‌اندازی، بازیابی کد قبلی تلاش می‌شود.")} confirmLabel={t("ثبت درخواست نصب")} loading={action.isPending} onConfirm={() => action.mutate(null)} />
 </Card>;
}
