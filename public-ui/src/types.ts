export type PublicConfig = {
  bot_url: string;
  brand: string;
  bot_username?: string;
  support_url?: string;
};

export type CabinetSection = "dashboard" | "subscription" | "balance" | "referrals" | "giveaways" | "help";
export type NoticeKind = "info" | "success" | "warn" | "error";

export type CabinetConfig = {
  id: number;
  server_name: string;
  protocol: string;
  device_name: string;
  vless_url: string;
  is_active: boolean;
  created_at: string;
};

export type CabinetSnapshot = {
  user: {
    telegram_id: number;
    username: string;
    balance_rub: number;
    pending_discount_promo_id: number | null;
    subscription_until: string | null;
    subscription_active: boolean;
    invited_count: number;
    referral_bonus_rub: number;
    configs: CabinetConfig[];
  };
  plans: Array<{ id: string; label: string; months: number; price_rub: number; badge: string; days: number }>;
  payment: { min_topup_rub: number; max_topup_rub: number };
  giveaways: Array<{ id: number; title: string; description: string; prize: string; kind: string; joined: boolean; participants: number }>;
  payments: Array<{ invoice_id: number; status: string; amount_rub: number; kind: string; created_at: string; paid_at: string | null; pay_url: string }>;
};

export type SubscriptionPreview = {
  metrics: {
    subscription_active: boolean;
    days_left: number;
    servers_count: number;
    devices_count: number;
    traffic_used_text: string;
    expires_text: string;
  };
  links: {
    subscription_url: string;
    raw_url: string;
    b64_url: string;
    stats_url: string;
    happ_import_url: string;
    happ_download_url: string;
  };
};

export type AppNotice = {
  id: number;
  kind: NoticeKind;
  title: string;
  body: string;
  read: boolean;
  created_at: number;
};