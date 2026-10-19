import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  CalendarClock,
  Copy,
  Link2Off,
  MoreHorizontal,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users as UsersIcon,
} from "lucide-react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import type { OperationResult, PanelSettings, UserPage, UserStatus, VPNUser, Plan, SubscriptionInfo } from "../lib/types";
import { useAuth } from "../lib/auth";
import ResourceAccessPicker, { type ResourcePolicy } from "../components/ResourceAccessPicker";
import {
  cn,
  formatBytes,
  formatDate,
  formatDateTime,
  formatNumber,
  fromDateTimeLocal,
  statusLabel,
  toDateTimeLocal,
} from "../lib/format";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Modal,
  Progress,
  Select,
  Spinner,
  StatusBadge,
  Textarea,
  Toggle,
} from "../components/UI";

interface UserForm extends ResourcePolicy {
  username: string;
  email: string;
  note: string;
  dataLimitGb: string;
  expireAtLocal: string;
  deviceLimit: string;
  isActive: boolean;
  planId: string;
}

type PendingAction = { kind: "delete" | "reset" | "revoke" | "rotate"; user: VPNUser } | null;

const STATUS_TABS: { value: "" | UserStatus; label: string }[] = [
  { value: "", label: "همه" },
  { value: "active", label: "فعال" },
  { value: "limited", label: "اتمام حجم" },
  { value: "expired", label: "منقضی" },
  { value: "disabled", label: "غیرفعال" },
];

function defaultExpiry(days: number): string {
  if (!days) return "";
  const date = new Date();
  date.setDate(date.getDate() + days);
  return toDateTimeLocal(date.toISOString());
}

function emptyForm(settings?: PanelSettings): UserForm {
  return {
    username: "",
    email: "",
    note: "",
    dataLimitGb: String(settings?.default_data_limit_gb || 0),
    expireAtLocal: defaultExpiry(settings?.default_expiry_days ?? 30),
    deviceLimit: "",
    isActive: true,
    planId: "",
    allowed_inbound_ids: null,
    allowed_dns_tunnel_ids: null,
  };
}

function userToForm(user: VPNUser): UserForm {
  return {
    username: user.username,
    email: user.email ?? "",
    note: user.note ?? "",
    dataLimitGb: user.data_limit_bytes ? String(Math.round((user.data_limit_bytes / 1024 ** 3) * 100) / 100) : "0",
    expireAtLocal: toDateTimeLocal(user.expire_at),
    deviceLimit: user.device_limit ? String(user.device_limit) : "",
    isActive: user.is_active,
    planId: "",
    allowed_inbound_ids: user.allowed_inbound_ids ?? null,
    allowed_dns_tunnel_ids: user.allowed_dns_tunnel_ids ?? null,
  };
}

export default function UsersPage() {
  const { admin } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [status, setStatus] = useState<"" | UserStatus>("");
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<VPNUser | null>(null);
  const [form, setForm] = useState<UserForm>(emptyForm());
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState<PendingAction>(null);

  const settings = useQuery({
    queryKey: ["panel-settings"],
    queryFn: () => api.get<PanelSettings>("/api/settings"),
    enabled: !!admin?.permissions.includes("settings.read"),
  });
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.get<Plan[]>("/api/plans"), enabled: !!admin?.permissions.includes("plans.read") });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      openCreate();
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const users = useQuery({
    queryKey: ["users", page, debouncedSearch, status],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), size: "12" });
      if (debouncedSearch) params.set("search", debouncedSearch);
      if (status) params.set("status", status);
      return api.get<UserPage>(`/api/users?${params.toString()}`);
    },
    placeholderData: (previous) => previous,
  });

  const totalPages = Math.max(1, Math.ceil((users.data?.total ?? 0) / 12));

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["users"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }

  const saveMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (editing) return api.patch<VPNUser>(`/api/users/${editing.id}`, payload);
      return api.post<VPNUser>("/api/users", payload);
    },
    onSuccess: (user) => {
      toast.success(editing ? "تغییرات کاربر ذخیره شد." : `کاربر ${user.username} ساخته شد.`);
      setModalOpen(false);
      setEditing(null);
      setFormError("");
      invalidate();
    },
    onError: (error: Error) => setFormError(error.message),
  });

  const actionMutation = useMutation({
    mutationFn: async (action: PendingAction) => {
      if (!action) throw new Error("عملیات نامعتبر است.");
      const { kind, user } = action;
      if (kind === "delete") return api.delete<OperationResult>(`/api/users/${user.id}`);
      if (kind === "reset") return api.post<VPNUser>(`/api/users/${user.id}/reset-traffic`);
      if (kind === "revoke") return api.post<VPNUser>(`/api/users/${user.id}/revoke-subscription`);
      return api.post<VPNUser>(`/api/users/${user.id}/rotate-uuid`);
    },
    onSuccess: (_result, action) => {
      const messages = {
        delete: "کاربر حذف شد.",
        reset: "مصرف کاربر صفر شد.",
        revoke: "لینک اشتراک ابطال و لینک جدید ساخته شد.",
        rotate: "UUID و رمز کاربر چرخش کرد.",
      };
      toast.success(messages[action?.kind ?? "delete"]);
      setPending(null);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const toggleMutation = useMutation({
    mutationFn: (user: VPNUser) => api.patch<VPNUser>(`/api/users/${user.id}`, { is_active: !user.is_active }),
    onSuccess: (user) => {
      toast.success(user.is_active ? "کاربر فعال شد." : "کاربر غیرفعال شد.");
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const subscriptionBase = useMemo(() => {
    const configured = settings.data?.subscription_base_url?.trim();
    return (configured || window.location.origin).replace(/\/$/, "");
  }, [settings.data]);

  function subscriptionUrl(user: VPNUser) {
    return `${subscriptionBase}${user.subscription_path}`;
  }

  async function copySubscription(user: VPNUser) {
    try {
      const info = await api.get<SubscriptionInfo>(`/sub/${user.sub_token}/info`);
      await navigator.clipboard.writeText(info.subscription_url);
      toast.success("لینک اشتراک کپی شد.");
    } catch {
      toast.error("مرورگر اجازهٔ دسترسی به کلیپ‌بورد نداد.");
    }
  }

  function openCreate() {
    setEditing(null);
    setForm(emptyForm(settings.data));
    setFormError("");
    setModalOpen(true);
  }

  function openEdit(user: VPNUser) {
    setEditing(user);
    setForm(userToForm(user));
    setFormError("");
    setModalOpen(true);
  }

  function submitForm(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (form.username.trim().length < 3) {
      setFormError("نام کاربری باید حداقل ۳ کاراکتر باشد.");
      return;
    }
    const limitValue = Number(form.dataLimitGb);
    const payload: Record<string, unknown> = {
      username: form.username.trim(),
      email: form.email.trim() || null,
      note: form.note.trim() || null,
      data_limit_bytes: limitValue > 0 ? Math.round(limitValue * 1024 ** 3) : null,
      expire_at: fromDateTimeLocal(form.expireAtLocal),
      device_limit: form.deviceLimit ? Number(form.deviceLimit) : null,
      is_active: form.isActive,
      allowed_inbound_ids: form.allowed_inbound_ids,
      allowed_dns_tunnel_ids: form.allowed_dns_tunnel_ids,
    };
    if (form.planId) {
      payload.plan_id = Number(form.planId);
      if (!editing) { delete payload.data_limit_bytes; delete payload.expire_at; delete payload.device_limit; }
    }
    saveMutation.mutate(payload);
  }

  function applyExpiry(days: number) {
    setForm((current) => ({ ...current, expireAtLocal: defaultExpiry(days) }));
  }

  function confirmText(action: PendingAction) {
    if (!action) return "";
    switch (action.kind) {
      case "delete":
        return `کاربر «${action.user.username}» و تمام سوابق مصرف او حذف می‌شود. این عملیات بازگشت‌پذیر نیست.`;
      case "reset":
        return `مصرف ثبت‌شده برای «${action.user.username}» صفر می‌شود. سوابق نمودار نیز پاک خواهد شد.`;
      case "revoke":
        return `لینک اشتراک فعلی «${action.user.username}» باطل و لینک جدیدی ساخته می‌شود.`;
      case "rotate":
        return `UUID و رمز اتصال «${action.user.username}» تغییر می‌کند و کلاینت‌های فعلی قطع می‌شوند.`;
    }
  }

  const actionTitles: Record<string, string> = {
    delete: "حذف کاربر",
    reset: "ریست مصرف",
    revoke: "ابطال لینک اشتراک",
    rotate: "چرخش UUID",
  };

  return (
    <div className="users-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">مدیریت دسترسی</p>
          <h2>کاربران و اشتراک‌ها</h2>
          <p className="page-subtitle">ساخت، ویرایش و کنترل مصرف کاربران؛ همه از یک‌جا.</p>
        </div>
        <div className="page-actions">
          <Button variant="outline" icon={<RefreshCw size={16} />} onClick={() => users.refetch()} loading={users.isFetching}>
            به‌روزرسانی
          </Button>
          <Button icon={<UserPlus size={17} />} onClick={openCreate}>
            کاربر جدید
          </Button>
        </div>
      </div>

      <Card className="toolbar-card">
        <div className="toolbar-row">
          <div className="search-box">
            <Search size={17} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="جست‌وجوی نام کاربری، ایمیل یا یادداشت..."
            />
          </div>
          <div className="toolbar-meta">
            <Badge tone="neutral">
              <UsersIcon size={13} /> {formatNumber(users.data?.total ?? 0)} کاربر
            </Badge>
            <span className="toolbar-divider" />
            <span className="toolbar-hint">صفحه {formatNumber(page)} از {formatNumber(totalPages)}</span>
          </div>
        </div>
        <div className="status-tabs">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              className={cn("status-tab", status === tab.value && "active")}
              onClick={() => {
                setStatus(tab.value);
                setPage(1);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </Card>

      <Card className="table-card">
        {users.isLoading ? (
          <Spinner />
        ) : users.isError ? (
          <EmptyState
            icon={<UsersIcon size={24} />}
            title="دریافت کاربران ناموفق بود"
            description={(users.error as Error).message}
            action={<Button onClick={() => users.refetch()}>تلاش دوباره</Button>}
          />
        ) : (users.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            icon={<UserPlus size={24} />}
            title={debouncedSearch || status ? "کاربری پیدا نشد" : "هنوز کاربری نساخته‌اید"}
            description={
              debouncedSearch || status
                ? "فیلترها یا عبارت جست‌وجو را تغییر دهید."
                : "اولین کاربر را بسازید تا لینک اشتراک چندپروتکلی برایش تولید شود."
            }
            action={
              debouncedSearch || status ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setSearch("");
                    setStatus("");
                  }}
                >
                  پاک کردن فیلترها
                </Button>
              ) : (
                <Button icon={<Plus size={16} />} onClick={openCreate}>
                  ساخت کاربر
                </Button>
              )
            }
          />
        ) : (
          <>
            <div className="table-wrap desktop-only">
              <table className="data-table users-table">
                <thead>
                  <tr>
                    <th>کاربر</th>
                    <th>وضعیت</th>
                    <th>مصرف داده</th>
                    <th>انقضا</th>
                    <th>دستگاه</th>
                    <th className="align-end">عملیات</th>
                  </tr>
                </thead>
                <tbody>
                  {users.data?.items.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <div className="identity-cell">
                          <span className={cn("identity-avatar", `avatar-${user.status}`)}>
                            {user.username.slice(0, 2).toUpperCase()}
                          </span>
                          <div>
                            <strong>{user.username}</strong>
                            <span dir="ltr">{user.email || "—"}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={user.status} />
                      </td>
                      <td>
                        <div className="usage-cell">
                          <div className="usage-text">
                            <span>{formatBytes(user.used_traffic_bytes)}</span>
                            <small>{user.data_limit_bytes ? `/ ${formatBytes(user.data_limit_bytes)}` : "نامحدود"}</small>
                          </div>
                          {user.data_limit_bytes ? (
                            <Progress
                              value={user.usage_percent}
                              tone={user.usage_percent >= 90 ? "danger" : user.usage_percent >= 70 ? "warning" : "accent"}
                            />
                          ) : (
                            <div className="usage-unlimited">بدون سقف حجم</div>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="date-cell">
                          <span>{formatDate(user.expire_at)}</span>
                          <small>{user.expire_at ? formatDateTime(user.expire_at).split("،").slice(-1) : "همیشگی"}</small>
                        </div>
                      </td>
                      <td>
                        <span className="device-count">
                          {user.device_limit ? `${formatNumber(user.device_limit)} دستگاه` : "∞"}
                        </span>
                      </td>
                      <td>
                        <div className="row-actions">
                          <button
                            type="button"
                            className="icon-btn"
                            title="کپی لینک اشتراک"
                            onClick={() => copySubscription(user)}
                          >
                            <Copy size={16} />
                          </button>
                          <button type="button" className="icon-btn" title="ویرایش" onClick={() => openEdit(user)}>
                            <Pencil size={16} />
                          </button>
                          <details className="action-menu">
                            <summary className="icon-btn" title="عملیات بیشتر">
                              <MoreHorizontal size={18} />
                            </summary>
                            <div className="action-menu-pop">
                              <button type="button" onClick={() => toggleMutation.mutate(user)}>
                                <Power size={15} />
                                {user.is_active ? "غیرفعال کردن" : "فعال کردن"}
                              </button>
                              <button type="button" onClick={() => setPending({ kind: "reset", user })}>
                                <RotateCcw size={15} />
                                ریست مصرف
                              </button>
                              <button type="button" onClick={() => setPending({ kind: "revoke", user })}>
                                <Link2Off size={15} />
                                ابطال لینک اشتراک
                              </button>
                              <button type="button" onClick={() => setPending({ kind: "rotate", user })}>
                                <ShieldCheck size={15} />
                                چرخش UUID
                              </button>
                              <span className="action-sep" />
                              <button type="button" className="danger" onClick={() => setPending({ kind: "delete", user })}>
                                <Trash2 size={15} />
                                حذف کاربر
                              </button>
                            </div>
                          </details>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mobile-user-list">
              {users.data?.items.map((user) => (
                <div className="mobile-user-card" key={user.id}>
                  <div className="mobile-user-head">
                    <div className="identity-cell">
                      <span className={cn("identity-avatar", `avatar-${user.status}`)}>
                        {user.username.slice(0, 2).toUpperCase()}
                      </span>
                      <div>
                        <strong>{user.username}</strong>
                        <span dir="ltr">{user.email || "—"}</span>
                      </div>
                    </div>
                    <StatusBadge status={user.status} />
                  </div>
                  <div className="mobile-user-usage">
                    <div className="usage-text">
                      <span>{formatBytes(user.used_traffic_bytes)}</span>
                      <small>{user.data_limit_bytes ? `/ ${formatBytes(user.data_limit_bytes)}` : "نامحدود"}</small>
                    </div>
                    {user.data_limit_bytes ? (
                      <Progress
                        value={user.usage_percent}
                        tone={user.usage_percent >= 90 ? "danger" : user.usage_percent >= 70 ? "warning" : "accent"}
                      />
                    ) : (
                      <div className="usage-unlimited">بدون سقف حجم</div>
                    )}
                  </div>
                  <div className="mobile-user-meta">
                    <span>
                      انقضا: <strong>{formatDate(user.expire_at)}</strong>
                    </span>
                    <span>
                      دستگاه: <strong>{user.device_limit ? formatNumber(user.device_limit) : "∞"}</strong>
                    </span>
                  </div>
                  <div className="mobile-user-actions">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Copy size={15} />}
                      onClick={() => copySubscription(user)}
                    >
                      لینک
                    </Button>
                    <Button size="sm" variant="ghost" icon={<Pencil size={15} />} onClick={() => openEdit(user)}>
                      ویرایش
                    </Button>
                    <details className="action-menu mobile-action-menu">
                      <summary className="icon-btn" title="عملیات بیشتر">
                        <MoreHorizontal size={18} />
                      </summary>
                      <div className="action-menu-pop">
                        <button type="button" onClick={() => toggleMutation.mutate(user)}>
                          <Power size={15} />
                          {user.is_active ? "غیرفعال کردن" : "فعال کردن"}
                        </button>
                        <button type="button" onClick={() => setPending({ kind: "reset", user })}>
                          <RotateCcw size={15} />
                          ریست مصرف
                        </button>
                        <button type="button" onClick={() => setPending({ kind: "revoke", user })}>
                          <Link2Off size={15} />
                          ابطال لینک اشتراک
                        </button>
                        <button type="button" onClick={() => setPending({ kind: "rotate", user })}>
                          <ShieldCheck size={15} />
                          چرخش UUID
                        </button>
                        <span className="action-sep" />
                        <button type="button" className="danger" onClick={() => setPending({ kind: "delete", user })}>
                          <Trash2 size={15} />
                          حذف کاربر
                        </button>
                      </div>
                    </details>
                  </div>
                </div>
              ))}
            </div>

            <div className="pagination">
              <Button
                variant="ghost"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                قبلی
              </Button>
              <span>
                صفحه {formatNumber(page)} از {formatNumber(totalPages)}
              </span>
              <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>
                بعدی
              </Button>
            </div>
          </>
        )}
      </Card>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? `ویرایش ${editing.username}` : "ساخت کاربر جدید"}
        description={editing ? "مشخصات دسترسی و محدودیت‌های کاربر را تغییر دهید." : "اطلاعات پایه را وارد کنید؛ UUID و لینک اشتراک خودکار ساخته می‌شود."}
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              انصراف
            </Button>
            <Button type="submit" form="user-form" loading={saveMutation.isPending}>
              {editing ? "ذخیره تغییرات" : "ساخت کاربر"}
            </Button>
          </>
        }
      >
        <form id="user-form" onSubmit={submitForm} className="form-grid">
          <ResourceAccessPicker value={form} onChange={policy => setForm(current => ({ ...current, ...policy }))} />
          {!editing && <Field label="پلن فروش" hint="با انتخاب پلن، حجم و مدت و سقف دستگاه از پلن اعمال می‌شود."><Select value={form.planId} onChange={e => setForm(current => ({ ...current, planId: e.target.value }))}><option value="">بدون پلن</option>{plans.data?.filter(p => p.is_active).map(p => <option key={p.id} value={p.id}>{p.name} · {formatNumber(p.price)}</option>)}</Select></Field>}
          <Field label="نام کاربری" hint="فقط حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط">
            <Input
              value={form.username}
              onChange={(event) => setForm({ ...form, username: event.target.value })}
              placeholder="sara_ahmadi"
              dir="ltr"
              required
              minLength={3}
            />
          </Field>
          <Field label="ایمیل (اختیاری)">
            <Input
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
              placeholder="user@example.com"
              dir="ltr"
            />
          </Field>

          <Field label="سقف مصرف (گیگابایت)" hint="عدد ۰ یعنی بدون محدودیت حجم">
            <Input
              type="number"
              min="0"
              step="0.5"
              value={form.dataLimitGb}
              onChange={(event) => setForm({ ...form, dataLimitGb: event.target.value })}
              dir="ltr"
            />
          </Field>
          <Field label="محدودیت دستگاه" hint="خالی یا صفر یعنی بدون محدودیت">
            <Input
              type="number"
              min="1"
              max="100"
              value={form.deviceLimit}
              onChange={(event) => setForm({ ...form, deviceLimit: event.target.value })}
              placeholder="بدون محدودیت"
              dir="ltr"
            />
          </Field>

          <Field label="تاریخ انقضا" hint="خالی بگذارید تا اشتراک بدون انقضا باشد" className="field-span-2">
            <Input
              type="datetime-local"
              value={form.expireAtLocal}
              onChange={(event) => setForm({ ...form, expireAtLocal: event.target.value })}
              dir="ltr"
            />
            <div className="preset-row">
              {[7, 30, 90].map((days) => (
                <button key={days} type="button" className="preset-chip" onClick={() => applyExpiry(days)}>
                  {formatNumber(days)} روز
                </button>
              ))}
              <button
                type="button"
                className="preset-chip"
                onClick={() => setForm({ ...form, expireAtLocal: "" })}
              >
                بدون انقضا
              </button>
            </div>
          </Field>

          <Field label="یادداشت" className="field-span-2">
            <Textarea
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
              placeholder="مثلاً پلن ماهانه ۵۰ گیگ، مشتری شماره ۱۲..."
              rows={3}
            />
          </Field>

          <div className="field-span-2 form-toggle-row">
            <div>
              <strong>وضعیت حساب</strong>
              <span>کاربر غیرفعال نمی‌تواند از اشتراک استفاده کند.</span>
            </div>
            <Toggle
              checked={form.isActive}
              onChange={(value) => setForm({ ...form, isActive: value })}
              label={form.isActive ? "فعال" : "غیرفعال"}
            />
          </div>

          {formError && <div className="form-error field-span-2">{formError}</div>}

          {editing && (
            <div className="edit-credentials field-span-2">
              <div>
                <span>UUID</span>
                <code dir="ltr">{editing.uuid}</code>
              </div>
              <div>
                <span>لینک اشتراک</span>
                <code dir="ltr">{subscriptionUrl(editing)}</code>
              </div>
            </div>
          )}
        </form>
      </Modal>

      <ConfirmDialog
        open={pending !== null}
        onClose={() => setPending(null)}
        onConfirm={() => actionMutation.mutate(pending)}
        title={pending ? actionTitles[pending.kind] : ""}
        message={confirmText(pending)}
        confirmLabel={pending?.kind === "delete" ? "حذف قطعی" : "تأیید"}
        danger={pending?.kind === "delete"}
        loading={actionMutation.isPending}
      />
    </div>
  );
}
