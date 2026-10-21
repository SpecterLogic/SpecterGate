import { t, tt } from "../lib/i18n";import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpRight,
  Boxes,
  Cpu,
  Database,
  HardDrive,
  Plus,
  RefreshCw,
  Server,
  TrendingUp,
  Users } from
"lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis } from
"recharts";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import type { DashboardOverview } from "../lib/types";
import {
  cn,
  formatBytes,
  formatDate,
  formatNumber,
  protocolLabel,
  toLocalDate,
  todayLabel } from
"../lib/format";
import { Badge, Button, Card, EmptyState, Progress, SectionHeader, Skeleton, StatusBadge } from "../components/UI";

const PROTOCOL_COLORS: Record<string, string> = {
  vless: "#2dd4bf",
  vmess: "#818cf8",
  trojan: "#f472b6",
  shadowsocks: "#f59e0b"
};

export default function Dashboard() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [syncing, setSyncing] = useState(false);

  const overview = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardOverview>("/api/dashboard/overview"),
    refetchInterval: 60_000
  });

  const syncStats = useMutation({
    mutationFn: () => api.post<{ok: boolean;message: string;}>("/api/xray/sync-stats"),
    onMutate: () => setSyncing(true),
    onSuccess: (result) => {
      if (result.ok) toast.success(result.message);else
      toast.error(result.message);
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: Error) => toast.error(error.message),
    onSettled: () => setSyncing(false)
  });

  if (overview.isLoading) {
    return (
      <div className="dashboard-page">
        <div className="stats-grid">
          {[0, 1, 2, 3].map((item) =>
          <Card key={item} className="stat-card">
              <Skeleton height={16} width="45%" />
              <Skeleton height={38} width="65%" />
              <Skeleton height={12} width="80%" />
            </Card>
          )}
        </div>
        <Card className="chart-card">
          <Skeleton height={300} />
        </Card>
      </div>);

  }

  if (overview.isError || !overview.data) {
    return (
      <Card>
        <EmptyState
          icon={<Activity size={24} />}
          title={t("دریافت اطلاعات ناموفق بود")}
          description={t("ارتباط با بک‌اند پنل برقرار نشد. دوباره تلاش کنید.")}
          action={<Button onClick={() => overview.refetch()}>{t("تلاش دوباره")}</Button>} />

      </Card>);

  }

  const data = overview.data;
  const totalProtocols = data.protocol_series.reduce((sum, item) => sum + item.value, 0);
  const usageToday = data.today_traffic_bytes;
  const statusSummary = [
  { label: t("فعال"), value: data.active_users, tone: "success" },
  { label: t("اتمام حجم"), value: data.limited_users, tone: "warning" },
  { label: t("منقضی"), value: data.expired_users, tone: "danger" },
  { label: t("غیرفعال"), value: data.disabled_users, tone: "neutral" }] as
  const;

  return (
    <div className="dashboard-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">{todayLabel()}</p>
          <h2>{t("سلام، همه‌چیز زیر کنترل است.")}</h2>
          <p className="page-subtitle">{"" + t("نگاهی سریع به وضعیت کاربران، ترافیک و سلامت نودها در ۷ روز گذشته.") + " "}

          </p>
        </div>
        <div className="page-actions">
          <Button
            variant="outline"
            icon={<RefreshCw size={16} className={cn(syncing && "spin")} />}
            onClick={() => syncStats.mutate()}
            loading={syncing}>{"" + t("همگام‌سازی آمار") + " "}


          </Button>
          <Button icon={<Plus size={17} />} onClick={() => navigate("/users?new=1")}>{"" + t("کاربر جدید") + " "}

          </Button>
        </div>
      </div>

      <div className="stats-grid">
        <Card className="stat-card stat-card-teal">
          <div className="stat-top">
            <span className="stat-icon">
              <Users size={20} />
            </span>
            <Badge tone="success" dot>
              {formatNumber(data.active_users)}{" " + t("فعال") + " "}
            </Badge>
          </div>
          <div className="stat-value">{formatNumber(data.total_users)}</div>
          <div className="stat-label">{t("کاربر ثبت‌شده")}</div>
          <div className="stat-foot">
            <span>{formatNumber(data.limited_users)}{" " + t("اتمام حجم") + ""}</span>
            <span>{formatNumber(data.expired_users)}{" " + t("منقضی") + ""}</span>
          </div>
        </Card>

        <Card className="stat-card stat-card-violet">
          <div className="stat-top">
            <span className="stat-icon">
              <HardDrive size={20} />
            </span>
            <span className="stat-trend">
              <TrendingUp size={14} />
              {formatBytes(usageToday)}{" " + t("امروز") + " "}
            </span>
          </div>
          <div className="stat-value">{formatBytes(data.total_traffic_bytes, 0)}</div>
          <div className="stat-label">{t("ترافیک کل مصرف‌شده")}</div>
          <div className="stat-foot split">
            <span>
              <ArrowUpRight size={13} /> {formatBytes(data.upload_bytes)}
            </span>
            <span>
              <ArrowDownToLine size={13} /> {formatBytes(data.download_bytes)}
            </span>
          </div>
        </Card>

        <Card className="stat-card stat-card-blue">
          <div className="stat-top">
            <span className="stat-icon">
              <Server size={20} />
            </span>
            <Badge tone={data.online_nodes === data.total_nodes ? "success" : "warning"} dot>
              {formatNumber(data.online_nodes)} / {formatNumber(data.total_nodes)}
            </Badge>
          </div>
          <div className="stat-value">{formatNumber(data.total_nodes)}</div>
          <div className="stat-label">{t("نود متصل")}</div>
          <div className="stat-foot">
            <span>{formatNumber(data.online_nodes)}{" " + t("نود آنلاین") + ""}</span>
          </div>
        </Card>

        <Card className="stat-card stat-card-amber">
          <div className="stat-top">
            <span className="stat-icon">
              <Boxes size={20} />
            </span>
            <Badge tone="info" dot>
              {formatNumber(data.active_inbounds)}{" " + t("فعال") + " "}
            </Badge>
          </div>
          <div className="stat-value">{formatNumber(data.total_inbounds)}</div>
          <div className="stat-label">{t("اینباند پیکربندی‌شده")}</div>
          <div className="stat-foot">
            <span>{totalProtocols ? tt("{0} مسیر فعال", [formatNumber(totalProtocols)]) : t("هنوز اینباندی ساخته نشده")}</span>
          </div>
        </Card>
      </div>

      <div className="dashboard-main-grid">
        <Card className="chart-card traffic-card">
          <SectionHeader
            title={t("روند ترافیک")}
            subtitle={t("مجموع آپلود و دانلود ثبت‌شده در ۷ روز اخیر")}
            action={
            <div className="chart-legend">
                <span>
                  <i className="legend-dot upload" />{" " + t("آپلود") + " "}
              </span>
                <span>
                  <i className="legend-dot download" />{" " + t("دانلود") + " "}
              </span>
              </div>
            } />

          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={288}>
              <AreaChart data={data.traffic_series} margin={{ top: 12, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="uploadGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.36} />
                    <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0.01} />
                  </linearGradient>
                  <linearGradient id="downloadGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#818cf8" stopOpacity={0.32} />
                    <stop offset="100%" stopColor="#818cf8" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="4 6" vertical={false} stroke="rgba(148,163,184,.1)" />
                <XAxis
                  dataKey="date"
                  reversed
                  tickFormatter={toLocalDate}
                  tick={{ fill: "#7d899e", fontSize: 11, fontFamily: "inherit" }}
                  axisLine={false}
                  tickLine={false}
                  dy={8} />

                <YAxis
                  orientation="right"
                  tickFormatter={(value) => formatBytes(Number(value), 0)}
                  tick={{ fill: "#7d899e", fontSize: 10, fontFamily: "inherit" }}
                  axisLine={false}
                  tickLine={false}
                  width={62} />

                <Tooltip
                  cursor={{ stroke: "rgba(45,212,191,.35)", strokeWidth: 1 }}
                  contentStyle={{
                    background: "#101724",
                    border: "1px solid rgba(148,163,184,.18)",
                    borderRadius: 12,
                    fontFamily: "inherit",
                    direction: "rtl",
                    boxShadow: "0 18px 40px rgba(0,0,0,.4)"
                  }}
                  labelFormatter={(label) => toLocalDate(String(label))}
                  formatter={(value) => formatBytes(Number(value))} />

                <Area
                  type="monotone"
                  dataKey="download"
                  name={t("دانلود")}
                  stroke="#818cf8"
                  strokeWidth={2.2}
                  fill="url(#downloadGradient)" />

                <Area
                  type="monotone"
                  dataKey="upload"
                  name={t("آپلود")}
                  stroke="#2dd4bf"
                  strokeWidth={2.2}
                  fill="url(#uploadGradient)" />

              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-summary">
            {statusSummary.map((item) =>
            <div key={item.label}>
                <span className={cn("summary-dot", item.tone)} />
                <span>{item.label}</span>
                <strong>{formatNumber(item.value)}</strong>
              </div>
            )}
          </div>
        </Card>

        <Card className="nodes-card">
          <SectionHeader
            title={t("سلامت نودها")}
            subtitle={t("وضعیت لحظه‌ای سرورها")}
            action={
            <Link to="/nodes" className="text-link">{"" + t("مدیریت") + " "}

            </Link>
            } />

          <div className="node-mini-list">
            {data.nodes.length === 0 &&
            <EmptyState
              icon={<Server size={22} />}
              title={t("نودی وجود ندارد")}
              description={t("برای شروع یک نود محلی یا راه دور اضافه کنید.")} />

            }
            {data.nodes.map((node) =>
            <div className="node-mini" key={node.id}>
                <span className={cn("node-signal", node.is_online ? "online" : "offline")}>
                  <Server size={16} />
                </span>
                <div className="node-mini-info">
                  <div>
                    <strong>{node.name}</strong>
                    {node.is_local && <span className="mini-tag">{t("محلی")}</span>}
                  </div>
                  <span dir="ltr">{node.address}</span>
                </div>
                <div className="node-metrics">
                  <span>
                    <Cpu size={12} /> {formatNumber(Math.round(node.cpu_usage))}{"" + t("٪") + " "}
                </span>
                  <span>
                    <Database size={12} /> {formatNumber(Math.round(node.memory_usage))}{"" + t("٪") + " "}
                </span>
                </div>
                <StatusBadge status={node.is_online ? "online" : "offline"} />
              </div>
            )}
          </div>
          <div className="nodes-footnote">
            <span className="pulse-dot" />{"" + t("وضعیت نودها هر ۳۰ ثانیه به‌روزرسانی می‌شود.") + " "}

          </div>
        </Card>
      </div>

      <div className="dashboard-bottom-grid">
        <Card className="recent-card">
          <SectionHeader
            title={t("کاربران اخیر")}
            subtitle={t("آخرین حساب‌های ساخته‌شده")}
            action={
            <Link to="/users" className="text-link">{"" + t("همهٔ کاربران") + " "}

            </Link>
            } />

          {data.recent_users.length === 0 ?
          <EmptyState
            icon={<Users size={22} />}
            title={t("هنوز کاربری ساخته نشده")}
            description={t("اولین کاربر خود را بسازید و لینک اشتراک را تحویل دهید.")}
            action={
            <Button size="sm" icon={<Plus size={15} />} onClick={() => navigate("/users?new=1")}>{"" + t("ساخت کاربر") + " "}

            </Button>
            } /> :


          <>
            <div className="table-wrap desktop-only">
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>{t("کاربر")}</th>
                    <th>{t("وضعیت")}</th>
                    <th>{t("مصرف")}</th>
                    <th>{t("انقضا")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_users.map((user) =>
                  <tr key={user.id}>
                      <td>
                        <div className="identity-cell">
                          <span className="identity-avatar">{user.username.slice(0, 2).toUpperCase()}</span>
                          <div>
                            <strong>{user.username}</strong>
                            <span>{user.email || t("بدون ایمیل")}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={user.status} />
                      </td>
                      <td>
                        <div className="usage-cell">
                          <span>{formatBytes(user.used_traffic_bytes)}</span>
                          <Progress value={user.usage_percent} tone={user.usage_percent > 85 ? "danger" : "accent"} />
                        </div>
                      </td>
                      <td className="muted-cell">{formatDate(user.expire_at)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="recent-mobile-list">
              {data.recent_users.map((user) =>
              <div className="recent-mobile-row" key={user.id}>
                  <div className="recent-mobile-main">
                    <span className="identity-avatar">{user.username.slice(0, 2).toUpperCase()}</span>
                    <div>
                      <strong>{user.username}</strong>
                      <span>{user.email || t("بدون ایمیل")}</span>
                    </div>
                    <StatusBadge status={user.status} />
                  </div>
                  <div className="recent-mobile-usage">
                    <div className="usage-text">
                      <span>{formatBytes(user.used_traffic_bytes)}</span>
                      <small>{user.data_limit_bytes ? `/ ${formatBytes(user.data_limit_bytes)}` : t("نامحدود")}</small>
                    </div>
                    <Progress value={user.usage_percent} tone={user.usage_percent > 85 ? "danger" : "accent"} />
                  </div>
                  <div className="recent-mobile-foot">
                    <span>{"" + t("انقضا:") + " "}{formatDate(user.expire_at)}</span>
                    <span>{formatNumber(user.usage_percent)}{t("٪ مصرف")}</span>
                  </div>
                </div>
              )}
            </div>
            </>
          }
        </Card>

        <Card className="protocol-card">
          <SectionHeader title={t("ترکیب پروتکل‌ها")} subtitle={t("اینباندهای فعال")} />
          {data.protocol_series.length === 0 ?
          <EmptyState
            icon={<Boxes size={22} />}
            title={t("اینباندی فعال نیست")}
            description={t("برای ساخت لینک اشتراک، حداقل یک اینباند اضافه کنید.")}
            action={
            <Button size="sm" onClick={() => navigate("/inbounds")}>{"" + t("ساخت اینباند") + " "}

            </Button>
            } /> :


          <>
              <div className="donut-wrap">
                <ResponsiveContainer width="100%" height={190}>
                  <PieChart>
                    <Pie
                    data={data.protocol_series}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={58}
                    outerRadius={82}
                    paddingAngle={4}
                    stroke="none">

                      {data.protocol_series.map((entry) =>
                    <Cell key={entry.name} fill={PROTOCOL_COLORS[entry.name] || "#64748b"} />
                    )}
                    </Pie>
                    <Tooltip
                    contentStyle={{
                      background: "#101724",
                      border: "1px solid rgba(148,163,184,.18)",
                      borderRadius: 12,
                      fontFamily: "inherit",
                      direction: "rtl"
                    }}
                    formatter={(value) => formatNumber(Number(value))}
                    labelFormatter={(label) => protocolLabel(String(label))} />

                  </PieChart>
                </ResponsiveContainer>
                <div className="donut-center">
                  <strong>{formatNumber(totalProtocols)}</strong>
                  <span>{t("اینباند")}</span>
                </div>
              </div>
              <div className="protocol-legend">
                {data.protocol_series.map((entry) =>
              <div key={entry.name}>
                    <span className="legend-dot" style={{ background: PROTOCOL_COLORS[entry.name] || "#64748b" }} />
                    <span>{protocolLabel(entry.name)}</span>
                    <strong>{formatNumber(entry.value)}</strong>
                  </div>
              )}
              </div>
            </>
          }
        </Card>
      </div>
    </div>);

}
