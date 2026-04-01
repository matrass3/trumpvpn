import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = { bot_url: string; brand: string; bot_username?: string };
type CabinetSection = "overview" | "subscription" | "billing" | "plans" | "devices" | "giveaways" | "account";

type CabinetUserConfig = {
  id: number;
  server_name: string;
  protocol: string;
  device_name: string;
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
    configs: CabinetUserConfig[];
  };
  plans: Array<{ id: string; label: string; price_rub: number; badge: string; days: number }>;
  payment: { min_topup_rub: number; max_topup_rub: number };
  giveaways: Array<{ id: number; title: string; description: string; prize: string; joined: boolean; participants: number; kind: string }>;
  payments: Array<{ invoice_id: number; status: string; amount_rub: number; kind: string; created_at: string; pay_url: string }>;
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

type TelegramAuthPayload = {
  id: number;
  username?: string;
  auth_date: number;
  hash: string;
};

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramAuthPayload) => void;
  }
}

const CABINET_NAV: Array<{ key: CabinetSection; label: string; note: string }> = [
  { key: "overview", label: "Overview", note: "Snapshot" },
  { key: "subscription", label: "Subscription", note: "Status" },
  { key: "billing", label: "Billing", note: "Top up and invoices" },
  { key: "plans", label: "Plans", note: "Catalog" },
  { key: "devices", label: "Devices", note: "Configs" },
  { key: "giveaways", label: "Giveaways", note: "Campaigns" },
  { key: "account", label: "Account", note: "Session" },
];

const LANDING_FEATURES = [
  ["Operational stability", "Multi-protocol routes with predictable day-to-day behavior."],
  ["Simple billing", "Balance, plans and invoice statuses in one clean flow."],
  ["Device visibility", "See active configs, protocol and server assignment."],
  ["Fast support flow", "Telegram bot for quick start, cabinet for detailed control."],
];

const GATEWAYS = ["cryptopay", "platega", "platega_card", "platega_sbp", "platega_crypto", "yoomoney"];

function formatInt(value: number | null | undefined) {
  return Intl.NumberFormat("en-US").format(Number(value || 0));
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function sanitizeErrorMessage(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return "Request failed";
  if (/502|504|bad gateway|gateway timeout|gateway time-out/i.test(text)) {
    return "Service is temporarily unavailable. Please refresh in 20-30 seconds.";
  }
  return text.slice(0, 320);
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
    const text = (await response.text()).trim();
    throw new Error(sanitizeErrorMessage(text || `HTTP ${response.status}`));
  }
  return (await response.json()) as T;
}

function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig>({ bot_url: "https://t.me/trumpvlessbot", brand: "TrumpVPN", bot_username: "trumpvlessbot" });
  useEffect(() => {
    void fetch("/api/public/config")
      .then(async (res) => (res.ok ? ((await res.json()) as Partial<PublicConfig>) : null))
      .then((payload) => {
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

function sectionPath(section: CabinetSection) {
  return section === "overview" ? "/cabinet" : `/cabinet/${section}`;
}

function parseSection(pathname: string): CabinetSection {
  const clean = pathname.replace(/\/+$/, "");
  if (!clean || clean === "/cabinet") return "overview";
  const key = clean.startsWith("/cabinet/") ? (clean.slice("/cabinet/".length) as CabinetSection) : "overview";
  return CABINET_NAV.some((item) => item.key === key) ? key : "overview";
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
  return <div className="tg-login-slot" ref={ref} />;
}

function LandingPage() {
  const config = usePublicConfig();
  return (
    <main className="landing-page">
      <div className="container">
        <header className="landing-header">
          <a className="brand" href="/"><span className="brand-mark" /><div><strong>{config.brand}</strong><small>Secure connectivity service</small></div></a>
          <nav className="landing-menu"><a href="#benefits">Benefits</a><a href="#workflow">Workflow</a><a href="#plans">Plans</a></nav>
          <div className="landing-actions"><a className="btn btn-outline" href="/cabinet">Cabinet</a><a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Bot</a></div>
        </header>
        <section className="hero"><div><p className="eyebrow">Privacy network for daily use</p><h1>Premium VPN experience with full account control</h1><p>Telegram for activation, web cabinet for subscription lifecycle and billing management.</p><div className="hero-actions"><a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Start now</a><a className="btn btn-outline" href="/cabinet">Open cabinet</a></div></div><aside className="hero-summary"><article><span>Monitoring</span><strong>24/7</strong><p>Health and availability checks</p></article><article><span>Protocols</span><strong>VLESS + Hysteria2</strong><p>Adaptive route stack</p></article><article><span>Onboarding</span><strong>~1 minute</strong><p>Bot-first client flow</p></article></aside></section>
        <section id="benefits" className="benefits"><div className="section-head"><p className="eyebrow">Benefits</p><h2>Product-level quality, not just a config generator</h2></div><div className="benefit-grid">{LANDING_FEATURES.map(([title, text]) => <article key={title} className="benefit-card"><h3>{title}</h3><p>{text}</p></article>)}</div></section>
        <section id="workflow" className="workflow"><div className="section-head"><p className="eyebrow">Workflow</p><h2>Clear three-step lifecycle</h2></div><div className="workflow-grid"><article><span>01</span><h3>Authenticate</h3><p>Start in Telegram and create your account.</p></article><article><span>02</span><h3>Activate</h3><p>Top up or purchase a plan in cabinet.</p></article><article><span>03</span><h3>Connect</h3><p>Import subscription URL and manage devices.</p></article></div></section>
        <section id="plans" className="landing-cta"><div><p className="eyebrow">Ready</p><h2>Open your personal cabinet</h2><p>Built for daily use on desktop and mobile.</p></div><a className="btn btn-primary" href="/cabinet">Go to cabinet</a></section>
      </div>
    </main>
  );
}

function CabinetPage() {
  const config = usePublicConfig();
  const [section, setSection] = useState<CabinetSection>(() => parseSection(window.location.pathname));
  const [snapshot, setSnapshot] = useState<CabinetSnapshot | null>(null);
  const [pending, setPending] = useState(true);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [topupAmount, setTopupAmount] = useState(500);
  const [topupGateway, setTopupGateway] = useState("cryptopay");
  const [promoCode, setPromoCode] = useState("");
  const [checkInvoiceId, setCheckInvoiceId] = useState(0);
  const [createdInvoice, setCreatedInvoice] = useState<{ invoice_id: number; pay_url: string } | null>(null);

  useEffect(() => {
    const onPop = () => setSection(parseSection(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const load = useCallback(async () => {
    setPending(true);
    setError("");
    try {
      const data = await apiJson<CabinetSnapshot>("/api/public/cabinet");
      setSnapshot(data);
      setUnauthorized(false);
      if (!checkInvoiceId && data.payments.length) setCheckInvoiceId(Number(data.payments[0].invoice_id || 0));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      if (/unauthorized|401/i.test(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
      } else setError(msg);
    } finally {
      setPending(false);
    }
  }, [checkInvoiceId]);

  useEffect(() => {
    void load();
  }, [load]);

  function go(next: CabinetSection) {
    const path = sectionPath(next);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setSection(next);
  }

  async function run(action: () => Promise<void>) {
    setActionPending(true);
    setError("");
    setMessage("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setActionPending(false);
    }
  }

  async function login(payload: TelegramAuthPayload) { await run(async () => { await apiJson("/api/public/auth/telegram", { method: "POST", body: JSON.stringify(payload) }); setMessage("Login success."); }); }
  async function logout() { await run(async () => { await apiJson("/api/public/auth/logout", { method: "POST" }); setSnapshot(null); setUnauthorized(true); go("overview"); }); }
  async function renew() { await run(async () => { await apiJson("/api/public/cabinet/renew-from-balance", { method: "POST" }); setMessage("Subscription renewed."); }); }
  async function welcome() { await run(async () => { await apiJson("/api/public/cabinet/welcome/claim", { method: "POST" }); setMessage("Welcome bonus processed."); }); }
  async function buy(planId: string) { await run(async () => { await apiJson("/api/public/cabinet/purchase-plan", { method: "POST", body: JSON.stringify({ plan_id: planId }) }); setMessage("Plan purchased."); }); }
  async function join(id: number) { await run(async () => { await apiJson("/api/public/cabinet/giveaways/join", { method: "POST", body: JSON.stringify({ giveaway_id: id }) }); setMessage("Giveaway joined."); }); }
  async function applyPromo(event: FormEvent) { event.preventDefault(); await run(async () => { if (!promoCode.trim()) throw new Error("Enter promo code."); await apiJson("/api/public/cabinet/promo/apply", { method: "POST", body: JSON.stringify({ code: promoCode.trim() }) }); setPromoCode(""); setMessage("Promo applied."); }); }
  async function createInvoice(event: FormEvent) { event.preventDefault(); await run(async () => { const r = await apiJson<{ invoice_id: number; pay_url: string }>("/api/public/cabinet/payments/create", { method: "POST", body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway }) }); setCreatedInvoice(r); setCheckInvoiceId(r.invoice_id); setMessage(`Invoice #${r.invoice_id} created.`); }); }
  async function checkInvoice(event: FormEvent) { event.preventDefault(); await run(async () => { if (!checkInvoiceId) throw new Error("Enter invoice ID."); const r = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", { method: "POST", body: JSON.stringify({ invoice_id: checkInvoiceId }) }); setMessage(`Invoice status: ${r.status}`); }); }

  return (
    <main className="cabinet-page">
      <div className="cabinet-layout">
        <aside className="cabinet-sidebar">
          <a className="brand" href="/"><span className="brand-mark" /><div><strong>TrumpVPN</strong><small>Personal cabinet</small></div></a>
          <nav className="cabinet-nav">{CABINET_NAV.map((item) => <button key={item.key} type="button" className={`cabinet-nav-item ${section === item.key ? "active" : ""}`} onClick={() => go(item.key)}><span>{item.label}</span><small>{item.note}</small></button>)}</nav>
          <a className="btn btn-outline" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Bot</a>
        </aside>
        <section className="cabinet-main">
          <header className="cabinet-header"><div><p className="eyebrow">Account workspace</p><h1>{CABINET_NAV.find((item) => item.key === section)?.label || "Cabinet"}</h1></div><div className="cabinet-header-actions"><button className="btn btn-outline" type="button" onClick={() => void load()} disabled={pending || actionPending}>{pending ? "Loading..." : "Refresh"}</button>{snapshot ? <button className="btn btn-outline" type="button" onClick={() => void logout()} disabled={actionPending}>Logout</button> : null}</div></header>
          {message ? <div className="banner banner-success">{message}</div> : null}
          {error ? <div className="banner banner-error">{error}</div> : null}
          {!pending && unauthorized ? <article className="panel"><h2>Login via Telegram</h2><p>Secure sign-in widget. New users are created automatically.</p><TelegramLoginButton botUsername={String(config.bot_username || "trumpvlessbot")} onAuth={(payload) => void login(payload)} /></article> : null}
          {pending && !snapshot ? <article className="panel">Loading cabinet...</article> : null}

          {snapshot ? (
            <>
              <section className="metric-grid"><article className="metric-card"><span>Status</span><strong>{snapshot.user.subscription_active ? "Active" : "Inactive"}</strong></article><article className="metric-card"><span>Balance</span><strong>{formatInt(snapshot.user.balance_rub)} RUB</strong></article><article className="metric-card"><span>Expires</span><strong>{formatDate(snapshot.user.subscription_until)}</strong></article><article className="metric-card"><span>Referrals</span><strong>{formatInt(snapshot.user.invited_count)}</strong></article></section>

              {section === "overview" ? <section className="section-grid"><article className="panel"><h2>Quick actions</h2><div className="row-actions"><button className="btn btn-primary" type="button" onClick={() => void renew()} disabled={actionPending}>Renew from balance</button><button className="btn btn-outline" type="button" onClick={() => void welcome()} disabled={actionPending}>Claim welcome bonus</button></div><form className="inline-form" onSubmit={(event) => void applyPromo(event)}><input className="control-input" value={promoCode} placeholder="Promo code" onChange={(event) => setPromoCode(event.target.value)} /><button className="btn btn-outline" type="submit" disabled={actionPending}>Apply</button></form></article><article className="panel"><h2>Snapshot</h2><ul className="meta-list"><li>Telegram ID: {snapshot.user.telegram_id}</li><li>Username: {snapshot.user.username || "-"}</li><li>Configs: {snapshot.user.configs.length}</li><li>Referral bonus: {formatInt(snapshot.user.referral_bonus_rub)} RUB</li></ul></article></section> : null}
              {section === "subscription" ? <section className="panel"><h2>Subscription and plans</h2><ul className="meta-list"><li>Status: {snapshot.user.subscription_active ? "Active" : "Inactive"}</li><li>Expires: {formatDate(snapshot.user.subscription_until)}</li><li>Pending promo ID: {snapshot.user.pending_discount_promo_id ?? "-"}</li></ul><div className="plan-grid">{snapshot.plans.map((plan) => <article key={plan.id} className="plan-card"><strong>{plan.label}</strong><p>{formatInt(plan.price_rub)} RUB</p><small>{plan.days} days • {plan.badge}</small><button className="btn btn-outline" type="button" onClick={() => void buy(plan.id)} disabled={actionPending}>Buy</button></article>)}</div></section> : null}
              {section === "billing" ? <section className="section-grid"><article className="panel"><h2>Create invoice</h2><form className="inline-form inline-form-wide" onSubmit={(event) => void createInvoice(event)}><input className="control-input" type="number" min={snapshot.payment.min_topup_rub} max={snapshot.payment.max_topup_rub} value={topupAmount} onChange={(event) => setTopupAmount(Number(event.target.value || 0))} /><select className="control-input" value={topupGateway} onChange={(event) => setTopupGateway(event.target.value)}>{GATEWAYS.map((g) => <option key={g} value={g}>{g}</option>)}</select><button className="btn btn-primary" type="submit" disabled={actionPending}>Create</button></form><p>Allowed range: {snapshot.payment.min_topup_rub} - {snapshot.payment.max_topup_rub} RUB</p>{createdInvoice ? <p>Invoice #{createdInvoice.invoice_id}: <a href={createdInvoice.pay_url} target="_blank" rel="noreferrer noopener">open payment link</a></p> : null}</article><article className="panel"><h2>Check invoice</h2><form className="inline-form" onSubmit={(event) => void checkInvoice(event)}><input className="control-input" type="number" value={checkInvoiceId || ""} onChange={(event) => setCheckInvoiceId(Number(event.target.value || 0))} /><button className="btn btn-outline" type="submit" disabled={actionPending}>Check</button></form></article><article className="panel panel-full"><h2>Payments</h2><div className="table-shell"><table className="data-table"><thead><tr><th>Invoice</th><th>Status</th><th>Amount</th><th>Gateway</th><th>Created</th></tr></thead><tbody>{snapshot.payments.map((row) => <tr key={row.invoice_id}><td>{row.invoice_id}</td><td>{row.status}</td><td>{formatInt(row.amount_rub)} RUB</td><td>{row.kind}</td><td>{formatDate(row.created_at)}</td></tr>)}{!snapshot.payments.length ? <tr><td colSpan={5}><div className="empty-banner">No payments yet.</div></td></tr> : null}</tbody></table></div></article></section> : null}
              {section === "plans" ? <section className="panel"><h2>Plans catalog</h2><div className="plan-grid">{snapshot.plans.map((plan) => <article key={plan.id} className="plan-card"><strong>{plan.label}</strong><p>{formatInt(plan.price_rub)} RUB</p><small>{plan.days} days • {plan.badge}</small><button className="btn btn-outline" type="button" onClick={() => void buy(plan.id)} disabled={actionPending}>Purchase</button></article>)}</div></section> : null}
              {section === "devices" ? <section className="panel"><h2>Device configurations</h2><div className="table-shell"><table className="data-table"><thead><tr><th>ID</th><th>Server</th><th>Protocol</th><th>Device</th><th>Status</th><th>Created</th></tr></thead><tbody>{snapshot.user.configs.map((cfg) => <tr key={cfg.id}><td>{cfg.id}</td><td>{cfg.server_name}</td><td>{cfg.protocol}</td><td>{cfg.device_name}</td><td>{cfg.is_active ? "active" : "revoked"}</td><td>{formatDate(cfg.created_at)}</td></tr>)}{!snapshot.user.configs.length ? <tr><td colSpan={6}><div className="empty-banner">No configs.</div></td></tr> : null}</tbody></table></div></section> : null}
              {section === "giveaways" ? <section className="panel"><h2>Active giveaways</h2><div className="plan-grid">{snapshot.giveaways.map((item) => <article key={item.id} className="plan-card"><strong>{item.title}</strong><p>{item.description || item.kind}</p><small>Prize: {item.prize || "-"} • Participants: {item.participants}</small><button className="btn btn-outline" type="button" disabled={actionPending || item.joined} onClick={() => void join(item.id)}>{item.joined ? "Joined" : "Join"}</button></article>)}{!snapshot.giveaways.length ? <div className="empty-banner">No active giveaways.</div> : null}</div></section> : null}
              {section === "account" ? <section className="section-grid"><article className="panel"><h2>Profile</h2><ul className="meta-list"><li>Telegram ID: {snapshot.user.telegram_id}</li><li>Username: {snapshot.user.username || "-"}</li><li>Referral bonus: {formatInt(snapshot.user.referral_bonus_rub)} RUB</li><li>Pending promo ID: {snapshot.user.pending_discount_promo_id ?? "-"}</li></ul></article><article className="panel"><h2>Session</h2><p>Use logout on shared devices.</p><div className="row-actions"><button className="btn btn-outline" type="button" onClick={() => void logout()} disabled={actionPending}>Logout now</button></div></article></section> : null}
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
    void fetch(`/api/public/subscription/${telegramId}/${token}${search}`, { headers: { Accept: "application/json" }, credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(sanitizeErrorMessage((await res.text()).trim() || `HTTP ${res.status}`));
        return (await res.json()) as SubscriptionPreview;
      })
      .then((payload) => setData(payload))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load subscription preview"))
      .finally(() => setPending(false));
  }, [search, telegramId, token]);

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // ignore
    }
  }

  return (
    <main className="cabinet-page">
      <div className="site">
        <section className="panel"><div className="sub-hero-head"><div><p className="eyebrow">Subscription portal</p><h1>Your VPN subscription</h1><p>Copy and import your link into a VPN client.</p></div><span className={`status ${data?.metrics.subscription_active ? "ok" : "warn"}`}>{data?.metrics.subscription_active ? "ACTIVE" : "INACTIVE"}</span></div></section>
        {pending ? <section className="panel">Loading subscription data...</section> : null}
        {error ? <section className="panel banner-error">{error}</section> : null}
        {data ? <><section className="metric-grid subscription-metrics"><article className="metric-card"><span>Status</span><strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong></article><article className="metric-card"><span>Days left</span><strong>{data.metrics.days_left}</strong></article><article className="metric-card"><span>Servers</span><strong>{data.metrics.servers_count}</strong></article><article className="metric-card"><span>Devices</span><strong>{data.metrics.devices_count}</strong></article><article className="metric-card"><span>Traffic used</span><strong>{data.metrics.traffic_used_text}</strong></article><article className="metric-card"><span>Expires</span><strong>{data.metrics.expires_text}</strong></article></section><section className="panel"><div className="subscription-actions"><button className="btn btn-primary" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>{copied ? "Copied" : "Copy URL"}</button><a className="btn btn-outline" href={data.links.stats_url}>Refresh</a><a className="btn btn-outline" href={data.links.raw_url}>Raw</a><a className="btn btn-outline" href={data.links.b64_url}>Base64</a>{data.links.happ_import_url ? <a className="btn btn-outline" href={data.links.happ_import_url}>Open in HApp</a> : null}{data.links.happ_download_url ? <a className="btn btn-outline" href={data.links.happ_download_url} target="_blank" rel="noreferrer noopener">Download HApp</a> : null}</div><pre className="url-box">{data.links.subscription_url}</pre></section></> : null}
      </div>
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
