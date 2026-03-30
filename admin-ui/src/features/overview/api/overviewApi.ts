import { apiGetJson } from "../../../shared/api/httpClient";

export type OverviewSnapshot = {
  generated_at: string;
  summary: {
    total_users: number;
    active_subscriptions: number;
    total_servers: number;
    enabled_servers: number;
    total_configs: number;
    active_configs: number;
    total_invoices: number;
    paid_invoices: number;
    revenue_rub: number;
    total_balance_rub: number;
    total_ref_bonus_rub: number;
    connected_now: number;
    live_users_now: number;
    live_users_partial: boolean;
  };
  analytics?: {
    users?: {
      new_24h: number;
      new_7d: number;
      new_30d: number;
      blocked: number;
      with_active_configs: number;
      expiring_3d: number;
      expiring_7d: number;
    };
    monetization?: {
      paid_users_total: number;
      paid_users_30d: number;
      revenue_7d: number;
      revenue_30d: number;
    };
    top?: {
      spenders?: Array<{ telegram_id: number; username: string; total_rub: number }>;
      referrers?: Array<{ telegram_id: number; username: string; referrals: number; bonus_rub: number }>;
    };
  };
  servers?: Array<{
    id: number;
    name: string;
    enabled: boolean;
    protocol: string;
    host: string;
    port: number;
    active_clients: number;
    runtime: {
      health: string;
      xray_state: string;
      vpn_latency_text: string;
      established_connections?: number;
      error?: string;
    };
  }>;
  recent_configs?: Array<{
    id: number;
    server: string;
    telegram_id: number;
    device_name: string;
    is_active: boolean;
    created_at: string;
  }>;
  recent_payments?: Array<{
    invoice_id: number;
    telegram_id: number;
    amount_rub: number;
    kind: string;
    promo_code?: string;
    status: string;
    created_at: string;
    paid_at: string;
  }>;
};

export function getOverviewSnapshot(): Promise<OverviewSnapshot> {
  return apiGetJson<OverviewSnapshot>("/overview");
}
