import { apiGetJson } from "./httpClient";
import type { PaginationMeta } from "../ui/Pager";

type Paged<T> = {
  generated_at: string;
  items: T[];
  pagination: PaginationMeta;
  filters?: Record<string, string>;
};

function query(params: Record<string, string | number | undefined | null>): string {
  const url = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || String(value).trim() === "") {
      continue;
    }
    url.set(key, String(value));
  }
  const raw = url.toString();
  return raw ? `?${raw}` : "";
}

export type AdminUser = {
  telegram_id: number;
  username: string;
  balance_rub: number;
  subscription_until: string;
  subscription_active: boolean;
  is_blocked: boolean;
  created_at: string;
  configs_total: number;
  configs_active: number;
  devices_active: number;
  last_config_at: string;
  paid_count: number;
  paid_sum: number;
  last_paid_at: string;
};

export type UserDevice = {
  device_name: string;
  configs_total: number;
  configs_active: number;
  servers: string[];
  servers_text: string;
  last_config_at: string;
};

export type UserDevicesResponse = {
  generated_at: string;
  user: {
    telegram_id: number;
    username: string;
    balance_rub: number;
    subscription_until: string;
    subscription_active: boolean;
    is_blocked: boolean;
  };
  items: UserDevice[];
};

export type AdminConfig = {
  id: number;
  telegram_id: number;
  server: string;
  device_name: string;
  is_active: boolean;
  created_at: string;
};

export type AdminSubscription = {
  telegram_id: number;
  username: string;
  balance_rub: number;
  subscription_until: string;
  is_active: boolean;
};

export type AdminPayment = {
  invoice_id: number;
  telegram_id: number;
  amount_rub: number;
  payable_rub: number;
  kind: string;
  promo_code: string | null;
  promo_discount_percent: number;
  credited_rub: number;
  referral_bonus_rub: number;
  status: string;
  created_at: string;
  paid_at: string;
};

export type AdminPromo = {
  id: number;
  code: string;
  kind: string;
  value_int: number;
  max_uses_total: number;
  max_uses_per_user: number;
  starts_at: string;
  ends_at: string;
  enabled: boolean;
  uses_total: number;
};

export type PromoUse = {
  id: number;
  code: string;
  telegram_id: number;
  kind: string;
  value_int: number;
  payment_invoice_id: number | null;
  created_at: string;
};

export type PromosResponse = {
  generated_at: string;
  items: AdminPromo[];
  uses: {
    items: PromoUse[];
    pagination: PaginationMeta;
    filters: { q: string };
  };
};

export type GiveawayWinner = {
  user_id: number;
  telegram_id: number;
  username: string;
  reason: string;
  created_at: string;
};

export type AdminGiveaway = {
  id: number;
  title: string;
  description: string;
  prize: string;
  kind: string;
  kind_title: string;
  condition_text: string;
  starts_at: string;
  ends_at: string;
  enabled: boolean;
  active: boolean;
  participants: number;
  winners: GiveawayWinner[];
};

export type GiveawaysResponse = {
  generated_at: string;
  items: AdminGiveaway[];
};

export type AdminAuditRow = {
  id: number;
  admin_telegram_id: number;
  action: string;
  entity_type: string;
  entity_id: string;
  request_path: string;
  remote_addr: string;
  details_json: string;
  created_at: string;
};

export type AuditResponse = Paged<AdminAuditRow> & {
  filters: {
    q: string;
    action: string;
    available_actions: string[];
  };
};

export type AdminSettingsResponse = {
  generated_at: string;
  values: Record<string, string | number | boolean>;
  masked: Record<string, string>;
};

export type AdminServerRow = {
  id: number;
  name: string;
  enabled: boolean;
  protocol: string;
  host: string;
  port: number;
  sni: string;
  ssh_host: string;
  active_clients: number;
  runtime: {
    health: string;
    xray_state: string;
    vpn_latency_text: string;
    established_connections?: number;
    error?: string;
  };
};

export type AdminServersSnapshot = {
  generated_at: string;
  servers: AdminServerRow[];
  defaults?: Record<string, string | number | boolean>;
};

export type AdminServerDetail = {
  generated_at: string;
  server: {
    id: number;
    name: string;
    protocol: string;
    host: string;
    port: number;
    sni: string;
    public_key: string;
    short_id: string;
    fingerprint: string;
    hy2_obfs: string;
    hy2_obfs_password: string;
    hy2_alpn: string;
    hy2_insecure: boolean;
    enabled: boolean;
    ssh_host: string;
    ssh_port: number;
    ssh_user: string;
    ssh_key_path: string;
    remote_add_script: string;
    remote_remove_script: string;
  };
  runtime: {
    health: string;
    xray_state: string;
    service_name?: string;
    protocol?: string;
    port_open?: boolean;
    vpn_reachable?: boolean;
    vpn_latency_ms?: number | null;
    vpn_latency_text?: string;
    established_connections?: number;
    active_devices_estimate?: number;
    load1?: number;
    load5?: number;
    load15?: number;
    mem_used_pct?: number | null;
    net_iface?: string;
    net_rx_bps?: number | null;
    net_tx_bps?: number | null;
    net_rx_text?: string;
    net_tx_text?: string;
    version?: string;
    uptime?: string;
    loadavg?: string;
    error?: string;
  };
  metrics: {
    total_configs: number;
    active_configs: number;
    active_users: number;
    active_devices: number;
    created_24h: number;
    revoked_24h: number;
    established_connections: number;
    live_active_devices_count: number;
  };
  latency_points: Array<{ ts: string; latency_ms: number; severity: string }>;
  load_points: Array<{ ts: string; load1: number; load5: number; load15: number; severity: string }>;
  connection_points: Array<{
    ts: string;
    established_connections: number;
    active_devices_estimate: number;
    severity: string;
  }>;
  daily_points: Array<{ day: string; count: number }>;
  live_active_devices: Array<{
    device_name: string;
    telegram_id: number;
    traffic_delta_bytes: number;
    traffic_delta_text: string;
    server_config_count: number;
  }>;
  live_active_devices_error: string | null;
  recent_configs: Array<{
    id: number;
    telegram_id: number;
    device_name: string;
    is_active: boolean;
    created_at: string;
    revoked_at: string;
  }>;
};

export type ServerRuntimeCheck = {
  health: string;
  xray_state: string;
  service_name?: string;
  protocol?: string;
  port_open: boolean;
  vpn_reachable: boolean;
  vpn_latency_ms?: number | null;
  vpn_latency_text: string;
  established_connections?: number;
  active_devices_estimate?: number;
  load1?: number;
  load5?: number;
  load15?: number;
  mem_used_pct?: number | null;
  net_iface?: string;
  net_rx_bps?: number | null;
  net_tx_bps?: number | null;
  net_rx_text?: string;
  net_tx_text?: string;
  version: string;
  uptime: string;
  loadavg: string;
  error?: string;
};

export function getAdminUsers(params: { q?: string; status?: string; page?: number; page_size?: number }) {
  return apiGetJson<Paged<AdminUser>>(`/users${query(params)}`);
}

export function getAdminUserDevices(telegramId: number) {
  return apiGetJson<UserDevicesResponse>(`/users/${telegramId}/devices`);
}

export function getAdminConfigs(params: { q?: string; status?: string; page?: number; page_size?: number }) {
  return apiGetJson<Paged<AdminConfig>>(`/configs${query(params)}`);
}

export function getAdminSubscriptions(params: { q?: string; status?: string; page?: number; page_size?: number }) {
  return apiGetJson<Paged<AdminSubscription>>(`/subscriptions${query(params)}`);
}

export function getAdminPayments(params: {
  q?: string;
  status?: string;
  kind?: string;
  page?: number;
  page_size?: number;
}) {
  return apiGetJson<Paged<AdminPayment>>(`/payments${query(params)}`);
}

export function getAdminPromos(params: { uses_q?: string; uses_page?: number; uses_page_size?: number }) {
  return apiGetJson<PromosResponse>(`/promos${query(params)}`);
}

export function getAdminGiveaways() {
  return apiGetJson<GiveawaysResponse>("/giveaways");
}

export function getAdminAudit(params: { q?: string; action?: string; page?: number; page_size?: number }) {
  return apiGetJson<AuditResponse>(`/audit${query(params)}`);
}

export function getAdminSettings() {
  return apiGetJson<AdminSettingsResponse>("/settings");
}

export function getAdminServers(params: { live?: number; fresh?: number } = {}) {
  return apiGetJson<AdminServersSnapshot>(`/servers${query(params)}`);
}

export function getAdminServerDetail(serverId: number, params: { live?: number; fresh?: number } = {}) {
  return apiGetJson<AdminServerDetail>(`/servers/${serverId}${query(params)}`);
}

export function getAdminServerRuntimeCheck(serverId: number) {
  return apiGetJson<ServerRuntimeCheck>(`/server/${serverId}/check`);
}
