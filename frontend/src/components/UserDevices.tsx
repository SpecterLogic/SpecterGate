import { t } from "../lib/i18n";import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { Button } from './UI';
import { useToast } from '../lib/toast';

export default function UserDevices({ userId }: {userId: number;}) {
  const cache = useQueryClient(),toast = useToast();
  const query = useQuery({ queryKey: ['user-devices', userId], queryFn: () => api.get<{id: number;label: string;last_seen_at: string;}[]>(`/api/users/${userId}/devices`) });
  const remove = useMutation({ mutationFn: (id: number) => api.delete(`/api/users/${userId}/devices/${id}`), onSuccess: () => cache.invalidateQueries({ queryKey: ['user-devices', userId] }), onError: (e: Error) => toast.error(e.message) });
  return <div className="field-span-2"><h4>{t("دستگاه‌های ثبت‌شده با HWID")}</h4>{query.error && <p role="alert">{query.error.message}</p>}{query.data?.map((row) => <div className="commerce-member" key={row.id}><span>{row.label}</span><Button type="button" variant="danger" loading={remove.isPending} onClick={() => remove.mutate(row.id)}>{t("آزاد کردن جای دستگاه")}</Button></div>)}{!query.data?.length && <p className="field-hint">{t("هنوز دستگاهی ثبت نشده است. حذف دستگاه، کانفیگ قبلاً دریافت‌شده را باطل نمی‌کند؛ برای ابطال از چرخش UUID استفاده کنید.")}</p>}</div>;
}
