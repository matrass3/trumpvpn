import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = { bot_url: string; brand: string; bot_username?: string; support_url?: string };
type TelegramAuthPayload = { id: number; username?: string; auth_date: number; hash: string };
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
    invited_count: number;
    referral_bonus_rub: number;
    configs: CabinetConfig[];
  };
  plans: Array<{ id: string; label: string; months: number; price_rub: number; badge: string; days: number }>;
  payment: { min_topup_rub: number; max_topup_rub: number };
  giveaways: Array<{ id: number; title: string; description: string; prize: string; kind: string; joined: boolean; participants: number }>;
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
  read: boolean;
  created_at: number;
};

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramAuthPayload) => void;
    Telegram?: {
      WebApp?: {
        initData?: string;
        ready?: () => void;
        expand?: () => void;
        HapticFeedback?: {
          impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
          notificationOccurred?: (kind: "error" | "success" | "warning") => void;
          selectionChanged?: () => void;
        };
      };
    };
  }
}

const NAV: Array<{ key: CabinetSection; title: string; icon: string }> = [
  { key: "dashboard", title: "Home", icon: "home" },
  { key: "subscription", title: "Subscription", icon: "sparkle" },
  { key: "balance", title: "Balance", icon: "wallet" },
  { key: "referrals", title: "Referrals", icon: "users" },
  { key: "giveaways", title: "Fortune", icon: "gift" },
  { key: "help", title: "Help", icon: "help" },
];

const GATEWAYS = [
  { code: "cryptopay", title: "CryptoPay" },
  { code: "platega", title: "Platega" },
  { code: "platega_card", title: "Platega Card" },
  { code: "platega_sbp", title: "Platega SBP" },
  { code: "platega_crypto", title: "Platega Crypto" },
  { code: "yoomoney", title: "YooMoney" },
];

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
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return "Request failed";
  if (/502|504|bad gateway|gateway timeout|gateway time-out/i.test(text)) return "Service is temporarily unavailable. Try again in 20-30 seconds.";
  return text.slice(0, 320);
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
  if (label && !/(?:\u0420.|\u00D0.|\u00D1.){2,}/.test(label) && !label.includes("\uFFFD")) return label;
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

function extractRawQueryParam(name: string): string {
  const query = window.location.search.startsWith("?") ? window.location.search.slice(1) : "";
  if (!query) return "";
  const parts = query.split("&");
  for (const item of parts) {
    if (!item) continue;
    const eqPos = item.indexOf("=");
    const key = eqPos >= 0 ? item.slice(0, eqPos) : item;
    if (key === name) return eqPos >= 0 ? item.slice(eqPos + 1) : "";
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
  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(sanitizeError((await response.text()).trim() || `HTTP ${response.status}`));
  }
  return (await response.json()) as T;
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

function TelegramLoginButton({ botUsername, onAuth }: { botUsername: string; onAuth: (payload: TelegramAuthPayload) => void }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || !botUsername) return;
    window.onTelegramAuth = (user) => onAuth(user);
    ref.current.innerHTML = "";
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-userpic", "false");
    script.setAttribute("data-request-access", "write");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    ref.current.appendChild(script);
    return () => {
      delete window.onTelegramAuth;
    };
  }, [botUsername, onAuth]);

  return <div className="telegram-widget-slot" ref={ref} />;
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
  const [miniAppAuthTried, setMiniAppAuthTried] = useState(false);
  const [miniAppAuthPending, setMiniAppAuthPending] = useState(false);
  const [notifications, setNotifications] = useState<AppNotice[]>([]);
  const [toasts, setToasts] = useState<AppNotice[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [protocolFilter, setProtocolFilter] = useState("all");
  const [revokeCandidate, setRevokeCandidate] = useState<CabinetConfig | null>(null);
  const noticeSeq = useRef(0);
  const previousSnapshot = useRef<CabinetSnapshot | null>(null);
  const expiryMarker = useRef("");

  const pushNotice = useCallback((kind: NoticeKind, body: string, title?: string) => {
    const id = ++noticeSeq.current;
    const entry: AppNotice = {
      id,
      kind,
      title: title || noticeTitleByKind(kind),
      body,
      read: false,
      created_at: Date.now(),
    };
    setNotifications((prev) => [entry, ...prev].slice(0, 30));
    setToasts((prev) => [entry, ...prev].slice(0, 3));
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  const unreadNotifications = useMemo(() => notifications.filter((item) => !item.read).length, [notifications]);

  useEffect(() => {
    const onPop = () => setSection(sectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!showNotifications) return;
    setNotifications((prev) => prev.map((item) => ({ ...item, read: true })));
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

  const navigate = useCallback((next: CabinetSection) => {
    const nextPath = pathFromSection(next);
    if (window.location.pathname !== nextPath) window.history.pushState({}, "", nextPath);
    setSection(next);
  }, []);

  async function withAction(action: () => Promise<void>) {
    setActionPending(true);
    try {
      await action();
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Action failed";
      pushNotice("error", msg);
      triggerNotify("error");
    } finally {
      setActionPending(false);
    }
  }

  async function login(payload: TelegramAuthPayload) {
    await withAction(async () => {
      await apiJson("/api/public/auth/telegram", { method: "POST", body: JSON.stringify(payload) });
      pushNotice("success", "Login successful.");
      triggerNotify("success");
    });
  }

  const loginWithMiniApp = useCallback(
    async (initDataRaw: string) => {
      const initData = String(initDataRaw || "").trim();
      if (!initData) return false;
      try {
        setMiniAppAuthPending(true);
        await apiJson("/api/public/auth/miniapp", { method: "POST", body: JSON.stringify({ init_data: initData }) });
        await refresh();
        pushNotice("success", "Logged in via Telegram Mini App.", "Telegram");
        triggerNotify("success");
        return true;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Mini App auth failed";
        pushNotice("warn", msg, "Telegram");
        return false;
      } finally {
        setMiniAppAuthPending(false);
      }
    },
    [pushNotice, refresh]
  );

  useEffect(() => {
    if (!unauthorized || miniAppAuthTried || miniAppAuthPending) return;
    let cancelled = false;
    let attempts = 0;
    const run = async () => {
      if (cancelled) return;
      const initData = getTelegramMiniAppInitData();
      if (!initData) {
        attempts += 1;
        if (attempts < 12) window.setTimeout(run, 250);
        return;
      }
      setMiniAppAuthTried(true);
      await loginWithMiniApp(initData);
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [unauthorized, miniAppAuthTried, miniAppAuthPending, loginWithMiniApp]);

  async function logout() {
    await withAction(async () => {
      await apiJson("/api/public/auth/logout", { method: "POST" });
      setUnauthorized(true);
      setSnapshot(null);
      setShowNotifications(false);
      setNotifications([]);
      setToasts([]);
      navigate("dashboard");
    });
  }

  async function renewFromBalance() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/renew-from-balance", { method: "POST" });
      pushNotice("success", "Subscription renewed.");
      triggerNotify("success");
    });
  }

  async function claimWelcome() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/welcome/claim", { method: "POST" });
      pushNotice("success", "Welcome bonus processed.");
      triggerNotify("success");
    });
  }

  async function applyPromo(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!promoCode.trim()) throw new Error("Enter promo code");
      await apiJson("/api/public/cabinet/promo/apply", { method: "POST", body: JSON.stringify({ code: promoCode.trim() }) });
      setPromoCode("");
      pushNotice("success", "Promo applied.");
      triggerNotify("success");
    });
  }

  async function createInvoice(event: FormEvent) {
    event.preventDefault();
    triggerImpact("medium");
    await withAction(async () => {
      const result = await apiJson<{ invoice_id: number; pay_url: string }>("/api/public/cabinet/payments/create", {
        method: "POST",
        body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway }),
      });
      setCreatedInvoice(result);
      setInvoiceToCheck(result.invoice_id);
      pushNotice("info", `Invoice #${result.invoice_id} created.`);
    });
  }

  async function checkInvoice(invoiceId?: number) {
    await withAction(async () => {
      const id = Number(invoiceId || invoiceToCheck || 0);
      if (!id) throw new Error("Enter invoice ID");
      const result = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", {
        method: "POST",
        body: JSON.stringify({ invoice_id: id }),
      });
      pushNotice("info", `Invoice #${id}: ${result.status}`);
    });
  }

  async function buyPlan(planId: string) {
    triggerImpact("medium");
    await withAction(async () => {
      await apiJson("/api/public/cabinet/purchase-plan", { method: "POST", body: JSON.stringify({ plan_id: planId }) });
      pushNotice("success", "Plan purchased.");
      triggerNotify("success");
    });
  }

  async function joinGiveaway(giveawayId: number) {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/giveaways/join", { method: "POST", body: JSON.stringify({ giveaway_id: giveawayId }) });
      pushNotice("success", "You joined the giveaway.");
      triggerNotify("success");
    });
  }

  async function doRevokeConfig(configId: number) {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/configs/revoke", { method: "POST", body: JSON.stringify({ config_id: configId }) });
      pushNotice("success", "Device access revoked.");
      triggerNotify("success");
    });
  }

  async function copyText(value: string) {
    triggerImpact("light");
    try {
      await navigator.clipboard.writeText(value);
      pushNotice("success", "Copied.");
      triggerNotify("success");
    } catch {
      pushNotice("error", "Copy failed");
      triggerNotify("error");
    }
  }

  const username = snapshot?.user.username || `id${snapshot?.user.telegram_id || ""}`;
  const daysLeft = getDaysLeft(snapshot?.user.subscription_until);
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
            <h2>Login via Telegram</h2>
            <p>{miniAppAuthPending ? "Authorizing via Telegram Mini App..." : "Use secure Telegram auth."}</p>
            {!miniAppAuthPending ? <TelegramLoginButton botUsername={String(config.bot_username || "trumpvlessbot")} onAuth={(payload) => void login(payload)} /> : null}
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
                    {activeConfigs[0]?.vless_url ? (
                      <button className="ui-btn ghost" type="button" onClick={() => void copyText(activeConfigs[0].vless_url)}>
                        Copy access key
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
                          <button className="ui-btn ghost small" type="button" onClick={() => void copyText(cfg.vless_url)}>
                            Copy key
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
                      <div className="action-row">
                        <a
                          className="ui-btn ghost"
                          href={createdInvoice.pay_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          onClick={() => triggerImpact("medium")}
                        >
                          Open payment link
                        </a>
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
                  <h2>Fortune wheel and giveaways</h2>
                  <p>Join active campaigns and check your status.</p>
                </article>
                <article className="panel plan-list">
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
                <button key={item.key} type="button" className={`nav-item ${section === item.key ? "active" : ""}`} onClick={() => navigate(item.key)}>
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
              Device <strong>{revokeCandidate.device_name}</strong> on <strong>{revokeCandidate.server_name}</strong> will be revoked.
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
