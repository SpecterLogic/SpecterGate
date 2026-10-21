export type UserStatus = "active" | "expired" | "limited" | "disabled";
export type AdminRole = "superadmin" | "admin" | "reseller" | "support" | "viewer";

export interface Plan {
  id: number; name: string; description: string | null; days: number;
  data_limit_bytes: number | null; device_limit: number | null;
  price: number; is_active: boolean;
}

export interface SubscriptionGroup {
  allowed_inbound_ids: number[] | null; allowed_dns_tunnel_ids: number[] | null;
  id: number; name: string; token: string; owner_admin_id: number | null;
  plan_id: number | null; max_members: number; data_limit_bytes: number | null;
  expire_at: string | null; is_active: boolean; status: string;
  used_traffic_bytes: number; note: string | null;
  members: { id: number; username: string; status: string; used_traffic_bytes: number }[];
}

export interface Admin {
  id: number;
  username: string;
  role: AdminRole;
  is_owner: boolean;
  is_active: boolean;
  totp_enabled?: boolean;
  parent_id: number | null;
  scope: "all" | "own" | "none";
  max_users: number | null;
  traffic_quota_bytes: number | null;
  credit: number;
  require_template: boolean;
  permissions: string[];
  user_count: number;
  used_traffic_bytes: number;
  last_login_at: string | null;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  admin: Admin;
}

export interface VPNUser {
  allowed_inbound_ids: number[] | null;
  allowed_dns_tunnel_ids: number[] | null;
  subscription_id: number | null;
  group_subscription_path: string | null;
  id: number;
  username: string;
  email: string | null;
  uuid: string;
  sub_token: string;
  status: UserStatus;
  is_active: boolean;
  data_limit_bytes: number | null;
  used_traffic_bytes: number;
  remaining_bytes: number | null;
  upload_bytes: number;
  download_bytes: number;
  usage_percent: number;
  device_limit: number | null;
  expire_at: string | null;
  last_online_at: string | null;
  note: string | null;
  created_at: string;
  subscription_path: string;
}

export interface UserPage {
  items: VPNUser[];
  total: number;
  page: number;
  size: number;
}

export interface Node {
  id: number;
  name: string;
  address: string;
  port: number;
  api_address: string | null;
  api_port: number | null;
  api_key: string;
  status: string;
  is_local: boolean;
  is_online: boolean;
  traffic_coefficient: number;
  cpu_usage: number;
  memory_usage: number;
  note: string | null;
  last_seen_at: string | null;
  created_at: string;
  inbound_count: number;
}

export type Protocol = "vless" | "vmess" | "trojan" | "shadowsocks";
export type Network = "tcp" | "ws" | "grpc" | "httpupgrade" | "xhttp" | "kcp";
export type Security = "reality" | "tls" | "none";

export interface Inbound {
  extra_json: string | null;
  id: number;
  node_id: number | null;
  node_name: string | null;
  tag: string;
  protocol: Protocol;
  listen: string;
  port: number;
  network: Network;
  security: Security;
  remark: string;
  sni: string | null;
  host: string | null;
  path: string | null;
  service_name: string | null;
  flow: string | null;
  fingerprint: string | null;
  alpn: string | null;
  reality_public_key: string | null;
  reality_private_key: string | null;
  reality_short_id: string | null;
  reality_dest: string | null;
  tls_cert_path: string | null;
  tls_key_path: string | null;
  is_active: boolean;
  data_limit_bytes?: number | null;
  expire_at?: string | null;
  reset_interval_days?: number | null;
  last_reset_at?: string | null;
  usage_percent?: number;
  status?: "active" | "disabled" | "expired" | "limited";
  total_bytes: number;
  created_at: string;
}

export interface TrafficPoint {
  date: string;
  upload: number;
  download: number;
  total: number;
}

export interface DashboardOverview {
  total_users: number;
  active_users: number;
  expired_users: number;
  limited_users: number;
  disabled_users: number;
  total_nodes: number;
  online_nodes: number;
  total_inbounds: number;
  active_inbounds: number;
  upload_bytes: number;
  download_bytes: number;
  total_traffic_bytes: number;
  today_traffic_bytes: number;
  traffic_series: TrafficPoint[];
  protocol_series: { name: string; value: number }[];
  recent_users: VPNUser[];
  nodes: Node[];
}

export interface PanelSettings {
  time_zone: string;
  calendar: 'persian' | 'gregory';
  panel_title: string;
  panel_description: string;
  subscription_base_url: string;
  public_host: string;
  default_expiry_days: number;
  default_data_limit_gb: number;
  subscription_path_prefix: string;
  support_url: string;
  announcement: string;
  registration_enabled: boolean;
}

export interface DnsTunnel {
  managed_gateway: boolean;
  id: number;
  name: string;
  domain: string;
  upstream_port: number;
  target_host: string;
  target_port: number;
  mtu: number;
  resolver: string;
  private_key: string;
  public_key: string;
  noizdns_enabled: boolean;
  is_active: boolean;
  note: string | null;
  created_at: string;
}

export interface DnsTunnelSetup {
  id: number;
  name: string;
  domain: string;
  key_path: string;
  command: string;
  systemd_unit: string;
  dns_records: string[];
  multiplexer_entry: { domain: string; upstream: string };
  client_uri_template_dnstt: string;
  client_uri_template_noizdns: string | null;
  notes: string[];
}

export interface DnsMultiplexer {
  listen: string;
  routes: { domain: string; upstream: string }[];
  config: Record<string, unknown>;
  command: string;
}

export interface DnsLink {
  id: number;
  remark: string;
  protocol: "dnstt" | "noizdns";
  domain: string;
  uri: string;
}

export interface SubscriptionInfo {
  username: string;
  status: UserStatus;
  expire_at: string | null;
  data_limit_bytes: number | null;
  used_traffic_bytes: number;
  upload_bytes: number;
  download_bytes: number;
  links: { remark: string; protocol: Protocol; uri: string }[];
  dns_links: DnsLink[];
  subscription_url: string;
  clash_url: string;
  page_url: string;
  format_urls: Record<string, string>;
  subscription_type: "single" | "group";
  group_name: string | null;
  max_members: number;
  members: { id: number; username: string; status: string; used_traffic_bytes: number }[];
  panel_title: string;
  panel_description: string;
  support_url: string;
  announcement: string;
}

export interface XrayStatus {
  enabled: boolean;
  binary_available: boolean;
  running: boolean;
  config_path: string;
  config_exists: boolean;
  message: string;
  pid: number | null;
}

export interface XrayApplyResult {
  ok: boolean;
  message: string;
  config_path: string;
  inbound_count: number;
  client_count: number;
  validation_output: string;
  warnings?: string[];
}

export interface AuditLog {
  id: number;
  admin_username: string;
  action: string;
  target_type: string;
  target_id: string | null;
  detail: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface OperationResult {
  ok: boolean;
  message: string;
}
