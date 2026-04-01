import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = { bot_url: string; brand: string; bot_username?: string };
type CabinetSection = "overview" | "subscription" | "payments" | "plans" | "devices" | "giveaways" | "account";

type SubscriptionPreview = {
  metrics: {
    subscription_active: boolean;
    days_left: number;
    servers_count: number;
    devices_count: number;
    traffic_used_text: string;
    expires_text: string;
  };
  links: { subscription_url: string; raw_url: string; b64_url: string; stats_url: string; happ_import_url: string; happ_download_url: string };
  account: { telegram_id: number; username: string; balance_rub: number };
  devices: string[];
  servers: string[];
};

type CabinetSnapshot = {
  user: {
    telegram_id: number;
    username: string;
    balance_rub: number;
    subscription_until: string | null;
    subscription_active: boolean;
    invited_count: number;
    referral_bonus_rub: number;
    pending_discount_promo_id: number | null;
    configs: Array<{ id: number; server_name: string; protocol: string; device_name: string; is_active: boolean; created_at: string }>;
  };
  plans: Array<{ id: string; label: string; price_rub: number; badge: string; days: number }>;
  payment: { min_topup_rub: number; max_topup_rub: number };
  giveaways: Array<{ id: number; title: string; description: string; prize: string; joined: boolean; participants: number; kind: string }>;
  payments: Array<{ invoice_id: number; status: string; amount_rub: number; kind: string; created_at: string; pay_url: string }>;
};

type TelegramAuthPayload = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
};

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramAuthPayload) => void;
  }
}

const CABINET_NAV: Array<{ key: CabinetSection; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "subscription", label: "Subscription" },
  { key: "payments", label: "Payments" },
  { key: "plans", label: "Plans" },
  { key: "devices", label: "Devices" },
  { key: "giveaways", label: "Giveaways" },
  { key: "account", label: "Account" },
];

const FEATURES = [
  ["Stable routing", "Smart protocol fallback for difficult mobile networks."],
  ["Self-service billing", "Top up, renew and track invoices from personal cabinet."],
  ["Device control", "See active configs and server/protocol distribution."],
  ["Campaign tools", "Promo code and giveaway participation in one place."],
];

function formatInt(v: number | null | undefined) {
  return Intl.NumberFormat("en-US").format(Number(v || 0));
}

function formatDate(v: string | null | undefined) {
  if (!v) return "-";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
}

function sanitizeErrorMessage(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (/502|504|bad gateway|gateway time-out|gateway timeout/i.test(text)) {
    return "Service is temporarily unavailable. Please refresh in 20-30 seconds.";
  }
  return text || "Request failed";
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers || {}) },
  });
  if (!response.ok) {
    throw new Error(sanitizeErrorMessage((await response.text()).trim() || `HTTP ${response.status}`));
  }
  return (await response.json()) as T;
}

function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig>({ bot_url: "https://t.me/trumpvlessbot", brand: "TrumpVPN", bot_username: "trumpvlessbot" });
  useEffect(() => {
    void fetch("/api/public/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((payload: Partial<PublicConfig> | null) => {
        if (!payload) return;
        setConfig((prev) => ({
          bot_url: String(payload.bot_url || prev.bot_url),
          brand: String(payload.brand || prev.brand),
          bot_username: String(payload.bot_username || prev.bot_username || "trumpvlessbot"),
        }));
      })
      .catch(() => undefined);
  }, []);
  return config;
}

function cabinetPath(section: CabinetSection) {
  return section === "overview" ? "/cabinet" : `/cabinet/${section}`;
}

function sectionFromPath(pathname: string): CabinetSection {
  const clean = pathname.replace(/\/+$/, "");
  if (clean === "/cabinet" || clean === "") return "overview";
  if (!clean.startsWith("/cabinet/")) return "overview";
  const key = clean.slice("/cabinet/".length) as CabinetSection;
  return CABINET_NAV.some((x) => x.key === key) ? key : "overview";
}

function TelegramLoginButton({ botUsername, onAuth }: { botUsername: string; onAuth: (payload: TelegramAuthPayload) => void }) {
  const slot = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!slot.current || !botUsername) return;
    window.onTelegramAuth = (user) => onAuth(user);
    slot.current.innerHTML = "";
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-userpic", "false");
    script.setAttribute("data-request-access", "write");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    slot.current.appendChild(script);
    return () => {
      delete window.onTelegramAuth;
    };
  }, [botUsername, onAuth]);
  return <div className="tg-login-slot" ref={slot} />;
}

function LandingPage() {
  const config = usePublicConfig();
  return (
    <main className="landing-page">
      <div className="container landing-shell">
        <header className="landing-topbar">
          <div className="landing-brand"><span className="landing-brand-dot" /><strong>{config.brand}</strong></div>
          <div className="landing-actions">
            <a className="btn btn-ghost" href="/cabinet">Personal Cabinet</a>
            <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Telegram Bot</a>
          </div>
        </header>
        <section className="hero-block">
          <div className="hero-copy">
            <p className="eyebrow">Daily-ready privacy network</p>
            <h1>Professional VPN experience for phone and desktop</h1>
            <p>Fast onboarding in Telegram and full multi-page account workspace in cabinet.</p>
            <div className="hero-buttons">
              <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Start now</a>
              <a className="btn btn-ghost" href="/cabinet">Open cabinet</a>
            </div>
          </div>
          <aside className="hero-panel">
            <p><strong>24/7</strong> node monitoring</p>
            <p><strong>VLESS + Hysteria2</strong> protocol flexibility</p>
            <p><strong>1 minute</strong> activation flow</p>
          </aside>
        </section>
        <section className="feature-block">
          <div className="section-head"><p className="eyebrow">Capabilities</p><h2>Designed as a complete service</h2></div>
          <div className="feature-grid">{FEATURES.map(([title, desc]) => <article key={title}><h3>{title}</h3><p>{desc}</p></article>)}</div>
        </section>
      </div>
    </main>
  );
}

function CabinetPage() {
  const config = usePublicConfig();
  const [section, setSection] = useState<CabinetSection>(() => sectionFromPath(window.location.pathname));
  const [snapshot, setSnapshot] = useState<CabinetSnapshot | null>(null);
  const [pending, setPending] = useState(true);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [topupAmount, setTopupAmount] = useState(500);
  const [topupGateway, setTopupGateway] = useState("cryptopay");
  const [promoCode, setPromoCode] = useState("");
  const [invoiceId, setInvoiceId] = useState(0);
  const [invoice, setInvoice] = useState<{ invoice_id: number; pay_url: string } | null>(null);

  useEffect(() => {
    const onPop = () => setSection(sectionFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const loadCabinet = useCallback(async () => {
    setPending(true);
    setError("");
    try {
      const data = await apiJson<CabinetSnapshot>("/api/public/cabinet");
      setSnapshot(data);
      setUnauthorized(false);
      if (!invoiceId && data.payments.length) setInvoiceId(Number(data.payments[0].invoice_id || 0));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load cabinet";
      if (/unauthorized|401/i.test(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
      } else setError(msg);
    } finally {
      setPending(false);
    }
  }, [invoiceId]);

  useEffect(() => { void loadCabinet(); }, [loadCabinet]);

  function go(next: CabinetSection) {
    const path = cabinetPath(next);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setSection(next);
  }

  async function action(fn: () => Promise<void>) {
    setActionPending(true);
    setMessage("");
    setError("");
    try { await fn(); await loadCabinet(); } catch (err) { setError(err instanceof Error ? err.message : "Action failed"); } finally { setActionPending(false); }
  }

  async function onAuth(payload: TelegramAuthPayload) {
    await action(async () => { await apiJson("/api/public/auth/telegram", { method: "POST", body: JSON.stringify(payload) }); setMessage("Login success."); });
  }
  async function onLogout() {
    await action(async () => { await apiJson("/api/public/auth/logout", { method: "POST" }); setSnapshot(null); setUnauthorized(true); go("overview"); });
  }
  async function createPayment(event: FormEvent) {
    event.preventDefault();
    await action(async () => { const r = await apiJson<{ invoice_id: number; pay_url: string }>("/api/public/cabinet/payments/create", { method: "POST", body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway }) }); setInvoice(r); setInvoiceId(r.invoice_id); setMessage(`Invoice #${r.invoice_id} created.`); });
  }
  async function checkPayment(event: FormEvent) {
    event.preventDefault();
    await action(async () => { if (!invoiceId) throw new Error("Enter invoice ID."); const r = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", { method: "POST", body: JSON.stringify({ invoice_id: invoiceId }) }); setMessage(`Invoice status: ${r.status}`); });
  }
  async function applyPromo(event: FormEvent) {
    event.preventDefault();
    await action(async () => { if (!promoCode.trim()) throw new Error("Enter promo code."); const r = await apiJson<{ message?: string }>("/api/public/cabinet/promo/apply", { method: "POST", body: JSON.stringify({ code: promoCode.trim() }) }); setPromoCode(""); setMessage(r.message || "Promo applied."); });
  }

  return (
    <main className="cabinet-root">
      <div className="cabinet-grid">
        <aside className="cabinet-sidebar">
          <div className="cabinet-brand"><strong>TrumpVPN</strong><small>Personal Cabinet</small></div>
          <nav className="cabinet-nav">{CABINET_NAV.map((item) => <button key={item.key} type="button" className={`cabinet-nav-item ${section === item.key ? "active" : ""}`} onClick={() => go(item.key)}>{item.label}</button>)}</nav>
          <a className="btn btn-ghost" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Bot</a>
        </aside>
        <section className="cabinet-content">
          <header className="cabinet-header"><h1>{CABINET_NAV.find((x) => x.key === section)?.label || "Cabinet"}</h1><div className="cabinet-header-actions"><button className="btn btn-ghost" type="button" onClick={() => void loadCabinet()} disabled={pending || actionPending}>{pending ? "Loading..." : "Refresh"}</button>{snapshot ? <button className="btn btn-ghost" type="button" onClick={() => void onLogout()} disabled={actionPending}>Logout</button> : null}</div></header>
          {message ? <div className="success-banner">{message}</div> : null}
          {error ? <div className="error-banner">{error}</div> : null}
          {!pending && unauthorized ? <article className="cabinet-panel"><h3>Login via Telegram</h3><TelegramLoginButton botUsername={String(config.bot_username || "trumpvlessbot")} onAuth={(p) => void onAuth(p)} /></article> : null}
          {pending && !snapshot ? <article className="cabinet-panel">Loading cabinet...</article> : null}
          {snapshot ? (
            <>
              <section className="cabinet-metrics">
                <article className="metric-card"><span>Status</span><strong>{snapshot.user.subscription_active ? "Active" : "Inactive"}</strong></article>
                <article className="metric-card"><span>Balance</span><strong>{formatInt(snapshot.user.balance_rub)} RUB</strong></article>
                <article className="metric-card"><span>Expires</span><strong>{formatDate(snapshot.user.subscription_until)}</strong></article>
                <article className="metric-card"><span>Referrals</span><strong>{formatInt(snapshot.user.invited_count)}</strong></article>
              </section>
              {section === "overview" ? <section className="cabinet-panel"><h3>Quick actions</h3><form className="inline-form" onSubmit={(e) => void applyPromo(e)}><input className="control-input" value={promoCode} placeholder="Promo code" onChange={(e) => setPromoCode(e.target.value)} /><button className="btn btn-ghost" type="submit" disabled={actionPending}>Apply promo</button></form></section> : null}
              {section === "subscription" ? <section className="cabinet-panel"><h3>Subscription details</h3><ul className="meta-list"><li>Status: {snapshot.user.subscription_active ? "Active" : "Inactive"}</li><li>Expires: {formatDate(snapshot.user.subscription_until)}</li><li>Pending promo ID: {snapshot.user.pending_discount_promo_id ?? "-"}</li></ul></section> : null}
              {section === "payments" ? <section className="cabinet-section-grid"><article className="cabinet-panel"><h3>Create invoice</h3><form className="inline-form inline-form-wide" onSubmit={(e) => void createPayment(e)}><input className="control-input" type="number" min={snapshot.payment.min_topup_rub} max={snapshot.payment.max_topup_rub} value={topupAmount} onChange={(e) => setTopupAmount(Number(e.target.value || 0))} /><select className="control-input" value={topupGateway} onChange={(e) => setTopupGateway(e.target.value)}><option value="cryptopay">cryptopay</option><option value="platega">platega</option><option value="platega_card">platega_card</option><option value="platega_sbp">platega_sbp</option><option value="platega_crypto">platega_crypto</option><option value="yoomoney">yoomoney</option></select><button className="btn btn-primary" type="submit" disabled={actionPending}>Create</button></form>{invoice ? <p className="sub-note">Invoice #{invoice.invoice_id}: <a href={invoice.pay_url} target="_blank" rel="noreferrer noopener">pay link</a></p> : null}</article><article className="cabinet-panel"><h3>Check invoice</h3><form className="inline-form" onSubmit={(e) => void checkPayment(e)}><input className="control-input" type="number" value={invoiceId || ""} onChange={(e) => setInvoiceId(Number(e.target.value || 0))} /><button className="btn btn-ghost" type="submit" disabled={actionPending}>Check</button></form></article><article className="cabinet-panel panel-full"><h3>History</h3><div className="table-shell"><table className="data-table"><thead><tr><th>Invoice</th><th>Status</th><th>Amount</th><th>Gateway</th><th>Created</th></tr></thead><tbody>{snapshot.payments.map((p) => <tr key={p.invoice_id}><td>{p.invoice_id}</td><td>{p.status}</td><td>{formatInt(p.amount_rub)} RUB</td><td>{p.kind}</td><td>{formatDate(p.created_at)}</td></tr>)}{!snapshot.payments.length ? <tr><td colSpan={5}><div className="empty-banner">No payments yet.</div></td></tr> : null}</tbody></table></div></article></section> : null}
              {section === "plans" ? <section className="cabinet-panel"><h3>Plans</h3><div className="plan-grid">{snapshot.plans.map((plan) => <article key={plan.id} className="plan-card"><strong>{plan.label}</strong><p>{formatInt(plan.price_rub)} RUB</p><small>{plan.days} days • {plan.badge}</small></article>)}</div></section> : null}
              {section === "devices" ? <section className="cabinet-panel"><h3>Device configs</h3><div className="table-shell"><table className="data-table"><thead><tr><th>ID</th><th>Server</th><th>Protocol</th><th>Device</th><th>Status</th></tr></thead><tbody>{snapshot.user.configs.map((cfg) => <tr key={cfg.id}><td>{cfg.id}</td><td>{cfg.server_name}</td><td>{cfg.protocol}</td><td>{cfg.device_name}</td><td>{cfg.is_active ? "active" : "revoked"}</td></tr>)}{!snapshot.user.configs.length ? <tr><td colSpan={5}><div className="empty-banner">No configs.</div></td></tr> : null}</tbody></table></div></section> : null}
              {section === "giveaways" ? <section className="cabinet-panel"><h3>Giveaways</h3><div className="plan-grid">{snapshot.giveaways.map((g) => <article key={g.id} className="plan-card"><strong>{g.title}</strong><p>{g.description || g.kind}</p><small>Prize: {g.prize || "-"} • Participants: {g.participants}</small></article>)}</div></section> : null}
              {section === "account" ? <section className="cabinet-panel"><h3>Account</h3><ul className="meta-list"><li>Telegram ID: {snapshot.user.telegram_id}</li><li>Username: {snapshot.user.username || "-"}</li><li>Referral bonus: {formatInt(snapshot.user.referral_bonus_rub)} RUB</li><li>Configs: {snapshot.user.configs.length}</li></ul></section> : null}
            </>
          ) : null}
        </section>
      </div>
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
    void fetch(`/api/public/subscription/${telegramId}/${token}${search}`)
      .then(async (r) => (r.ok ? ((await r.json()) as SubscriptionPreview) : Promise.reject(new Error(sanitizeErrorMessage(await r.text())))))
      .then((payload) => setData(payload))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load subscription preview"))
      .finally(() => setPending(false));
  }, [search, telegramId, token]);
  async function copyUrl(url: string) {
    try { await navigator.clipboard.writeText(url); setCopied(true); window.setTimeout(() => setCopied(false), 1200); } catch { undefined; }
  }
  return (
    <main className="site subscription-page">
      <section className="card sub-hero"><div className="sub-hero-head"><div><p className="eyebrow">Subscription portal</p><h1>Your VPN subscription</h1></div><span className={`status ${data?.metrics.subscription_active ? "ok" : "warn"}`}>{data?.metrics.subscription_active ? "ACTIVE" : "INACTIVE"}</span></div></section>
      {pending ? <div className="card sub-loading">Loading subscription data...</div> : null}
      {error ? <div className="card error">{error}</div> : null}
      {data ? <><section className="sub-metrics"><article className="card metric"><span>Status</span><strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong></article><article className="card metric"><span>Days left</span><strong>{data.metrics.days_left}</strong></article><article className="card metric"><span>Servers</span><strong>{data.metrics.servers_count}</strong></article><article className="card metric"><span>Devices</span><strong>{data.metrics.devices_count}</strong></article><article className="card metric"><span>Traffic used</span><strong>{data.metrics.traffic_used_text}</strong></article><article className="card metric"><span>Expires</span><strong>{data.metrics.expires_text}</strong></article></section><section className="card sub-url-card"><div className="sub-url-head"><h2>Subscription URL</h2><div className="sub-url-actions"><button className="btn btn-primary" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>{copied ? "Copied" : "Copy URL"}</button><a className="btn btn-ghost" href={data.links.stats_url}>Refresh</a><a className="btn btn-ghost" href={data.links.raw_url}>Raw</a><a className="btn btn-ghost" href={data.links.b64_url}>Base64</a></div></div><pre className="url-box">{data.links.subscription_url}</pre></section></> : null}
    </main>
  );
}

export default function App() {
  const path = window.location.pathname;
  const subMatch = path.match(/^\/subscription\/(\d+)\/([^/?#]+)/);
  if (subMatch) return <SubscriptionPage telegramId={subMatch[1]} token={subMatch[2]} />;
  if (path === "/cabinet" || path.startsWith("/cabinet/")) return <CabinetPage />;
  return <LandingPage />;
}
