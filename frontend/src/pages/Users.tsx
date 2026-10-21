import { t, tt } from "../lib/i18n";import { useEffect, useMemo, useState, type FormEvent } from "react";
import ActionMenu from "../components/ActionMenu";
import UserDevices from "../components/UserDevices";
import { QRCodeSVG } from "qrcode.react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  CalendarClock,
  Copy,
  QrCode,
  ExternalLink,
  Link2Off,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users as UsersIcon } from
"lucide-react";
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
  toDateTimeLocal } from
"../lib/format";
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
  Toggle } from
"../components/UI";

interface UserForm extends ResourcePolicy {
  hwidLimit: string;resetDays: string;renewalDays: string;renewalCount: string;
  subscriptionSlug: string;
  username: string;
  email: string;
  note: string;
  dataLimitGb: string;
  expireAtLocal: string;
  deviceLimit: string;
  isActive: boolean;
  planId: string;
}

type PendingAction = {kind: "delete" | "reset" | "revoke" | "rotate";user: VPNUser;} | null;

const STATUS_TABS: {value: "" | UserStatus;label: string;}[] = [
{ value: "", label: t("همه") },
{ value: "active", label: t("فعال") },
{ value: "limited", label: t("اتمام حجم") },
{ value: "expired", label: t("منقضی") },
{ value: "disabled", label: t("غیرفعال") }];


function defaultExpiry(days: number): string {
  if (!days) return "";
  const date = new Date();
  date.setDate(date.getDate() + days);
  return toDateTimeLocal(date.toISOString());
}

function emptyForm(settings?: PanelSettings): UserForm {
  return {
    hwidLimit: "", resetDays: "", renewalDays: "", renewalCount: "0",
    subscriptionSlug: "",
    username: "",
    email: "",
    note: "",
    dataLimitGb: String(settings?.default_data_limit_gb || 0),
    expireAtLocal: defaultExpiry(settings?.default_expiry_days ?? 30),
    deviceLimit: "",
    isActive: true,
    planId: "",
    allowed_inbound_ids: null,
    allowed_dns_tunnel_ids: null
  };
}

function userToForm(user: VPNUser): UserForm {
  return {
    hwidLimit: String(user.hwid_limit || ""), resetDays: String(user.traffic_reset_days || ""), renewalDays: String(user.renewal_days || ""), renewalCount: String(user.renewal_remaining || 0),
    subscriptionSlug: user.sub_token,
    username: user.username,
    email: user.email ?? "",
    note: user.note ?? "",
    dataLimitGb: user.data_limit_bytes ? String(Math.round(user.data_limit_bytes / 1024 ** 3 * 100) / 100) : "0",
    expireAtLocal: toDateTimeLocal(user.expire_at),
    deviceLimit: user.device_limit ? String(user.device_limit) : "",
    isActive: user.is_active,
    planId: "",
    allowed_inbound_ids: user.allowed_inbound_ids ?? null,
    allowed_dns_tunnel_ids: user.allowed_dns_tunnel_ids ?? null
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
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [wg, setWg] = useState<{config: string;filename: string;} | null>(null);

  async function nativeWireGuard(user: VPNUser, revoke = false) {
    try {
      if (revoke) {
        await api.delete(`/api/wireguard/users/${user.id}`);
        toast.success(t("دسترسی WireGuard لغو شد."));
      } else {
        setWg(await api.post(`/api/wireguard/users/${user.id}`, {}));
      }
    } catch (error) {toast.error(error instanceof Error ? error.message : t("خطای WireGuard"));}
  }

  async function showSubscription(user: VPNUser) {
    try {
      setSubscription(await api.get<SubscriptionInfo>(`/sub/${user.sub_token}/info`));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("دریافت اشتراک ممکن نشد."));
    }
  }

  const settings = useQuery({
    queryKey: ["panel-settings"],
    queryFn: () => api.get<PanelSettings>("/api/settings"),
    enabled: !!admin?.permissions.includes("settings.read")
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
    placeholderData: (previous) => previous
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
      toast.success(editing ? t("تغییرات کاربر ذخیره شد.") : tt("کاربر {0} ساخته شد.", [user.username]));
      if (!editing) void showSubscription(user);
      setModalOpen(false);
      setEditing(null);
      setFormError("");
      invalidate();
    },
    onError: (error: Error) => setFormError(error.message)
  });

  const actionMutation = useMutation({
    mutationFn: async (action: PendingAction) => {
      if (!action) throw new Error(t("عملیات نامعتبر است."));
      const { kind, user } = action;
      if (kind === "delete") return api.delete<OperationResult>(`/api/users/${user.id}`);
      if (kind === "reset") return api.post<VPNUser>(`/api/users/${user.id}/reset-traffic`);
      if (kind === "revoke") return api.post<VPNUser>(`/api/users/${user.id}/revoke-subscription`);
      return api.post<VPNUser>(`/api/users/${user.id}/rotate-uuid`);
    },
    onSuccess: (_result, action) => {
      const messages = {
        delete: t("کاربر حذف شد."),
        reset: t("مصرف کاربر صفر شد."),
        revoke: t("لینک اشتراک ابطال و لینک جدید ساخته شد."),
        rotate: t("UUID و رمز کاربر چرخش کرد.")
      };
      toast.success(messages[action?.kind ?? "delete"]);
      setPending(null);
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message)
  });

  const toggleMutation = useMutation({
    mutationFn: (user: VPNUser) => api.patch<VPNUser>(`/api/users/${user.id}`, { is_active: !user.is_active }),
    onSuccess: (user) => {
      toast.success(user.is_active ? t("کاربر فعال شد.") : t("کاربر غیرفعال شد."));
      invalidate();
    },
    onError: (error: Error) => toast.error(error.message)
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
      toast.success(t("لینک اشتراک کپی شد."));
    } catch {
      toast.error(t("مرورگر اجازهٔ دسترسی به کلیپ‌بورد نداد."));
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
      setFormError(t("نام کاربری باید حداقل ۳ کاراکتر باشد."));
      return;
    }
    const limitValue = Number(form.dataLimitGb);
    const payload: Record<string, unknown> = {
      username: form.username.trim(),
      email: form.email.trim() || null,
      note: form.note.trim() || null,
      data_limit_bytes: limitValue > 0 ? Math.round(limitValue * 1024 ** 3) : null,
      expire_at: fromDateTimeLocal(form.expireAtLocal),
      hwid_limit: form.hwidLimit ? Number(form.hwidLimit) : null,
      traffic_reset_days: form.resetDays ? Number(form.resetDays) : null,
      renewal_days: form.renewalDays ? Number(form.renewalDays) : null,
      renewal_remaining: Number(form.renewalCount || 0),
      device_limit: form.deviceLimit ? Number(form.deviceLimit) : null,
      is_active: form.isActive,
      allowed_inbound_ids: form.allowed_inbound_ids,
      allowed_dns_tunnel_ids: form.allowed_dns_tunnel_ids
    };
    if (form.subscriptionSlug.trim()) payload.subscription_slug = form.subscriptionSlug.trim();
    if (form.planId) {
      payload.plan_id = Number(form.planId);
      if (!editing) {delete payload.data_limit_bytes;delete payload.expire_at;delete payload.device_limit;}
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
        return tt("کاربر «{0}» و تمام سوابق مصرف او حذف می‌شود. این عملیات بازگشت‌پذیر نیست.", [action.user.username]);
      case "reset":
        return tt("مصرف ثبت‌شده برای «{0}» صفر می‌شود. سوابق نمودار نیز پاک خواهد شد.", [action.user.username]);
      case "revoke":
        return tt("لینک اشتراک فعلی «{0}» باطل و لینک جدیدی ساخته می‌شود.", [action.user.username]);
      case "rotate":
        return tt("UUID و رمز اتصال «{0}» تغییر می‌کند و کلاینت‌های فعلی قطع می‌شوند.", [action.user.username]);
    }
  }

  const actionTitles: Record<string, string> = {
    delete: t("حذف کاربر"),
    reset: t("ریست مصرف"),
    revoke: t("ابطال لینک اشتراک"),
    rotate: t("چرخش UUID")
  };

  return (
    <div className="users-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">{t("مدیریت دسترسی")}</p>
          <h2>{t("کاربران و اشتراک‌ها")}</h2>
          <p className="page-subtitle">{t("ساخت، ویرایش و کنترل مصرف کاربران؛ همه از یک‌جا.")}</p>
        </div>
        <div className="page-actions">
          <Button variant="outline" icon={<RefreshCw size={16} />} onClick={() => users.refetch()} loading={users.isFetching}>{"" + t("به‌روزرسانی") + " "}

          </Button>
          <Button icon={<UserPlus size={17} />} onClick={openCreate}>{"" + t("کاربر جدید") + " "}

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
              placeholder={t("جست‌وجوی نام کاربری، ایمیل یا یادداشت...")} />

          </div>
          <div className="toolbar-meta">
            <Badge tone="neutral">
              <UsersIcon size={13} /> {formatNumber(users.data?.total ?? 0)}{" " + t("کاربر") + " "}
            </Badge>
            <span className="toolbar-divider" />
            <span className="toolbar-hint">{"" + t("صفحه") + " "}{formatNumber(page)}{" " + t("از") + " "}{formatNumber(totalPages)}</span>
          </div>
        </div>
        <div className="status-tabs">
          {STATUS_TABS.map((tab) =>
          <button
            key={tab.value}
            type="button"
            className={cn("status-tab", status === tab.value && "active")}
            onClick={() => {
              setStatus(tab.value);
              setPage(1);
            }}>

              {tab.label}
            </button>
          )}
        </div>
      </Card>

      <Card className="table-card">
        {users.isLoading ?
        <Spinner /> :
        users.isError ?
        <EmptyState
          icon={<UsersIcon size={24} />}
          title={t("دریافت کاربران ناموفق بود")}
          description={(users.error as Error).message}
          action={<Button onClick={() => users.refetch()}>{t("تلاش دوباره")}</Button>} /> :

        (users.data?.items.length ?? 0) === 0 ?
        <EmptyState
          icon={<UserPlus size={24} />}
          title={debouncedSearch || status ? t("کاربری پیدا نشد") : t("هنوز کاربری نساخته‌اید")}
          description={
          debouncedSearch || status ? t("فیلترها یا عبارت جست‌وجو را تغییر دهید.") : t("اولین کاربر را بسازید تا لینک اشتراک چندپروتکلی برایش تولید شود.")


          }
          action={
          debouncedSearch || status ?
          <Button
            variant="outline"
            onClick={() => {
              setSearch("");
              setStatus("");
            }}>{"" + t("پاک کردن فیلترها") + " "}


          </Button> :

          <Button icon={<Plus size={16} />} onClick={openCreate}>{"" + t("ساخت کاربر") + " "}

          </Button>

          } /> :


        <>
            <div className="table-wrap desktop-only">
              <table className="data-table users-table">
                <thead>
                  <tr>
                    <th>{t("کاربر")}</th>
                    <th>{t("وضعیت")}</th>
                    <th>{t("مصرف داده")}</th>
                    <th>{t("انقضا")}</th>
                    <th>{t("دستگاه")}</th>
                    <th className="align-end">{t("عملیات")}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.data?.items.map((user) =>
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
                            <small>{user.data_limit_bytes ? `/ ${formatBytes(user.data_limit_bytes)}` : t("نامحدود")}</small>
                          </div>
                          {user.data_limit_bytes ?
                      <Progress
                        value={user.usage_percent}
                        tone={user.usage_percent >= 90 ? "danger" : user.usage_percent >= 70 ? "warning" : "accent"} /> :


                      <div className="usage-unlimited">{t("بدون سقف حجم")}</div>
                      }
                        </div>
                      </td>
                      <td>
                        <div className="date-cell">
                          <span>{formatDate(user.expire_at)}</span>
                          <small>{user.expire_at ? formatDateTime(user.expire_at).split(t("،")).slice(-1) : t("همیشگی")}</small>
                        </div>
                      </td>
                      <td>
                        <span className="device-count">
                          {user.device_limit ? tt("{0} دستگاه", [formatNumber(user.device_limit)]) : "∞"}
                        </span>
                      </td>
                      <td>
                        <div className="row-actions">
                          <button type="button" className="icon-btn" title={t("اشتراک و QR")} onClick={() => showSubscription(user)}><QrCode size={18} /></button>
                          <button
                        type="button"
                        className="icon-btn"
                        title={t("کپی لینک اشتراک")}
                        onClick={() => copySubscription(user)}>

                            <Copy size={16} />
                          </button>
                          <button type="button" className="icon-btn" title={t("ویرایش")} onClick={() => openEdit(user)}>
                            <Pencil size={16} />
                          </button>
                          <ActionMenu>
                            {admin?.permissions.includes("settings.manage") && <>
                              <button type="button" onClick={() => nativeWireGuard(user)}>WireGuard IPv4 / QR</button>
                              <button type="button" onClick={() => nativeWireGuard(user, true)}>{t("لغو دسترسی WireGuard")}</button>
                            </>}

                              <button type="button" onClick={() => toggleMutation.mutate(user)}>
                                <Power size={15} />
                                {user.is_active ? t("غیرفعال کردن") : t("فعال کردن")}
                              </button>
                              <button type="button" onClick={() => setPending({ kind: "reset", user })}>
                                <RotateCcw size={15} />{"" + t("ریست مصرف") + " "}

                        </button>
                              <button type="button" onClick={() => setPending({ kind: "revoke", user })}>
                                <Link2Off size={15} />{"" + t("ابطال لینک اشتراک") + " "}

                        </button>
                              <button type="button" onClick={() => setPending({ kind: "rotate", user })}>
                                <ShieldCheck size={15} />{"" + t("چرخش UUID") + " "}

                        </button>
                              <span className="action-sep" />
                              <button type="button" className="danger" onClick={() => setPending({ kind: "delete", user })}>
                                <Trash2 size={15} />{"" + t("حذف کاربر") + " "}

                        </button>
                            </ActionMenu>
                        </div>
                      </td>
                    </tr>
                )}
                </tbody>
              </table>
            </div>

            <div className="mobile-user-list">
              {users.data?.items.map((user) =>
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
                      <small>{user.data_limit_bytes ? `/ ${formatBytes(user.data_limit_bytes)}` : t("نامحدود")}</small>
                    </div>
                    {user.data_limit_bytes ?
                <Progress
                  value={user.usage_percent}
                  tone={user.usage_percent >= 90 ? "danger" : user.usage_percent >= 70 ? "warning" : "accent"} /> :


                <div className="usage-unlimited">{t("بدون سقف حجم")}</div>
                }
                  </div>
                  <div className="mobile-user-meta">
                    <span>{"" + t("انقضا:") + " "}
                  <strong>{formatDate(user.expire_at)}</strong>
                    </span>
                    <span>{"" + t("دستگاه:") + " "}
                  <strong>{user.device_limit ? formatNumber(user.device_limit) : "∞"}</strong>
                    </span>
                  </div>
                  <div className="mobile-user-actions">
                    <Button size="sm" variant="ghost" icon={<QrCode size={16} />} onClick={() => showSubscription(user)}>{t("اشتراک و QR")}</Button>
                    <Button
                  size="sm"
                  variant="ghost"
                  icon={<Copy size={15} />}
                  onClick={() => copySubscription(user)}>{"" + t("لینک") + " "}


                </Button>
                    <Button size="sm" variant="ghost" icon={<Pencil size={15} />} onClick={() => openEdit(user)}>{"" + t("ویرایش") + " "}

                </Button>
                    <ActionMenu>
                            {admin?.permissions.includes("settings.manage") && <>
                              <button type="button" onClick={() => nativeWireGuard(user)}>WireGuard IPv4 / QR</button>
                              <button type="button" onClick={() => nativeWireGuard(user, true)}>{t("لغو دسترسی WireGuard")}</button>
                            </>}

                        <button type="button" onClick={() => toggleMutation.mutate(user)}>
                          <Power size={15} />
                          {user.is_active ? t("غیرفعال کردن") : t("فعال کردن")}
                        </button>
                        <button type="button" onClick={() => setPending({ kind: "reset", user })}>
                          <RotateCcw size={15} />{"" + t("ریست مصرف") + " "}

                  </button>
                        <button type="button" onClick={() => setPending({ kind: "revoke", user })}>
                          <Link2Off size={15} />{"" + t("ابطال لینک اشتراک") + " "}

                  </button>
                        <button type="button" onClick={() => setPending({ kind: "rotate", user })}>
                          <ShieldCheck size={15} />{"" + t("چرخش UUID") + " "}

                  </button>
                        <span className="action-sep" />
                        <button type="button" className="danger" onClick={() => setPending({ kind: "delete", user })}>
                          <Trash2 size={15} />{"" + t("حذف کاربر") + " "}

                  </button>
                      </ActionMenu>
                  </div>
                </div>
            )}
            </div>

            <div className="pagination">
              <Button
              variant="ghost"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}>{"" + t("قبلی") + " "}


            </Button>
              <span>{"" + t("صفحه") + " "}
              {formatNumber(page)}{" " + t("از") + " "}{formatNumber(totalPages)}
              </span>
              <Button variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>{"" + t("بعدی") + " "}

            </Button>
            </div>
          </>
        }
      </Card>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? tt("ویرایش {0}", [editing.username]) : t("ساخت کاربر جدید")}
        description={editing ? t("مشخصات دسترسی و محدودیت‌های کاربر را تغییر دهید.") : t("اطلاعات پایه را وارد کنید؛ UUID و لینک اشتراک خودکار ساخته می‌شود.")}
        wide
        footer={
        <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>{"" + t("انصراف") + " "}

          </Button>
            <Button type="submit" form="user-form" loading={saveMutation.isPending}>
              {editing ? t("ذخیره تغییرات") : t("ساخت کاربر")}
            </Button>
          </>
        }>

        <form id="user-form" onSubmit={submitForm} className="form-grid">
          <Field label={t("نام دلخواه لینک اشتراک")} hint={t("اختیاری؛ حروف انگلیسی، عدد، خط تیره و زیرخط. نام کوتاه مثل test قابل حدس است؛ برای لینک خصوصی نام طولانی انتخاب کنید.")}>
            <Input dir="ltr" value={form.subscriptionSlug} placeholder={t("خالی = لینک تصادفی امن")} minLength={3} maxLength={64} pattern="[a-zA-Z0-9_-]+" onChange={(e) => setForm({ ...form, subscriptionSlug: e.target.value })} />
          </Field>
          <ResourceAccessPicker value={form} onChange={(policy) => setForm((current) => ({ ...current, ...policy }))} />
          {!editing && <Field label={t("پلن فروش")} hint={t("با انتخاب پلن، حجم و مدت و سقف دستگاه از پلن اعمال می‌شود.")}><Select value={form.planId} onChange={(e) => setForm((current) => ({ ...current, planId: e.target.value }))}><option value="">{t("بدون پلن")}</option>{plans.data?.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} · {formatNumber(p.price)}</option>)}</Select></Field>}
          <Field label={t("نام کاربری")} hint={t("فقط حروف انگلیسی، عدد، نقطه، خط تیره و زیرخط")}>
            <Input
              value={form.username}
              onChange={(event) => setForm({ ...form, username: event.target.value })}
              placeholder="sara_ahmadi"
              dir="ltr"
              required
              minLength={3} />

          </Field>
          <Field label={t("ایمیل (اختیاری)")}>
            <Input
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
              placeholder="user@example.com"
              dir="ltr" />

          </Field>

          <Field label={t("سقف مصرف (گیگابایت)")} hint={t("عدد ۰ یعنی بدون محدودیت حجم")}>
            <Input
              type="number"
              min="0"
              step="0.5"
              value={form.dataLimitGb}
              onChange={(event) => setForm({ ...form, dataLimitGb: event.target.value })}
              dir="ltr" />

          </Field>
          <Field label={t("سقف IP هم‌زمان Xray محلی")} hint={t("خالی یا صفر یعنی نامحدود. هستهٔ مدیریت‌شده IP جدیدِ مازاد را رد می‌کند؛ کاهش سقف حدود پنج ثانیه بعد فقط اتصال‌های مازاد را می‌بندد. چند دستگاه پشت NAT ممکن است یک IP باشند. هستهٔ قدیمی نیاز به ارتقا دارد.")}>
            <Input
              type="number"
              min="1"
              max="100"
              value={form.deviceLimit}
              onChange={(event) => setForm({ ...form, deviceLimit: event.target.value })}
              placeholder={t("بدون محدودیت")}
              dir="ltr" />

          </Field>

          <Field label={t("سقف دستگاه‌های HWID")} hint={t("اختیاری؛ فقط برنامه‌های ارسال‌کنندهٔ X-HWID. این شناسه قابل جعل است و سقف اتصال شبکه نیست.")}><Input type="number" min={1} max={100} value={form.hwidLimit} onChange={(e) => setForm({ ...form, hwidLimit: e.target.value })} /></Field>
          <Field label={t("ریست خودکار حجم (هر چند روز)")} hint={t("خالی یعنی بدون ریست دوره‌ای.")}><Input type="number" min={1} max={365} value={form.resetDays} onChange={(e) => setForm({ ...form, resetDays: e.target.value })} /></Field>
          <Field label={t("مدت هر تمدید خودکار (روز)")}><Input type="number" min={1} max={365} value={form.renewalDays} onChange={(e) => setForm({ ...form, renewalDays: e.target.value })} /></Field>
          <Field label={t("تعداد تمدید مجاز باقی‌مانده")} hint={t("با هر انقضا یک تمدید مصرف و حجم صفر می‌شود؛ صفر یعنی غیرفعال.")}><Input type="number" min={0} max={120} value={form.renewalCount} onChange={(e) => setForm({ ...form, renewalCount: e.target.value })} /></Field>
          {editing && <UserDevices userId={editing.id} />}
          <Field label={t("تاریخ انقضا")} hint={t("خالی بگذارید تا اشتراک بدون انقضا باشد")} className="field-span-2">
            <Input
              type="datetime-local"
              value={form.expireAtLocal}
              onChange={(event) => setForm({ ...form, expireAtLocal: event.target.value })}
              dir="ltr" />

            <div className="preset-row">
              {[7, 30, 90].map((days) =>
              <button key={days} type="button" className="preset-chip" onClick={() => applyExpiry(days)}>
                  {formatNumber(days)}{" " + t("روز") + " "}
              </button>
              )}
              <button
                type="button"
                className="preset-chip"
                onClick={() => setForm({ ...form, expireAtLocal: "" })}>{"" + t("بدون انقضا") + " "}


              </button>
            </div>
          </Field>

          <Field label={t("یادداشت")} className="field-span-2">
            <Textarea
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
              placeholder={t("مثلاً پلن ماهانه ۵۰ گیگ، مشتری شماره ۱۲...")}
              rows={3} />

          </Field>

          <div className="field-span-2 form-toggle-row">
            <div>
              <strong>{t("وضعیت حساب")}</strong>
              <span>{t("کاربر غیرفعال نمی‌تواند از اشتراک استفاده کند.")}</span>
            </div>
            <Toggle
              checked={form.isActive}
              onChange={(value) => setForm({ ...form, isActive: value })}
              label={form.isActive ? t("فعال") : t("غیرفعال")} />

          </div>

          {formError && <div className="form-error field-span-2">{formError}</div>}

          {editing &&
          <div className="edit-credentials field-span-2">
              <div>
                <span>UUID</span>
                <code dir="ltr">{editing.uuid}</code>
              </div>
              <div>
                <span>{t("لینک اشتراک")}</span>
                <code dir="ltr">{subscriptionUrl(editing)}</code>
              </div>
            </div>
          }
        </form>
      </Modal>
      <Modal open={!!subscription} onClose={() => setSubscription(null)} title={t("اشتراک و QR کاربر")}>
        {subscription && <div className="subscription-share">
          <div className="qr-frame"><QRCodeSVG value={subscription.subscription_url} size={210} marginSize={2} /></div>
          <Field label={t("لینک اشتراک برای برنامه")}><Input dir="ltr" readOnly value={subscription.subscription_url} /></Field>
          <Button icon={<Copy size={16} />} onClick={async () => {try {await navigator.clipboard.writeText(subscription.subscription_url);toast.success(t("کپی شد."));} catch {toast.error(t("لینک را از کادر کپی کنید."));}}}>{t("کپی لینک اشتراک")}</Button>
          <a className="text-link" href={subscription.page_url} target="_blank" rel="noreferrer"><ExternalLink size={16} />{" " + t("باز کردن صفحه کاربر، حجم و کانفیگ‌ها") + ""}</a>
        </div>}
      </Modal>
      <Modal open={!!wg} onClose={() => setWg(null)} title={t("کانفیگ WireGuard IPv4")}>
        {wg && <div className="subscription-share">
          <div className="qr-frame"><QRCodeSVG value={wg.config} size={240} marginSize={2} /></div>
          <Textarea dir="ltr" readOnly rows={11} value={wg.config} />
          <Button onClick={() => {
            const url = URL.createObjectURL(new Blob([wg.config], { type: "text/plain" }));
            const a = document.createElement("a");a.href = url;a.download = wg.filename;a.click();setTimeout(() => URL.revokeObjectURL(url), 1000);
          }}>{t("دانلود فایل conf برای برنامه WireGuard")}</Button>
          <p>{t("این دسترسی جداگانه توسط مدیر اعطا می‌شود. حجم و انقضای همان کاربر روی WireGuard هم اعمال می‌شود.")}</p>
        </div>}
      </Modal>

      <ConfirmDialog
        open={pending !== null}
        onClose={() => setPending(null)}
        onConfirm={() => actionMutation.mutate(pending)}
        title={pending ? actionTitles[pending.kind] : ""}
        message={confirmText(pending)}
        confirmLabel={pending?.kind === "delete" ? t("حذف قطعی") : t("تأیید")}
        danger={pending?.kind === "delete"}
        loading={actionMutation.isPending} />

    </div>);

}
