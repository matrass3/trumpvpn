import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = { bot_url: string; brand: string; bot_username?: string; support_url?: string };
type CabinetSection = "dashboard" | "subscription" | "balance" | "referrals" | "giveaways" | "help";
type NoticeKind = "info" | "success" | "warn" | "error";

type CabinetConfig = {
  id: number;
  server_name: string;
  protocol: string;
  device_name: string;
  vless_url: string;
  is_active: boolean;
  created_at: string;
};

type CabinetSnapshot = {
  user: {
    telegram_id: number;
    username: string;
    balance_rub: number;
    pending_discount_promo_id: number | null;
    subscription_until: string | null;
    subscription_active: boolean;
    subscription_url?: string;
    invited_count: number;
    referral_bonus_rub: number;
    configs: CabinetConfig[];
  };
  plans: Array<{ id: string; label: string; months: number; price_rub: number; badge: string; days: number }>;
  payment: { min_topup_rub: number; max_topup_rub: number };
  giveaways: Array<{ id: number; title: string; description: string; prize: string; kind: string; joined: boolean; participants: number }>;
  fortune: {
    price_rub: number;
    can_spin: boolean;
    reason: string;
    balance_rub: number;
    subscription_active: boolean;
    prizes: Array<{ id: string; label: string; kind: string; value_int: number; weight: number; color: string; emoji: string }>;
    recent: Array<{
      id: number;
      price_rub: number;
      prize_id: string;
      prize_label: string;
      prize_kind: string;
      prize_value_int: number;
      reward_rub: number;
      reward_days: number;
      balance_before: number;
      balance_after: number;
      created_at: string;
    }>;
  };
  payments: Array<{ invoice_id: number; status: string; amount_rub: number; kind: string; created_at: string; paid_at: string | null; pay_url: string }>;
};

type SubscriptionPreview = {
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

type AppNotice = {
  id: number;
  kind: NoticeKind;
  title: string;
  body: string;
  count: number;
  read: boolean;
  created_at: number;
};

const NAV: Array<{ key: CabinetSection; title: string; icon: string }> = [
  { key: "dashboard", title: "Home", icon: "🏠" },
  { key: "subscription", title: "Subscription", icon: "✨" },
  { key: "balance", title: "Balance", icon: "💳" },
  { key: "referrals", title: "Referrals", icon: "👥" },
  { key: "giveaways", title: "Fortune", icon: "🎁" },
  { key: "help", title: "Help", icon: "❓" },
];

const GATEWAYS = [
  { code: "cryptopay", title: "CryptoPay" },
  { code: "platega", title: "Platega" },
  { code: "platega_card", title: "Platega Card" },
  { code: "platega_sbp", title: "Platega SBP" },
  { code: "platega_crypto", title: "Platega Crypto" },
  { code: "yoomoney", title: "YooMoney" },
];
const PUBLIC_SESSION_STORAGE_KEY = "trumpvpn_public_session";

function fmtRub(value: number | null | undefined) {
  return `${Intl.NumberFormat("ru-RU").format(Number(value || 0))} RUB`;
}

function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ru-RU");
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function getDaysLeft(value: string | null | undefined) {
  const end = parseDate(value);
  if (!end) return 0;
  const delta = end.getTime() - Date.now();
  if (delta <= 0) return 0;
  return Math.ceil(delta / 86400000);
}

function sanitizeError(raw: string) {
  const source = String(raw || "").trim();
  if (!source) return "Request failed";

  let extracted = source;
  try {
    const parsed = JSON.parse(source) as { detail?: unknown; message?: unknown; error?: unknown };
    if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
      extracted = parsed.detail.trim();
    } else if (parsed?.detail && typeof parsed.detail === "object" && typeof (parsed.detail as { message?: unknown }).message === "string") {
      extracted = String((parsed.detail as { message?: string }).message || "").trim();
    } else if (typeof parsed?.message === "string" && parsed.message.trim()) {
      extracted = parsed.message.trim();
    } else if (typeof parsed?.error === "string" && parsed.error.trim()) {
      extracted = parsed.error.trim();
    }
  } catch {
    extracted = source;
  }

  const text = extracted.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return "Request failed";

  if (/telegram user not found/i.test(text)) return "Telegram user not found. Re-open Mini App from the bot.";
  if (/signature mismatch|invalid init_data|expired/i.test(text)) return "Telegram session expired. Re-open Mini App from the bot.";
  if (/vpn revoke failed/i.test(text)) {
    const cfgMatch = text.match(/cfg#(\d+)/i);
    const cfgSuffix = cfgMatch ? ` (cfg #${cfgMatch[1]})` : "";
    if (/authentication failed/i.test(text)) return `Unable to revoke device${cfgSuffix}: SSH authentication failed.`;
    if (/jq: error|cannot iterate over null/i.test(text)) return `Unable to revoke device${cfgSuffix}: VPN node config issue.`;
    return `Unable to revoke device${cfgSuffix}. Try again later.`;
  }
  const insufficient = text.match(/insufficient balance\.?\s*need\s*(\d+)\s*rub,\s*missing\s*(\d+)\s*rub/i);
  if (insufficient) {
    const need = Number(insufficient[1] || 0);
    const missing = Number(insufficient[2] || 0);
    return `Insufficient balance: need ${fmtRub(need)}, missing ${fmtRub(missing)}.`;
  }

  if (/unauthorized|401/i.test(text)) return "Authorization required in Telegram Mini App.";
  if (/502|504|bad gateway|gateway timeout|gateway time-out/i.test(text)) return "Service is temporarily unavailable. Try again in 20-30 seconds.";
  return text.slice(0, 320);
}

function isAuthError(message: string) {
  const text = String(message || "").toLowerCase();
  return text.includes("authorization required in telegram mini app") || text.includes("unauthorized") || text.includes("401");
}

function extractMissingRub(message: string): number {
  const text = String(message || "");
  const match = text.match(/missing\s*([0-9\s]+)/i);
  if (!match) return 0;
  const amount = Number(match[1].replace(/\s+/g, ""));
  return Number.isFinite(amount) ? Math.max(0, amount) : 0;
}

function makeIdempotencyKey(prefix: string) {
  const safePrefix = String(prefix || "pay").replace(/[^a-z0-9_-]/gi, "").toLowerCase() || "pay";
  const rnd =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 16)
      : Math.random().toString(36).slice(2, 14);
  return `${safePrefix}-${Date.now()}-${rnd}`;
}

function pathFromSection(section: CabinetSection) {
  return section === "dashboard" ? "/cabinet" : `/cabinet/${section}`;
}

function sectionFromPath(pathname: string): CabinetSection {
  const clean = pathname.replace(/\/+$/, "");
  if (!clean || clean === "/cabinet") return "dashboard";
  if (!clean.startsWith("/cabinet/")) return "dashboard";
  const raw = clean.slice("/cabinet/".length);
  if (raw === "overview") return "dashboard";
  if (raw === "plans") return "subscription";
  if (raw === "account") return "referrals";
  if (raw === "dashboard" || raw === "subscription" || raw === "balance" || raw === "referrals" || raw === "giveaways" || raw === "help") return raw;
  return "dashboard";
}

function planLabel(plan: { label: string; months: number; days: number }) {
  const label = String(plan.label || "").trim();
  if (label && !label.includes("\uFFFD") && !/\?{3,}/.test(label)) return label;
  const m = plan.months > 0 ? plan.months : Math.max(1, Math.round(plan.days / 30));
  if (m === 1) return "1 month";
  if (m === 3) return "3 months";
  if (m === 6) return "6 months";
  if (m === 12) return "1 year";
  return `${m} months`;
}

function triggerImpact(style: "light" | "medium" | "heavy" = "light") {
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(style);
}

function triggerNotify(kind: "error" | "success" | "warning") {
  window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.(kind);
}

function openPaymentUrl(url: string): boolean {
  const clean = String(url || "").trim();
  if (!clean) return false;
  try {
    if (window.Telegram?.WebApp?.openLink) {
      window.Telegram.WebApp.openLink(clean, { try_instant_view: false });
      return true;
    }
  } catch {
    // Fallback below.
  }
  const win = window.open(clean, "_blank", "noopener,noreferrer");
  return Boolean(win);
}

function extractRawQueryParam(name: string): string {
  const sources: string[] = [];
  if (window.location.search.startsWith("?")) sources.push(window.location.search.slice(1));
  const hashRaw = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (hashRaw) {
    const hashQueryPos = hashRaw.indexOf("?");
    sources.push(hashQueryPos >= 0 ? hashRaw.slice(hashQueryPos + 1) : hashRaw);
  }
  for (const source of sources) {
    if (!source) continue;
    const parts = source.split("&");
    for (const item of parts) {
      if (!item) continue;
      const eqPos = item.indexOf("=");
      const key = eqPos >= 0 ? item.slice(0, eqPos) : item;
      if (key === name) return eqPos >= 0 ? item.slice(eqPos + 1) : "";
    }
  }
  return "";
}

function getTelegramMiniAppInitData() {
  const direct = String(window.Telegram?.WebApp?.initData || "").trim();
  if (direct) return direct;
  const raw = extractRawQueryParam("tgWebAppData") || extractRawQueryParam("initData");
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const sessionToken = String(window.localStorage.getItem(PUBLIC_SESSION_STORAGE_KEY) || "").trim();
  const miniAppInitData = getTelegramMiniAppInitData();
  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(sessionToken ? { "X-Public-Session": sessionToken } : {}),
      ...(miniAppInitData ? { "X-Telegram-Init-Data": miniAppInitData } : {}),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(sanitizeError((await response.text()).trim() || `HTTP ${response.status}`));
  }
  return (await response.json()) as T;
}

function trackEvent(event: string, meta: Record<string, unknown> = {}) {
  void fetch("/api/public/analytics/event", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ event, meta }),
  }).catch(() => undefined);
}

function shouldStopMiniAppRetry(errorMessage: string) {
  const text = String(errorMessage || "").toLowerCase();
  return (
    text.includes("signature mismatch") ||
    text.includes("expired") ||
    text.includes("invalid init_data") ||
    text.includes("telegram user not found")
  );
}

function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig>({
    bot_url: "https://t.me/trumpvlessbot",
    brand: "TrumpVPN",
    bot_username: "trumpvlessbot",
    support_url: "https://t.me/trumpvpnhelp",
  });

  useEffect(() => {
    void fetch("/api/public/config")
      .then(async (res) => (res.ok ? ((await res.json()) as Partial<PublicConfig>) : null))
      .then((payload) => {
        if (!payload) return;
        setConfig((prev) => ({
          bot_url: String(payload.bot_url || prev.bot_url),
          brand: String(payload.brand || prev.brand),
          bot_username: String(payload.bot_username || prev.bot_username || "trumpvlessbot"),
          support_url: String(payload.support_url || prev.support_url || "https://t.me/trumpvpnhelp"),
        }));
      })
      .catch(() => undefined);
  }, []);

  return config;
}

function LandingPage() {
  const config = usePublicConfig();

  return (
    <main className="landing-root">
      <div className="landing-card">
        <p className="landing-kicker">SECURE VPN SERVICE</p>
        <h1>{config.brand}</h1>
        <p>Fast VPN for phone and desktop. Subscription, balance and access keys in one cabinet.</p>
        <div className="landing-actions">
          <a className="ui-btn primary" href="/cabinet">
            Open Cabinet
          </a>
          <a className="ui-btn ghost" href={config.bot_url} target="_blank" rel="noreferrer noopener">
            Open Telegram Bot
          </a>
        </div>
      </div>
    </main>
  );
}

function SkeletonCabinet() {
  return (
    <section className="stack">
      <article className="panel skeleton-panel">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
      </article>
      <article className="panel skeleton-panel">
        <div className="skeleton-grid">
          <div className="skeleton skeleton-stat" />
          <div className="skeleton skeleton-stat" />
          <div className="skeleton skeleton-stat" />
        </div>
      </article>
      <article className="panel skeleton-panel">
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line short" />
      </article>
    </section>
  );
}

function noticeTitleByKind(kind: NoticeKind) {
  if (kind === "success") return "Success";
  if (kind === "warn") return "Warning";
  if (kind === "error") return "Error";
  return "Info";
}

function CabinetPage() {
  const config = usePublicConfig();
  const [section, setSection] = useState<CabinetSection>(() => sectionFromPath(window.location.pathname));
  const [snapshot, setSnapshot] = useState<CabinetSnapshot | null>(null);
  const [pending, setPending] = useState(true);
  const [unauthorized, setUnauthorized] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [topupAmount, setTopupAmount] = useState(500);
  const [topupGateway, setTopupGateway] = useState("cryptopay");
  const [promoCode, setPromoCode] = useState("");
  const [invoiceToCheck, setInvoiceToCheck] = useState(0);
  const [createdInvoice, setCreatedInvoice] = useState<{ invoice_id: number; pay_url: string } | null>(null);
  const [pendingInvoiceId, setPendingInvoiceId] = useState(0);
  const [pendingInvoiceChecks, setPendingInvoiceChecks] = useState(0);
  const [miniAppAuthPending, setMiniAppAuthPending] = useState(false);
  const [miniAppAuthError, setMiniAppAuthError] = useState("");
  const [notifications, setNotifications] = useState<AppNotice[]>([]);
  const [toasts, setToasts] = useState<AppNotice[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [protocolFilter, setProtocolFilter] = useState("all");
  const [revokeCandidate, setRevokeCandidate] = useState<CabinetConfig | null>(null);
  const [quickAmount, setQuickAmount] = useState(500);
  const [fortuneWheelDeg, setFortuneWheelDeg] = useState(0);
  const [fortuneLastPrizeId, setFortuneLastPrizeId] = useState("");
  const noticeSeq = useRef(0);
  const previousSnapshot = useRef<CabinetSnapshot | null>(null);
  const expiryMarker = useRef("");
  const authRetryAttempt = useRef(0);
  const authRetryTimer = useRef<number | null>(null);
  const authRetryStopped = useRef(false);
  const showNotificationsRef = useRef(false);
  const recentNoticeMap = useRef<Map<string, number>>(new Map());
  const authRefreshTimer = useRef<number | null>(null);
  const pendingInvoiceTimer = useRef<number | null>(null);
  const pendingInvoiceChecksRef = useRef(0);

  const pushNotice = useCallback((kind: NoticeKind, body: string, title?: string) => {
    const now = Date.now();
    const normalizedTitle = title || noticeTitleByKind(kind);
    const dedupeKey = `${kind}|${normalizedTitle}|${String(body || "").trim()}`;
    const prevTs = recentNoticeMap.current.get(dedupeKey) || 0;
    recentNoticeMap.current.set(dedupeKey, now);
    for (const [key, ts] of recentNoticeMap.current.entries()) {
      if (now - ts > 90000) recentNoticeMap.current.delete(key);
    }

    if (now - prevTs < 12000) {
      setNotifications((prev) => {
        const idx = prev.findIndex((item) => `${item.kind}|${item.title}|${item.body}` === dedupeKey);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          count: Math.min(99, (next[idx].count || 1) + 1),
          read: false,
          created_at: now,
        };
        return next;
      });
      return;
    }

    const id = ++noticeSeq.current;
    const entry: AppNotice = {
      id,
      kind,
      title: normalizedTitle,
      body,
      count: 1,
      read: false,
      created_at: now,
    };
    setNotifications((prev) => [entry, ...prev].slice(0, 30));
    if (!showNotificationsRef.current) {
      setToasts((prev) => [entry, ...prev].slice(0, 3));
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((item) => item.id !== id));
      }, 4200);
    }
  }, []);

  const unreadNotifications = useMemo(() => notifications.filter((item) => !item.read).length, [notifications]);

  const navigate = useCallback((next: CabinetSection) => {
    const nextPath = pathFromSection(next);
    if (window.location.pathname !== nextPath) window.history.pushState({}, "", nextPath);
    setSection(next);
  }, []);

  useEffect(() => {
    const onPop = () => setSection(sectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    showNotificationsRef.current = showNotifications;
    if (!showNotifications) return;
    setNotifications((prev) => prev.map((item) => ({ ...item, read: true })));
    setToasts([]);
  }, [showNotifications]);

  useEffect(() => {
    const onReady = () => {
      window.Telegram?.WebApp?.ready?.();
      window.Telegram?.WebApp?.expand?.();
    };
    onReady();
    if (window.Telegram?.WebApp) return;
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-web-app.js";
    script.async = true;
    script.onload = onReady;
    document.head.appendChild(script);
  }, []);

  useEffect(() => {
    const back = window.Telegram?.WebApp?.BackButton;
    if (!back) return;
    const handleBack = () => {
      if (section !== "dashboard") navigate("dashboard");
    };
    if (section === "dashboard") back.hide?.();
    else back.show?.();
    back.onClick?.(handleBack);
    return () => back.offClick?.(handleBack);
  }, [section, navigate]);

  const refreshSession = useCallback(async () => {
    try {
      const result = await apiJson<{ session_token?: string; ok?: boolean }>("/api/public/auth/session/refresh", {
        method: "POST",
      });
      const token = String(result?.session_token || "").trim();
      if (token) window.localStorage.setItem(PUBLIC_SESSION_STORAGE_KEY, token);
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    if (unauthorized) return;
    const schedule = () => {
      if (authRefreshTimer.current) window.clearTimeout(authRefreshTimer.current);
      authRefreshTimer.current = window.setTimeout(async () => {
        await refreshSession();
        schedule();
      }, 10 * 60 * 1000);
    };
    schedule();
    return () => {
      if (authRefreshTimer.current) {
        window.clearTimeout(authRefreshTimer.current);
        authRefreshTimer.current = null;
      }
    };
  }, [unauthorized, refreshSession]);

  const refresh = useCallback(async () => {
    setPending(true);
    try {
      const data = await apiJson<CabinetSnapshot>("/api/public/cabinet");
      setSnapshot(data);
      setUnauthorized(false);
      if (!invoiceToCheck && data.payments.length) setInvoiceToCheck(Number(data.payments[0].invoice_id || 0));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load cabinet";
      if (/unauthorized|401/i.test(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
      } else {
        pushNotice("error", msg);
      }
    } finally {
      setPending(false);
    }
  }, [invoiceToCheck, pushNotice]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!snapshot) return;
    const prev = previousSnapshot.current;
    if (prev) {
      const prevStatus = new Map(prev.payments.map((item) => [item.invoice_id, String(item.status || "").toLowerCase()]));
      for (const payment of snapshot.payments) {
        const currentStatus = String(payment.status || "").toLowerCase();
        const beforeStatus = prevStatus.get(payment.invoice_id);
        if (currentStatus === "paid" && beforeStatus && beforeStatus !== "paid") {
          pushNotice("success", `Payment #${payment.invoice_id} confirmed: ${fmtRub(payment.amount_rub)}`, "Payment");
          trackEvent("invoice_paid", { invoice_id: payment.invoice_id, amount_rub: payment.amount_rub, source: "snapshot_diff" });
          triggerNotify("success");
        }
      }
    }
    const daysLeft = getDaysLeft(snapshot.user.subscription_until);
    if (snapshot.user.subscription_active && daysLeft > 0 && daysLeft <= 3) {
      const marker = `${snapshot.user.subscription_until || ""}:${daysLeft}`;
      if (expiryMarker.current !== marker) {
        expiryMarker.current = marker;
        pushNotice("warn", `Subscription expires in ${daysLeft} day(s).`, "Subscription");
      }
    }
    previousSnapshot.current = snapshot;
  }, [snapshot, pushNotice]);

  async function withAction(action: () => Promise<void>) {
    setActionPending(true);
    try {
      await action();
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Action failed";
      if (isAuthError(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
        setMiniAppAuthError("Refreshing session via Telegram Mini App...");
        authRetryStopped.current = false;
        authRetryAttempt.current = 0;
        return;
      }
      pushNotice("error", msg);
      triggerNotify("error");
    } finally {
      setActionPending(false);
    }
  }

  const loginWithMiniApp = useCallback(
    async (initDataRaw: string, silent = false) => {
      const initData = String(initDataRaw || "").trim();
      if (!initData) return false;
      try {
        setMiniAppAuthPending(true);
        setMiniAppAuthError("");
        const auth = await apiJson<{ ok: boolean; session_token?: string }>("/api/public/auth/miniapp", {
          method: "POST",
          body: JSON.stringify({ init_data: initData }),
        });
        const sessionToken = String(auth.session_token || "").trim();
        if (sessionToken) {
          window.localStorage.setItem(PUBLIC_SESSION_STORAGE_KEY, sessionToken);
        }
        await refresh();
        authRetryAttempt.current = 0;
        authRetryStopped.current = false;
        if (!silent) {
          pushNotice("success", "Logged in via Telegram Mini App.", "Telegram");
          triggerNotify("success");
        }
        return true;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Mini App auth failed";
        setMiniAppAuthError(msg);
        if (shouldStopMiniAppRetry(msg)) {
          authRetryStopped.current = true;
        }
        if (!silent) {
          pushNotice("warn", msg, "Telegram");
        }
        return false;
      } finally {
        setMiniAppAuthPending(false);
      }
    },
    [pushNotice, refresh]
  );

  useEffect(() => {
    if (!unauthorized || miniAppAuthPending || authRetryStopped.current) return;
    let cancelled = false;

    const run = async (silent = true) => {
      const initData = getTelegramMiniAppInitData();
      if (!initData) {
        authRetryAttempt.current += 1;
        if (authRetryAttempt.current > 20) {
          setMiniAppAuthError("Unable to read Telegram Mini App session. Re-open Mini App from bot.");
          authRetryStopped.current = true;
          return false;
        }
        setMiniAppAuthError("Waiting for Telegram Mini App session...");
        authRetryTimer.current = window.setTimeout(() => {
          if (!cancelled) void run(true);
        }, 800);
        return false;
      }
      const ok = await loginWithMiniApp(initData, silent);
      if (ok || authRetryStopped.current || cancelled) return ok;
      authRetryAttempt.current += 1;
      if (authRetryAttempt.current > 7) {
        authRetryStopped.current = true;
        return false;
      }
      const delayMs = Math.min(15000, 500 * 2 ** authRetryAttempt.current);
      authRetryTimer.current = window.setTimeout(() => {
        if (!cancelled) {
          void run(true);
        }
      }, delayMs);
      return false;
    };

    void run(true);

    return () => {
      cancelled = true;
      if (authRetryTimer.current) {
        window.clearTimeout(authRetryTimer.current);
        authRetryTimer.current = null;
      }
    };
  }, [unauthorized, miniAppAuthPending, loginWithMiniApp]);

  async function logout() {
    await withAction(async () => {
      await apiJson("/api/public/auth/logout", { method: "POST" });
      window.localStorage.removeItem(PUBLIC_SESSION_STORAGE_KEY);
      setUnauthorized(true);
      setSnapshot(null);
      setShowNotifications(false);
      setNotifications([]);
      setToasts([]);
      authRetryAttempt.current = 0;
      authRetryStopped.current = false;
      navigate("dashboard");
    });
  }

  async function renewFromBalance() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/renew-from-balance", { method: "POST" });
      trackEvent("renew_from_balance");
      pushNotice("success", "Subscription renewed.");
      triggerNotify("success");
    });
  }

  async function claimWelcome() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/welcome/claim", { method: "POST" });
      trackEvent("welcome_bonus_claimed");
      pushNotice("success", "Welcome bonus processed.");
      triggerNotify("success");
    });
  }

  async function applyPromo(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!promoCode.trim()) throw new Error("Enter promo code");
      await apiJson("/api/public/cabinet/promo/apply", { method: "POST", body: JSON.stringify({ code: promoCode.trim() }) });
      trackEvent("promo_applied", { code: promoCode.trim() });
      setPromoCode("");
      pushNotice("success", "Promo applied.");
      triggerNotify("success");
    });
  }
  const checkInvoiceStatus = useCallback(
    async (invoiceId: number, options?: { silent?: boolean; source?: "manual" | "auto" }) => {
      const id = Number(invoiceId || 0);
      if (!id) throw new Error("Enter invoice ID");
      const source = options?.source || "manual";
      const silent = Boolean(options?.silent);
      const result = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", {
        method: "POST",
        body: JSON.stringify({ invoice_id: id }),
      });
      const statusValue = String(result.status || "").toLowerCase();
      trackEvent("invoice_checked", { invoice_id: id, status: statusValue, source });
      if (statusValue === "paid") {
        trackEvent("invoice_paid", { invoice_id: id, source });
        pendingInvoiceChecksRef.current = 0;
        setPendingInvoiceChecks(0);
        setPendingInvoiceId(0);
        triggerNotify("success");
        if (!silent) pushNotice("success", `Payment #${id} confirmed.`, "Payment");
        await refresh();
        return statusValue;
      }
      if (statusValue === "expired" || statusValue === "cancelled") {
        pendingInvoiceChecksRef.current = 0;
        setPendingInvoiceChecks(0);
        setPendingInvoiceId(0);
        if (!silent) pushNotice("warn", `Payment #${id} is ${statusValue}.`, "Payment");
        return statusValue;
      }
      if (!silent) pushNotice("info", `Payment #${id}: ${result.status}`, "Payment");
      return statusValue;
    },
    [pushNotice, refresh]
  );

  async function createInvoice(event: FormEvent) {
    event.preventDefault();
    triggerImpact("medium");
    await withAction(async () => {
      const idemKey = makeIdempotencyKey("topup");
      const result = await apiJson<{ invoice_id: number; pay_url: string; idempotent_reuse?: boolean }>("/api/public/cabinet/payments/create", {
        method: "POST",
        body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway, idempotency_key: idemKey }),
      });
      setCreatedInvoice(result);
      setInvoiceToCheck(result.invoice_id);
      setPendingInvoiceId(result.invoice_id);
      pendingInvoiceChecksRef.current = 0;
      setPendingInvoiceChecks(0);
      trackEvent("invoice_created", {
        invoice_id: result.invoice_id,
        amount_rub: Number(topupAmount || 0),
        gateway: topupGateway,
        idempotent_reuse: Boolean(result.idempotent_reuse),
      });
      const opened = openPaymentUrl(result.pay_url);
      trackEvent("pay_link_opened", { invoice_id: result.invoice_id, source: "auto", opened });
      if (opened) {
        pushNotice("success", `Payment link for invoice #${result.invoice_id} opened.`, "Payment");
        triggerNotify("success");
      } else {
        pushNotice("warn", `Invoice #${result.invoice_id} created. Open payment link manually.`, "Payment");
      }
    });
  }

  async function checkInvoice(invoiceId?: number) {
    await withAction(async () => {
      const id = Number(invoiceId || invoiceToCheck || 0);
      await checkInvoiceStatus(id, { source: "manual", silent: false });
    });
  }

  useEffect(() => {
    return () => {
      if (pendingInvoiceTimer.current) {
        window.clearTimeout(pendingInvoiceTimer.current);
        pendingInvoiceTimer.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!pendingInvoiceId || unauthorized) return;
    let cancelled = false;

    const stopPolling = () => {
      if (pendingInvoiceTimer.current) {
        window.clearTimeout(pendingInvoiceTimer.current);
        pendingInvoiceTimer.current = null;
      }
      pendingInvoiceChecksRef.current = 0;
      setPendingInvoiceChecks(0);
    };

    const schedule = (delayMs: number) => {
      if (pendingInvoiceTimer.current) window.clearTimeout(pendingInvoiceTimer.current);
      pendingInvoiceTimer.current = window.setTimeout(() => {
        void tick();
      }, delayMs);
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const status = await checkInvoiceStatus(pendingInvoiceId, { source: "auto", silent: true });
        if (status === "paid" || status === "expired" || status === "cancelled") {
          stopPolling();
          return;
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Invoice check failed";
        if (isAuthError(msg)) {
          setUnauthorized(true);
          setSnapshot(null);
          setMiniAppAuthError("Refreshing session via Telegram Mini App...");
          stopPolling();
          return;
        }
        if (pendingInvoiceChecksRef.current === 0) {
          pushNotice("warn", "Payment status check is temporary unavailable. Retrying...");
        }
      }

      pendingInvoiceChecksRef.current += 1;
      setPendingInvoiceChecks(pendingInvoiceChecksRef.current);
      if (pendingInvoiceChecksRef.current >= 40) {
        pushNotice("warn", `Payment #${pendingInvoiceId} is still pending. You can check manually.`, "Payment");
        setPendingInvoiceId(0);
        stopPolling();
        return;
      }
      schedule(5000);
    };

    schedule(5000);
    return () => {
      cancelled = true;
      if (pendingInvoiceTimer.current) {
        window.clearTimeout(pendingInvoiceTimer.current);
        pendingInvoiceTimer.current = null;
      }
    };
  }, [pendingInvoiceId, unauthorized, checkInvoiceStatus, pushNotice]);

  async function buyPlan(planId: string) {
    triggerImpact("medium");
    setActionPending(true);
    try {
      trackEvent("plan_purchase_requested", { plan_id: planId });
      await apiJson("/api/public/cabinet/purchase-plan", { method: "POST", body: JSON.stringify({ plan_id: planId }) });
      pushNotice("success", "Plan purchased.");
      triggerNotify("success");
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Plan purchase failed";
      if (isAuthError(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
        setMiniAppAuthError("Refreshing session via Telegram Mini App...");
        return;
      }
      if (/insufficient balance/i.test(msg)) {
        const missing = extractMissingRub(msg);
        const suggested = Math.max(
          snapshot?.payment.min_topup_rub || 100,
          Math.min(snapshot?.payment.max_topup_rub || 200000, missing > 0 ? missing : quickAmount || 500)
        );
        setQuickAmount(suggested);
        setTopupAmount(suggested);
        navigate("balance");
        pushNotice("warn", `Not enough balance. Top up ${fmtRub(suggested)} to continue.`, "Payment");
        triggerNotify("warning");
      } else {
        pushNotice("error", msg);
        triggerNotify("error");
      }
    } finally {
      setActionPending(false);
    }
  }

  async function joinGiveaway(giveawayId: number) {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/giveaways/join", { method: "POST", body: JSON.stringify({ giveaway_id: giveawayId }) });
      trackEvent("giveaway_joined", { giveaway_id: giveawayId });
      pushNotice("success", "You joined the giveaway.");
      triggerNotify("success");
    });
  }

  async function spinFortuneWheel() {
    if (!snapshot) return;
    triggerImpact("heavy");
    setActionPending(true);
    try {
      const result = await apiJson<{
        ok: boolean;
        result: { prize_id: string; prize_label: string; reward_rub: number; reward_days: number };
      }>("/api/public/cabinet/fortune/spin", { method: "POST" });
      const prizes = snapshot.fortune?.prizes || [];
      const winnerId = String(result?.result?.prize_id || "");
      const winnerIndex = Math.max(0, prizes.findIndex((item) => String(item.id || "") === winnerId));
      const segAngle = prizes.length > 0 ? 360 / prizes.length : 360;
      const stopOffset = ((360 - (winnerIndex + 0.5) * segAngle) % 360 + 360) % 360;
      setFortuneWheelDeg((prev) => prev + 5 * 360 + stopOffset);
      setFortuneLastPrizeId(winnerId);
      trackEvent("fortune_spin", { prize_id: winnerId, reward_rub: result?.result?.reward_rub || 0, reward_days: result?.result?.reward_days || 0 });
      if ((result?.result?.reward_rub || 0) > 0) {
        pushNotice("success", `You won ${fmtRub(result.result.reward_rub)}.`, "Fortune");
      } else if ((result?.result?.reward_days || 0) > 0) {
        pushNotice("success", `You won ${result.result.reward_days} subscription day(s).`, "Fortune");
      } else {
        pushNotice("info", `Prize: ${result?.result?.prize_label || "Try next time"}.`, "Fortune");
      }
      triggerNotify("success");
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Spin failed";
      if (isAuthError(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
      } else {
        pushNotice("error", msg, "Fortune");
        triggerNotify("error");
      }
    } finally {
      setActionPending(false);
    }
  }

  async function doRevokeConfig(configId: number) {
    await withAction(async () => {
      const result = await apiJson<{ status: string; revoked_count?: number; revoked_mode?: string; failed_count?: number }>("/api/public/cabinet/configs/revoke", {
        method: "POST",
        body: JSON.stringify({ config_id: configId }),
      });
      const localOnly = String(result.revoked_mode || "") === "local_only";
      trackEvent("device_revoked", {
        config_id: configId,
        revoked_count: result.revoked_count || 0,
        failed_count: result.failed_count || 0,
        mode: localOnly ? "local_only" : "remote",
      });
      if (localOnly) {
        pushNotice("warn", "Device disabled locally. Remote server is unavailable now.", "Devices");
        triggerNotify("warning");
      } else {
        pushNotice("success", `Device access revoked (${result.revoked_count || 0}).`);
        triggerNotify("success");
      }
    });
  }

  async function copyText(value: string) {
    triggerImpact("light");
    try {
      await navigator.clipboard.writeText(value);
      trackEvent("copy_text", { size: String(value || "").length });
      pushNotice("success", "Copied.");
      triggerNotify("success");
    } catch {
      pushNotice("error", "Copy failed");
      triggerNotify("error");
    }
  }

  const username = snapshot?.user.username || `id${snapshot?.user.telegram_id || ""}`;
  const daysLeft = getDaysLeft(snapshot?.user.subscription_until);
  const accessLink = String(snapshot?.user.subscription_url || "").trim();
  const happAccessLink = useMemo(() => {
    if (!accessLink) return "";
    try {
      const parsed = new URL(accessLink);
      parsed.searchParams.set("fmt", "b64");
      parsed.searchParams.set("preview", "0");
      parsed.searchParams.set("pool", "all");
      return parsed.toString();
    } catch {
      return accessLink;
    }
  }, [accessLink]);
  const botRefLink = `${config.bot_url}?start=ref${snapshot?.user.telegram_id || ""}`;
  const cabinetRefLink = `${window.location.origin}/cabinet?ref=${snapshot?.user.telegram_id || ""}`;
  const activeConfigs = (snapshot?.user.configs || []).filter((cfg) => cfg.is_active);
  const protocolOptions = useMemo(() => Array.from(new Set(activeConfigs.map((cfg) => String(cfg.protocol || "").toLowerCase()))).sort(), [activeConfigs]);
  const filteredConfigs = useMemo(() => {
    const q = deviceFilter.trim().toLowerCase();
    return activeConfigs.filter((cfg) => {
      if (protocolFilter !== "all" && String(cfg.protocol || "").toLowerCase() !== protocolFilter) return false;
      if (!q) return true;
      const hay = `${cfg.device_name} ${cfg.server_name} ${cfg.protocol}`.toLowerCase();
      return hay.includes(q);
    });
  }, [activeConfigs, deviceFilter, protocolFilter]);
  const paidPaymentsCount = useMemo(() => snapshot?.payments.filter((p) => String(p.status || "").toLowerCase() === "paid").length || 0, [snapshot]);
  const revokeTargetsCount = useMemo(() => {
    if (!revokeCandidate) return 0;
    return activeConfigs.filter((cfg) => cfg.device_name === revokeCandidate.device_name).length;
  }, [activeConfigs, revokeCandidate]);
  const quickTopupValues = useMemo(() => {
    const min = Math.max(1, snapshot?.payment.min_topup_rub || 100);
    const max = Math.max(min, snapshot?.payment.max_topup_rub || 200000);
    const raw = [quickAmount, 300, 500, 1000, 2000];
    return Array.from(new Set(raw.map((item) => Math.min(max, Math.max(min, Number(item || 0)))))).sort((a, b) => a - b);
  }, [snapshot?.payment.min_topup_rub, snapshot?.payment.max_topup_rub, quickAmount]);
  const fortune = snapshot?.fortune;
  const fortunePrizes = fortune?.prizes || [];
  const fortuneRecent = fortune?.recent || [];
  const fortuneSegCount = Math.max(1, fortunePrizes.length || 1);
  const fortuneEmojiRadius = 104;
  const fortuneGradient = useMemo(() => {
    if (!fortunePrizes.length) return "conic-gradient(from -90deg, #1f2f4e 0deg 360deg)";
    const seg = 360 / fortunePrizes.length;
    const chunks = fortunePrizes.map((item, idx) => {
      const start = idx * seg;
      const end = (idx + 1) * seg;
      return `${item.color || "#64748b"} ${start}deg ${end}deg`;
    });
    return `conic-gradient(from -90deg, ${chunks.join(", ")})`;
  }, [fortunePrizes]);
  const fortuneActivePrize = useMemo(() => {
    if (!fortuneLastPrizeId) return null;
    return fortunePrizes.find((item) => String(item.id || "") === fortuneLastPrizeId) || null;
  }, [fortunePrizes, fortuneLastPrizeId]);

  return (
    <main className="cabinet-root">
      <div className="mobile-shell">
        <header className="mobile-topbar compact">
          <div className="mobile-brand">{config.brand}</div>
          <div className="top-actions">
            <button className="chip-btn notif-btn" type="button" onClick={() => setShowNotifications((prev) => !prev)} aria-label="Notifications">
              Alerts
              {unreadNotifications > 0 ? <span className="badge">{unreadNotifications}</span> : null}
            </button>
            {snapshot ? (
              <button className="chip-btn" type="button" onClick={() => void logout()} disabled={actionPending}>
                Logout
              </button>
            ) : null}
          </div>
        </header>

        <div className="toasts">
          {toasts.map((item) => (
            <div key={item.id} className={`toast ${item.kind === "error" ? "err" : item.kind === "warn" ? "warn" : "ok"}`}>
              <strong>{item.title}</strong>
              <span>{item.body}</span>
            </div>
          ))}
        </div>

        {showNotifications ? (
          <section className="panel notifications-panel">
            <div className="panel-head">
              <h3>Notifications</h3>
              <button className="chip-btn" type="button" onClick={() => setNotifications([])}>
                Clear
              </button>
            </div>
            <div className="notifications-list">
              {notifications.map((item) => (
                <article key={item.id} className={`notification-item ${item.read ? "read" : ""}`}>
                  <div className="notification-title">{item.title}</div>
                  <div className="notification-body">{item.body}</div>
                  <time>{new Date(item.created_at).toLocaleTimeString("ru-RU")}</time>
                </article>
              ))}
              {!notifications.length ? <div className="empty">No notifications.</div> : null}
            </div>
          </section>
        ) : null}

        {!pending && unauthorized ? (
          <section className="panel">
            <h2>Telegram Mini App Required</h2>
            <p>{miniAppAuthPending ? "Authorizing via Telegram Mini App..." : miniAppAuthError || "Open this page from Telegram bot Mini App."}</p>
            <div className="action-row">
              <a className="ui-btn primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
                Open bot and launch Mini App
              </a>
            </div>
          </section>
        ) : null}

        {pending && !snapshot ? <SkeletonCabinet /> : null}

        {snapshot ? (
          <>
            <section className="hero panel">
              <div className="hero-row">
                <div>
                  <h1>Welcome, {username}!</h1>
                  <p>{snapshot.user.subscription_active ? `Active until ${fmtDate(snapshot.user.subscription_until)}` : "No active subscription"}</p>
                </div>
                <div className="hero-badges">
                  <span className={`status-pill ${snapshot.user.subscription_active ? "ok" : "off"}`}>{snapshot.user.subscription_active ? "Active" : "Inactive"}</span>
                  <span className="status-pill neutral">{fmtRub(snapshot.user.balance_rub)}</span>
                </div>
              </div>
            </section>

            {section === "dashboard" ? (
              <section className="stack">
                <article className="panel trial-card">
                  <h2>{snapshot.user.subscription_active ? "Subscription active" : "Free trial available"}</h2>
                  <p>{snapshot.user.subscription_active ? "Your account is active and ready." : "Try VPN with fast setup in Telegram."}</p>
                  <div className="numbers">
                    <div>
                      <strong>{daysLeft}</strong>
                      <span>days</span>
                    </div>
                    <div>
                      <strong>{activeConfigs.length}</strong>
                      <span>keys</span>
                    </div>
                    <div>
                      <strong>{snapshot.user.invited_count}</strong>
                      <span>referrals</span>
                    </div>
                  </div>
                  <div className="action-row">
                    <button className="ui-btn primary" type="button" onClick={() => void renewFromBalance()} disabled={actionPending}>
                      Renew from balance
                    </button>
                    <button className="ui-btn ghost" type="button" onClick={() => void claimWelcome()} disabled={actionPending}>
                      Claim welcome bonus
                    </button>
                  </div>
                </article>

                <div className="double-grid">
                  <article className="panel mini-card">
                    <h3>Balance</h3>
                    <strong>{fmtRub(snapshot.user.balance_rub)}</strong>
                    <button className="link-btn" type="button" onClick={() => navigate("balance")}>
                      Open balance
                    </button>
                  </article>
                  <article className="panel mini-card">
                    <h3>Payments</h3>
                    <strong>{paidPaymentsCount}</strong>
                    <button className="link-btn" type="button" onClick={() => navigate("subscription")}>
                      Open subscription
                    </button>
                  </article>
                </div>

                <article className="panel">
                  <h3>Quick tools</h3>
                  <div className="action-row">
                    {accessLink ? (
                      <button className="ui-btn ghost" type="button" onClick={() => void copyText(happAccessLink || accessLink)}>
                        Copy access link
                      </button>
                    ) : null}
                    <button className="ui-btn ghost" type="button" onClick={() => navigate("help")}>
                      Open help center
                    </button>
                    <button className="ui-btn ghost" type="button" onClick={() => void refresh()} disabled={pending || actionPending}>
                      Refresh data
                    </button>
                  </div>
                </article>
              </section>
            ) : null}

            {section === "subscription" ? (
              <section className="stack">
                <article className="panel">
                  <h2>Subscription</h2>
                  <p>{snapshot.user.subscription_active ? `Active until ${fmtDate(snapshot.user.subscription_until)}` : "You do not have an active subscription."}</p>
                </article>

                <article className="panel plan-list">
                  <h3>Choose plan</h3>
                  {snapshot.plans.map((plan) => (
                    <div key={plan.id} className="plan-row">
                      <div>
                        <strong>{planLabel(plan)}</strong>
                        <small>{plan.days} days</small>
                      </div>
                      <div className="plan-row-actions">
                        <span>{fmtRub(plan.price_rub)}</span>
                        <button className="ui-btn ghost" type="button" onClick={() => void buyPlan(plan.id)} disabled={actionPending}>
                          Buy
                        </button>
                      </div>
                    </div>
                  ))}
                </article>

                <article className="panel">
                  <div className="panel-head">
                    <h3>Manage devices</h3>
                    <small>{filteredConfigs.length} found</small>
                  </div>
                  <div className="device-filters">
                    <input
                      className="input"
                      value={deviceFilter}
                      placeholder="Search by device or server"
                      onChange={(event) => setDeviceFilter(event.target.value)}
                    />
                    <select className="input" value={protocolFilter} onChange={(event) => setProtocolFilter(event.target.value)}>
                      <option value="all">All protocols</option>
                      {protocolOptions.map((item) => (
                        <option key={item} value={item}>
                          {item.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="devices-list">
                    {filteredConfigs.map((cfg) => (
                      <article key={cfg.id} className="device-item">
                        <div>
                          <strong>{cfg.device_name}</strong>
                          <small>
                            {cfg.server_name} · {cfg.protocol.toUpperCase()}
                          </small>
                          <small>Created: {fmtDate(cfg.created_at)}</small>
                        </div>
                        <div className="action-row">
                          <button className="ui-btn ghost small" type="button" onClick={() => void copyText(happAccessLink || accessLink || cfg.vless_url)}>
                            Copy access link
                          </button>
                          <button className="ui-btn ghost small danger" type="button" onClick={() => setRevokeCandidate(cfg)} disabled={actionPending}>
                            Remove
                          </button>
                        </div>
                      </article>
                    ))}
                    {!filteredConfigs.length ? <div className="empty">No active devices match the filter.</div> : null}
                  </div>
                </article>
              </section>
            ) : null}

            {section === "balance" ? (
              <section className="stack">
                <article className="panel balance-panel">
                  <h2>Current balance</h2>
                  <div className="balance-value">{fmtRub(snapshot.user.balance_rub)}</div>
                </article>

                <article className="panel">
                  <h3>Promo code</h3>
                  <form className="inline-form" onSubmit={(event) => void applyPromo(event)}>
                    <input className="input" value={promoCode} placeholder="Enter promo code" onChange={(event) => setPromoCode(event.target.value)} />
                    <button className="ui-btn primary" type="submit" disabled={actionPending}>
                      Activate
                    </button>
                  </form>
                </article>

                <article className="panel">
                  <h3>Top up balance</h3>
                  <div className="quick-amounts">
                    {quickTopupValues.map((amount) => (
                      <button
                        key={amount}
                        className={`chip-btn ${Number(topupAmount || 0) === amount ? "active" : ""}`}
                        type="button"
                        onClick={() => {
                          triggerImpact("light");
                          setTopupAmount(amount);
                          setQuickAmount(amount);
                        }}
                      >
                        {fmtRub(amount)}
                      </button>
                    ))}
                  </div>
                  <form className="topup-form" onSubmit={(event) => void createInvoice(event)}>
                    <label>
                      Amount (RUB)
                      <input
                        className="input"
                        type="number"
                        min={snapshot.payment.min_topup_rub}
                        max={snapshot.payment.max_topup_rub}
                        value={topupAmount}
                        onChange={(event) => setTopupAmount(Number(event.target.value || 0))}
                      />
                    </label>
                    <label>
                      Payment method
                      <select className="input" value={topupGateway} onChange={(event) => setTopupGateway(event.target.value)}>
                        {GATEWAYS.map((g) => (
                          <option key={g.code} value={g.code}>
                            {g.title}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="ui-btn primary" type="submit" disabled={actionPending}>
                      Top up
                    </button>
                  </form>

                  {createdInvoice ? (
                    <div className="invoice-box">
                      <p>Invoice #{createdInvoice.invoice_id}</p>
                      {pendingInvoiceId === createdInvoice.invoice_id ? (
                        <p className="muted-text">Waiting for payment confirmation... check #{pendingInvoiceChecks}/40</p>
                      ) : null}
                      <div className="action-row">
                        <button
                          className="ui-btn ghost"
                          type="button"
                          onClick={() => {
                            triggerImpact("medium");
                            const opened = openPaymentUrl(createdInvoice.pay_url);
                            trackEvent("pay_link_opened", { invoice_id: createdInvoice.invoice_id, source: "manual", opened });
                            if (!opened) {
                              pushNotice("warn", "Unable to open payment link automatically.");
                            }
                          }}
                        >
                          Open payment link
                        </button>
                        <button className="ui-btn ghost" type="button" onClick={() => void checkInvoice(createdInvoice.invoice_id)} disabled={actionPending}>
                          Check status
                        </button>
                      </div>
                    </div>
                  ) : null}
                </article>
              </section>
            ) : null}

            {section === "referrals" ? (
              <section className="stack">
                <article className="panel">
                  <h2>Referral program</h2>
                  <div className="double-grid">
                    <div className="stat-box">
                      <span>Total referrals</span>
                      <strong>{snapshot.user.invited_count}</strong>
                    </div>
                    <div className="stat-box">
                      <span>Total earnings</span>
                      <strong>{fmtRub(snapshot.user.referral_bonus_rub)}</strong>
                    </div>
                  </div>
                </article>

                <article className="panel">
                  <h3>Your referral links</h3>
                  <div className="ref-link-row">
                    <input className="input" value={botRefLink} readOnly />
                    <button className="ui-btn primary" type="button" onClick={() => void copyText(botRefLink)}>
                      Copy
                    </button>
                  </div>
                  <div className="ref-link-row">
                    <input className="input" value={cabinetRefLink} readOnly />
                    <button className="ui-btn ghost" type="button" onClick={() => void copyText(cabinetRefLink)}>
                      Copy
                    </button>
                  </div>
                </article>

                <article className="panel">
                  <h3>Recent payments</h3>
                  <div className="payments-list">
                    {snapshot.payments.slice(0, 8).map((p) => (
                      <div key={p.invoice_id} className="payment-item">
                        <span>#{p.invoice_id}</span>
                        <span>{fmtRub(p.amount_rub)}</span>
                        <span>{p.status}</span>
                      </div>
                    ))}
                    {!snapshot.payments.length ? <div className="empty">No payments yet.</div> : null}
                  </div>
                </article>
              </section>
            ) : null}

            {section === "giveaways" ? (
              <section className="stack">
                <article className="panel">
                  <h2>Fortune Wheel</h2>
                  <p>Spin cost: {fmtRub(fortune?.price_rub || 19)}. Prize is credited instantly.</p>
                </article>
                <article className="panel fortune-panel">
                  <div className="fortune-wheel-wrap">
                    <div className="fortune-pointer" />
                    <div className="fortune-wheel" style={{ backgroundImage: fortuneGradient, transform: `rotate(${fortuneWheelDeg}deg)` }}>
                      {fortunePrizes.map((item, idx) => {
                        const segAngle = 360 / fortuneSegCount;
                        const angle = -90 + idx * segAngle + segAngle / 2;
                        return (
                          <span
                            key={item.id}
                            className="fortune-segment-emoji"
                            style={{ transform: `translate(-50%, -50%) rotate(${angle}deg) translateY(-${fortuneEmojiRadius}px) rotate(${-angle}deg)` }}
                          >
                            {item.emoji || "🎁"}
                          </span>
                        );
                      })}
                      {Array.from({ length: fortuneSegCount }).map((_, idx) => (
                        <span
                          key={idx}
                          className="fortune-mark"
                          style={{ transform: `rotate(${-90 + (360 / fortuneSegCount) * idx}deg)` }}
                        />
                      ))}
                    </div>
                    <div className="fortune-center">SPIN</div>
                  </div>
                  <div className="fortune-meta">
                    <div className="status-pill neutral">Balance: {fmtRub(snapshot.user.balance_rub)}</div>
                    <div className={`status-pill ${snapshot.user.subscription_active ? "ok" : "off"}`}>
                      {snapshot.user.subscription_active ? "Subscription active" : "Subscription inactive"}
                    </div>
                  </div>
                  {fortune?.reason ? <p className="muted-text">{fortune.reason}</p> : null}
                  <div className="action-row">
                    <button className="ui-btn primary" type="button" onClick={() => void spinFortuneWheel()} disabled={actionPending || !fortune?.can_spin}>
                      Spin for {fmtRub(fortune?.price_rub || 19)}
                    </button>
                    <button className="ui-btn ghost" type="button" onClick={() => navigate("balance")}>
                      Top up balance
                    </button>
                  </div>
                  {fortuneActivePrize ? (
                    <p className="muted-text">
                      Last prize: <strong>{fortuneActivePrize.label}</strong>
                    </p>
                  ) : null}
                </article>
                <article className="panel">
                  <h3>Prize pool</h3>
                  <div className="fortune-prize-list">
                    {fortunePrizes.map((item) => (
                      <div key={item.id} className="fortune-prize-row">
                        <span className="fortune-prize-dot" style={{ background: item.color }} />
                        <span>{item.emoji || "🎁"} {item.label}</span>
                      </div>
                    ))}
                    {!fortunePrizes.length ? <div className="empty">No prize configuration.</div> : null}
                  </div>
                </article>
                <article className="panel">
                  <h3>Recent spins</h3>
                  <div className="payments-list">
                    {fortuneRecent.slice(0, 8).map((item) => (
                      <div key={item.id} className="payment-item">
                        <span>{item.prize_label}</span>
                        <span>{item.reward_rub > 0 ? `+${fmtRub(item.reward_rub)}` : item.reward_days > 0 ? `+${item.reward_days} day(s)` : "No reward"}</span>
                        <span>{item.created_at}</span>
                      </div>
                    ))}
                    {!fortuneRecent.length ? <div className="empty">No spins yet.</div> : null}
                  </div>
                </article>
                <article className="panel plan-list">
                  <h3>Active giveaways</h3>
                  {snapshot.giveaways.map((item) => (
                    <div key={item.id} className="plan-row">
                      <div>
                        <strong>{item.title}</strong>
                        <small>{item.prize || item.kind}</small>
                      </div>
                      <button className="ui-btn ghost" type="button" onClick={() => void joinGiveaway(item.id)} disabled={actionPending || item.joined}>
                        {item.joined ? "Joined" : "Join"}
                      </button>
                    </div>
                  ))}
                  {!snapshot.giveaways.length ? <div className="empty">No active giveaways.</div> : null}
                </article>
              </section>
            ) : null}

            {section === "help" ? (
              <section className="stack">
                <article className="panel">
                  <h2>Help center</h2>
                  <p>Support, documentation and useful links.</p>
                  <div className="action-row">
                    <a className="ui-btn primary" href={config.support_url || "https://t.me/trumpvpnhelp"} target="_blank" rel="noreferrer noopener">
                      Open support chat
                    </a>
                    <a className="ui-btn ghost" href={config.bot_url} target="_blank" rel="noreferrer noopener">
                      Open Telegram bot
                    </a>
                  </div>
                </article>
                <article className="panel">
                  <h3>Quick actions</h3>
                  <div className="action-row">
                    <button className="ui-btn ghost" type="button" onClick={() => void copyText(config.support_url || "https://t.me/trumpvpnhelp")}>
                      Copy support link
                    </button>
                    <button className="ui-btn ghost" type="button" onClick={() => void copyText(String(snapshot.user.telegram_id || ""))}>
                      Copy Telegram ID
                    </button>
                    <button className="ui-btn ghost" type="button" onClick={() => void refresh()} disabled={pending || actionPending}>
                      Refresh data
                    </button>
                  </div>
                </article>
              </section>
            ) : null}

            <nav className="bottom-nav">
              {NAV.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`nav-item ${section === item.key ? "active" : ""}`}
                  onClick={() => {
                    triggerImpact("light");
                    navigate(item.key);
                  }}
                >
                  <span className="nav-icon">{item.icon}</span>
                  <span>{item.title}</span>
                </button>
              ))}
            </nav>
          </>
        ) : null}
      </div>

      {revokeCandidate ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card panel">
            <h3>Remove device access?</h3>
            <p>
              Device <strong>{revokeCandidate.device_name}</strong> will be revoked on <strong>{revokeTargetsCount}</strong> server(s).
            </p>
            <div className="action-row">
              <button className="ui-btn ghost" type="button" onClick={() => setRevokeCandidate(null)} disabled={actionPending}>
                Cancel
              </button>
              <button
                className="ui-btn ghost danger"
                type="button"
                onClick={() => {
                  triggerImpact("medium");
                  const id = revokeCandidate.id;
                  setRevokeCandidate(null);
                  void doRevokeConfig(id);
                }}
                disabled={actionPending}
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function SubscriptionPage({ telegramId, token }: { telegramId: string; token: string }) {
  const [data, setData] = useState<SubscriptionPreview | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const search = useMemo(() => window.location.search || "", []);

  useEffect(() => {
    void fetch(`/api/public/subscription/${telegramId}/${token}${search}`, { headers: { Accept: "application/json" }, credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(sanitizeError((await res.text()).trim() || `HTTP ${res.status}`));
        return (await res.json()) as SubscriptionPreview;
      })
      .then((payload) => setData(payload))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load subscription"))
      .finally(() => setPending(false));
  }, [search, telegramId, token]);

  async function copyUrl(url: string) {
    triggerImpact("light");
    try {
      await navigator.clipboard.writeText(url);
      trackEvent("copy_subscription_url", { size: String(url || "").length });
      setCopied(true);
      triggerNotify("success");
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // noop
    }
  }

  return (
    <main className="cabinet-root">
      <div className="mobile-shell sub-shell">
        <section className="panel">
          <h1>Subscription</h1>
          <p>Copy URL and import into VPN client.</p>
        </section>
        {pending ? <SkeletonCabinet /> : null}
        {error ? <section className="toast err">{error}</section> : null}
        {data ? (
          <>
            <section className="panel stats-row">
              <div>
                <span>Status</span>
                <strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong>
              </div>
              <div>
                <span>Days left</span>
                <strong>{data.metrics.days_left}</strong>
              </div>
              <div>
                <span>Servers</span>
                <strong>{data.metrics.servers_count}</strong>
              </div>
            </section>

            <section className="panel">
              <div className="action-row">
                <button className="ui-btn primary" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>
                  {copied ? "Copied" : "Copy URL"}
                </button>
                <a className="ui-btn ghost" href={data.links.stats_url}>
                  Refresh
                </a>
                <a className="ui-btn ghost" href={data.links.raw_url}>
                  Raw
                </a>
                <a className="ui-btn ghost" href={data.links.b64_url}>
                  Base64
                </a>
                {data.links.happ_import_url ? (
                  <a className="ui-btn ghost" href={data.links.happ_import_url}>
                    Open in HApp
                  </a>
                ) : null}
                {data.links.happ_download_url ? (
                  <a className="ui-btn ghost" href={data.links.happ_download_url} target="_blank" rel="noreferrer noopener">
                    Download HApp
                  </a>
                ) : null}
              </div>
              <pre className="url-box">{data.links.subscription_url}</pre>
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}

export default function App() {
  const path = window.location.pathname;
  const subscription = path.match(/^\/(?:subscription|sub)\/(\d+)\/([^/?#]+)/);
  if (subscription) return <SubscriptionPage telegramId={subscription[1]} token={subscription[2]} />;
  if (path === "/cabinet" || path.startsWith("/cabinet/")) return <CabinetPage />;
  return <LandingPage />;
}
