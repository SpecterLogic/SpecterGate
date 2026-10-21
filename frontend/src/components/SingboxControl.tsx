import AuxiliaryStatus from "./AuxiliaryStatus";
import { t } from "../lib/i18n";import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useToast } from '../lib/toast';
import { Button, Card } from './UI';
export default function SingboxControl() {
  const { admin } = useAuth(),toast = useToast(),cache = useQueryClient();
  const allowed = !!admin?.permissions.includes('xray.manage');
  const query = useQuery({ queryKey: ['singbox-status'], queryFn: () => api.get<{installed: boolean;running: boolean;}>('/api/xray/singbox/status'), enabled: allowed, refetchInterval: 10000 });
  const action = useMutation({ mutationFn: (command: string) => api.post<{message?: string;}>(`/api/xray/singbox/${command}`), onSuccess: (r) => {cache.invalidateQueries({ queryKey: ['singbox-status'] });toast.success(r.message || t("انجام شد."));}, onError: (e: Error) => toast.error(e.message) });
  if (!allowed) return null;
  return <Card><h3>{t("هستهٔ Sing-box")}</h3><p>{query.data?.running ? t("در حال اجرا") : query.data?.installed ? t("نصب شده؛ متوقف") : t("نصب نشده")}</p><p className="field-hint">{t("Hysteria2 و TUIC روی UDP اجرا می‌شوند؛ ShadowTLS خروجی کامل Sing-box می‌خواهد. مصرف و مسیریابی از هستهٔ محلی Xray عبور می‌کند.")}</p><Button loading={action.isPending} onClick={() => action.mutate('apply')}>{t("اعمال و اجرای Sing-box")}</Button> <Button variant="danger" loading={action.isPending} onClick={() => action.mutate('stop')}>{t("توقف Sing-box")}</Button><AuxiliaryStatus /></Card>;
}
