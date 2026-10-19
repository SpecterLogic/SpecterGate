import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Field, Select, Spinner } from "./UI";

export interface ResourcePolicy {
  allowed_inbound_ids: number[] | null;
  allowed_dns_tunnel_ids: number[] | null;
}
interface Option { id: number; name: string; tag?: string; protocol?: string; domain?: string; is_active: boolean }

export default function ResourceAccessPicker({ value, onChange }: { value: ResourcePolicy; onChange: (next: ResourcePolicy) => void }) {
  const options = useQuery({ queryKey: ["resource-options"], queryFn: () => api.get<{ inbounds: Option[]; dns_tunnels: Option[] }>("/api/users/access-options") });
  if (options.isLoading) return <Spinner label="دریافت کانفیگ‌ها و تونل‌ها..." />;
  if (options.error) return <p role="alert">{options.error.message}</p>;
  return <fieldset className="resource-access"><legend>دسترسی به کانفیگ‌ها و تونل‌ها</legend><p>دسترسی نهایی، اشتراک مجوزهای ادمین، گروه و کاربر است. انتخاب کاربر محدودیت گروه را باز نمی‌کند.</p>
    {([['allowed_inbound_ids', 'کانفیگ‌های مجاز', options.data?.inbounds ?? []], ['allowed_dns_tunnel_ids', 'تونل‌های DNS مجاز', options.data?.dns_tunnels ?? []]] as const).map(([key, label, items]) => <div key={key}>
      <Field label={label}><Select value={value[key] === null ? 'inherit' : 'selected'} onChange={e => onChange({ ...value, [key]: e.target.value === 'inherit' ? null : [] })}><option value="inherit">همه موارد مجاز در سطح بالادست</option><option value="selected">فقط موارد انتخابی (بدون انتخاب = عدم دسترسی)</option></Select></Field>
      {value[key] !== null && <div className="resource-options">{items.map(item => <label key={item.id}><input type="checkbox" checked={value[key]?.includes(item.id) ?? false} onChange={e => onChange({ ...value, [key]: e.target.checked ? [...(value[key] ?? []), item.id] : value[key]?.filter(id => id !== item.id) ?? [] })} /><span>{item.name} <small>{item.protocol ?? item.domain} {item.is_active ? '' : '· غیرفعال'}</small></span></label>)}{!items.length && <p>موردی موجود نیست. ابتدا کانفیگ یا تونل بسازید.</p>}</div>}
    </div>)}
  </fieldset>;
}
