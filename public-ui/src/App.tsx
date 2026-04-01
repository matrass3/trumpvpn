import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = { bot_url: string; brand: string; bot_username?: string };
type CabinetSection = "overview" | "subscription" | "billing" | "plans" | "devices" | "giveaways" | "account";

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
    configs: Array<{ id: number; server_name: string; protocol: string; device_name: string; is_active: boolean; created_at: string }>;
  };
  plans: Array<{ id: string; label: string; price_rub: number; badge: string; days: number }>;
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
  account: { telegram_id: number; username: string; balance_rub: number };
  devices: string[];
  servers: string[];
};

type TelegramAuthPayload = { id: number; username?: string; auth_date: number; hash: string };

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramAuthPayload) => void;
  }
}

const NAV: Array<{ key: CabinetSection; title: string; subtitle: string }> = [
  { key: "overview", title: "Overview", subtitle: "Main snapshot" },
  { key: "subscription", title: "Subscription", subtitle: "Status and renewal" },
  { key: "billing", title: "Billing", subtitle: "Top up and invoices" },
  { key: "plans", title: "Plans", subtitle: "Catalog" },
  { key: "devices", title: "Devices", subtitle: "Configs" },
  { key: "giveaways", title: "Giveaways", subtitle: "Campaigns" },
  { key: "account", title: "Account", subtitle: "Profile and session" },
];

const GATEWAYS = ["cryptopay", "platega", "platega_card", "platega_sbp", "platega_crypto", "yoomoney"];

const FEATURES: Array<[string, string]> = [
  ["Stable daily connectivity", "Adaptive protocol stack for mobile and desktop traffic."],
  ["Clear billing", "Balance, plans and invoice statuses in one flow."],
  ["Device visibility", "Track configurations by protocol and server."],
  ["Fast onboarding", "Telegram activation plus complete web cabinet."],
];

function fmtInt(value: number | null | undefined) {
  return Intl.NumberFormat("en-US").format(Number(value || 0));
}

function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function sanitizeError(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return "Request failed";
  if (/502|504|bad gateway|gateway timeout|gateway time-out/i.test(text)) return "Service is temporarily unavailable. Try again in 20-30 seconds.";
  return text.slice(0, 320);
}

function sectionPath(section: CabinetSection) {
  return section === "overview" ? "/cabinet" : `/cabinet/${section}`;
}

function pathSection(pathname: string): CabinetSection {
  const clean = pathname.replace(/\/+$/, "");
  if (!clean || clean === "/cabinet") return "overview";
  if (!clean.startsWith("/cabinet/")) return "overview";
  const key = clean.slice("/cabinet/".length) as CabinetSection;
  return NAV.some((item) => item.key === key) ? key : "overview";
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
    throw new Error(sanitizeError(text || `HTTP ${response.status}`));
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

function useReveal() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(".reveal"));
    if (!nodes.length) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.18, rootMargin: "0px 0px -8% 0px" });
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
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
    return () => { delete window.onTelegramAuth; };
  }, [botUsername, onAuth]);
  return <div className="telegram-widget-slot" ref={ref} />;
}

function LandingPage() {
  const config = usePublicConfig();
  useReveal();
  return (
    <main className="landing-page">
      <div className="landing-gradient-a" />
      <div className="landing-gradient-b" />
      <div className="container landing-wrap">
        <header className="landing-header reveal">
          <a className="brand-lockup" href="/"><span className="brand-glyph" /><div><strong>{config.brand}</strong><small>Digital privacy platform</small></div></a>
          <nav className="landing-nav"><a href="#benefits">Benefits</a><a href="#workflow">Workflow</a><a href="#plans">Plans</a></nav>
          <div className="landing-header-actions"><a className="btn btn-secondary" href="/cabinet">Cabinet</a><a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Telegram Bot</a></div>
        </header>
        <section className="landing-hero reveal"><div><p className="eyebrow">Designed for real daily usage</p><h1>VPN product with account-grade user experience</h1><p className="hero-copy">Start from Telegram, then manage subscription, billing and devices in a dedicated cabinet.</p><div className="hero-actions"><a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Start now</a><a className="btn btn-secondary" href="/cabinet">Open cabinet</a></div></div><aside className="hero-status"><article><span>Monitoring</span><strong>24/7</strong><p>Node health checks</p></article><article><span>Protocol stack</span><strong>VLESS + Hysteria2</strong><p>Adaptive transport strategy</p></article><article><span>Onboarding</span><strong>~1 minute</strong><p>Bot-first activation flow</p></article></aside></section>
        <section id="benefits" className="landing-section reveal"><div className="section-head"><p className="eyebrow">Benefits</p><h2>Product-level quality beyond plain config links</h2></div><div className="feature-grid">{FEATURES.map(([title, text]) => <article key={title} className="feature-card"><h3>{title}</h3><p>{text}</p></article>)}</div></section>
        <section id="workflow" className="landing-section reveal"><div className="section-head"><p className="eyebrow">Workflow</p><h2>Simple and predictable lifecycle</h2></div><div className="workflow-grid"><article><span>01</span><h3>Authenticate</h3><p>Quick identity and account creation in Telegram.</p></article><article><span>02</span><h3>Activate</h3><p>Top up or purchase a plan in cabinet.</p></article><article><span>03</span><h3>Manage</h3><p>Control subscription and devices from one workspace.</p></article></div></section>
        <section id="plans" className="landing-cta reveal"><div><p className="eyebrow">Ready</p><h2>Open your personal cabinet and continue</h2><p>Built for daily use on desktop and mobile.</p></div><a className="btn btn-primary" href="/cabinet">Go to Personal Cabinet</a></section>
      </div>
    </main>
  );
}

function CabinetPage() {
  const config = usePublicConfig();
  const [section, setSection] = useState<CabinetSection>(() => pathSection(window.location.pathname));
  const [snapshot, setSnapshot] = useState<CabinetSnapshot | null>(null);
  const [pending, setPending] = useState(true);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [topupAmount, setTopupAmount] = useState(500);
  const [topupGateway, setTopupGateway] = useState("cryptopay");
  const [promoCode, setPromoCode] = useState("");
  const [invoiceToCheck, setInvoiceToCheck] = useState(0);
  const [createdInvoice, setCreatedInvoice] = useState<{ invoice_id: number; pay_url: string } | null>(null);

  useEffect(() => {
    const onPop = () => setSection(pathSection(window.location.pathname));
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
      if (!invoiceToCheck && data.payments.length) setInvoiceToCheck(Number(data.payments[0].invoice_id || 0));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load cabinet";
      if (/unauthorized|401/i.test(msg)) { setUnauthorized(true); setSnapshot(null); } else setError(msg);
    } finally {
      setPending(false);
    }
  }, [invoiceToCheck]);

  useEffect(() => { void loadCabinet(); }, [loadCabinet]);

  const navigateSection = useCallback((next: CabinetSection) => {
    const path = sectionPath(next);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setSection(next);
  }, []);

  async function withAction(action: () => Promise<void>) {
    setActionPending(true);
    setError("");
    setMessage("");
    try { await action(); await loadCabinet(); } catch (err) { setError(err instanceof Error ? err.message : "Action failed"); } finally { setActionPending(false); }
  }

  async function login(payload: TelegramAuthPayload) { await withAction(async () => { await apiJson("/api/public/auth/telegram", { method: "POST", body: JSON.stringify(payload) }); setMessage("Login success."); }); }
  async function logout() { await withAction(async () => { await apiJson("/api/public/auth/logout", { method: "POST" }); setUnauthorized(true); setSnapshot(null); navigateSection("overview"); }); }
  async function renew() { await withAction(async () => { await apiJson("/api/public/cabinet/renew-from-balance", { method: "POST" }); setMessage("Subscription renewed."); }); }
  async function welcome() { await withAction(async () => { await apiJson("/api/public/cabinet/welcome/claim", { method: "POST" }); setMessage("Welcome bonus processed."); }); }
  async function buy(planId: string) { await withAction(async () => { await apiJson("/api/public/cabinet/purchase-plan", { method: "POST", body: JSON.stringify({ plan_id: planId }) }); setMessage("Plan purchased."); }); }
  async function join(id: number) { await withAction(async () => { await apiJson("/api/public/cabinet/giveaways/join", { method: "POST", body: JSON.stringify({ giveaway_id: id }) }); setMessage("Giveaway joined."); }); }

  async function applyPromo(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!promoCode.trim()) throw new Error("Enter promo code.");
      await apiJson("/api/public/cabinet/promo/apply", { method: "POST", body: JSON.stringify({ code: promoCode.trim() }) });
      setPromoCode("");
      setMessage("Promo applied.");
    });
  }

  async function createInvoice(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      const res = await apiJson<{ invoice_id: number; pay_url: string }>("/api/public/cabinet/payments/create", {
        method: "POST",
        body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway }),
      });
      setCreatedInvoice(res);
      setInvoiceToCheck(res.invoice_id);
      setMessage(`Invoice #${res.invoice_id} created.`);
    });
  }

  async function checkInvoice(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!invoiceToCheck) throw new Error("Enter invoice ID.");
      const res = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", {
        method: "POST",
        body: JSON.stringify({ invoice_id: invoiceToCheck }),
      });
      setMessage(`Invoice status: ${res.status}`);
    });
  }

  return (
    <main className="cabinet-page">
      <div className="cabinet-layout">
        <aside className="cabinet-sidebar">
          <a className="brand-lockup" href="/"><span className="brand-glyph" /><div><strong>TrumpVPN</strong><small>Personal workspace</small></div></a>
          <nav className="cabinet-nav">{NAV.map((item) => <button key={item.key} type="button" className={`cabinet-nav-item ${section === item.key ? "active" : ""}`} onClick={() => navigateSection(item.key)}><span>{item.title}</span><small>{item.subtitle}</small></button>)}</nav>
          <a className="btn btn-secondary" href={config.bot_url} target="_blank" rel="noreferrer noopener">Open Telegram Bot</a>
        </aside>
        <section className="cabinet-main">
          <header className="cabinet-header"><div><p className="eyebrow">Personal cabinet</p><h1>{NAV.find((item) => item.key === section)?.title || "Cabinet"}</h1></div><div className="cabinet-header-actions"><button className="btn btn-secondary" type="button" onClick={() => void loadCabinet()} disabled={pending || actionPending}>{pending ? "Loading..." : "Refresh"}</button>{snapshot ? <button className="btn btn-secondary" type="button" onClick={() => void logout()} disabled={actionPending}>Logout</button> : null}</div></header>
          {message ? <div className="notice notice-success">{message}</div> : null}
          {error ? <div className="notice notice-error">{error}</div> : null}
          {!pending && unauthorized ? <article className="surface"><h2>Login via Telegram</h2><p>Secure sign-in widget. New users are registered automatically.</p><TelegramLoginButton botUsername={String(config.bot_username || "trumpvlessbot")} onAuth={(payload) => void login(payload)} /></article> : null}
          {pending && !snapshot ? <article className="surface">Loading cabinet...</article> : null}
          {snapshot ? <><section className="stats-grid"><article className="stat-card"><span>Status</span><strong>{snapshot.user.subscription_active ? "Active" : "Inactive"}</strong></article><article className="stat-card"><span>Balance</span><strong>{fmtInt(snapshot.user.balance_rub)} RUB</strong></article><article className="stat-card"><span>Expires</span><strong>{fmtDate(snapshot.user.subscription_until)}</strong></article><article className="stat-card"><span>Referrals</span><strong>{fmtInt(snapshot.user.invited_count)}</strong></article></section>
            {section === "overview" ? <section className="columns-2"><article className="surface"><h2>Quick actions</h2><div className="action-row"><button className="btn btn-primary" type="button" onClick={() => void renew()} disabled={actionPending}>Renew from balance</button><button className="btn btn-secondary" type="button" onClick={() => void welcome()} disabled={actionPending}>Claim welcome bonus</button></div><form className="form-inline" onSubmit={(event) => void applyPromo(event)}><input className="control" value={promoCode} placeholder="Promo code" onChange={(event) => setPromoCode(event.target.value)} /><button className="btn btn-secondary" type="submit" disabled={actionPending}>Apply</button></form></article><article className="surface"><h2>Snapshot</h2><ul className="meta-list"><li>Telegram ID: {snapshot.user.telegram_id}</li><li>Username: {snapshot.user.username || "-"}</li><li>Active configs: {snapshot.user.configs.filter((cfg) => cfg.is_active).length}</li><li>Referral bonus: {fmtInt(snapshot.user.referral_bonus_rub)} RUB</li></ul></article></section> : null}
            {section === "subscription" ? <section className="surface"><h2>Subscription and plans</h2><ul className="meta-list"><li>Status: {snapshot.user.subscription_active ? "Active" : "Inactive"}</li><li>Expires: {fmtDate(snapshot.user.subscription_until)}</li><li>Pending promo ID: {snapshot.user.pending_discount_promo_id ?? "-"}</li></ul><div className="plan-grid">{snapshot.plans.map((plan) => <article key={plan.id} className="plan-card"><strong>{plan.label}</strong><p>{fmtInt(plan.price_rub)} RUB</p><small>{plan.days} days • {plan.badge}</small><button className="btn btn-secondary" type="button" onClick={() => void buy(plan.id)} disabled={actionPending}>Buy</button></article>)}</div></section> : null}
            {section === "billing" ? <section className="columns-2"><article className="surface"><h2>Create invoice</h2><form className="form-inline form-inline-wide" onSubmit={(event) => void createInvoice(event)}><input className="control" type="number" min={snapshot.payment.min_topup_rub} max={snapshot.payment.max_topup_rub} value={topupAmount} onChange={(event) => setTopupAmount(Number(event.target.value || 0))} /><select className="control" value={topupGateway} onChange={(event) => setTopupGateway(event.target.value)}>{GATEWAYS.map((gateway) => <option key={gateway} value={gateway}>{gateway}</option>)}</select><button className="btn btn-primary" type="submit" disabled={actionPending}>Create</button></form><p>Allowed range: {snapshot.payment.min_topup_rub} - {snapshot.payment.max_topup_rub} RUB</p>{createdInvoice ? <p>Invoice #{createdInvoice.invoice_id}: <a href={createdInvoice.pay_url} target="_blank" rel="noreferrer noopener">open payment link</a></p> : null}</article><article className="surface"><h2>Check invoice</h2><form className="form-inline" onSubmit={(event) => void checkInvoice(event)}><input className="control" type="number" value={invoiceToCheck || ""} onChange={(event) => setInvoiceToCheck(Number(event.target.value || 0))} /><button className="btn btn-secondary" type="submit" disabled={actionPending}>Check</button></form></article><article className="surface surface-full"><h2>Payments history</h2><div className="table-shell"><table className="data-table"><thead><tr><th>Invoice</th><th>Status</th><th>Amount</th><th>Gateway</th><th>Created</th><th>Paid</th></tr></thead><tbody>{snapshot.payments.map((row) => <tr key={row.invoice_id}><td>{row.invoice_id}</td><td>{row.status}</td><td>{fmtInt(row.amount_rub)} RUB</td><td>{row.kind}</td><td>{fmtDate(row.created_at)}</td><td>{fmtDate(row.paid_at)}</td></tr>)}{!snapshot.payments.length ? <tr><td colSpan={6}><div className="empty-row">No payments yet.</div></td></tr> : null}</tbody></table></div></article></section> : null}
            {section === "plans" ? <section className="surface"><h2>Plans catalog</h2><div className="plan-grid">{snapshot.plans.map((plan) => <article key={plan.id} className="plan-card"><strong>{plan.label}</strong><p>{fmtInt(plan.price_rub)} RUB</p><small>{plan.days} days • {plan.badge}</small><button className="btn btn-secondary" type="button" onClick={() => void buy(plan.id)} disabled={actionPending}>Purchase</button></article>)}</div></section> : null}
            {section === "devices" ? <section className="surface"><h2>Device configurations</h2><div className="table-shell"><table className="data-table"><thead><tr><th>ID</th><th>Server</th><th>Protocol</th><th>Device</th><th>Status</th><th>Created</th></tr></thead><tbody>{snapshot.user.configs.map((cfg) => <tr key={cfg.id}><td>{cfg.id}</td><td>{cfg.server_name}</td><td>{cfg.protocol}</td><td>{cfg.device_name}</td><td>{cfg.is_active ? "active" : "revoked"}</td><td>{fmtDate(cfg.created_at)}</td></tr>)}{!snapshot.user.configs.length ? <tr><td colSpan={6}><div className="empty-row">No configs.</div></td></tr> : null}</tbody></table></div></section> : null}
            {section === "giveaways" ? <section className="surface"><h2>Active giveaways</h2><div className="plan-grid">{snapshot.giveaways.map((item) => <article key={item.id} className="plan-card"><strong>{item.title}</strong><p>{item.description || item.kind}</p><small>Prize: {item.prize || "-"} • Participants: {item.participants}</small><button className="btn btn-secondary" type="button" onClick={() => void join(item.id)} disabled={actionPending || item.joined}>{item.joined ? "Joined" : "Join"}</button></article>)}{!snapshot.giveaways.length ? <div className="empty-row">No active giveaways.</div> : null}</div></section> : null}
            {section === "account" ? <section className="columns-2"><article className="surface"><h2>Profile</h2><ul className="meta-list"><li>Telegram ID: {snapshot.user.telegram_id}</li><li>Username: {snapshot.user.username || "-"}</li><li>Referral bonus: {fmtInt(snapshot.user.referral_bonus_rub)} RUB</li><li>Pending promo ID: {snapshot.user.pending_discount_promo_id ?? "-"}</li></ul></article><article className="surface"><h2>Session management</h2><p>Use logout on shared devices.</p><div className="action-row"><button className="btn btn-secondary" type="button" onClick={() => void logout()} disabled={actionPending}>Logout</button></div></article></section> : null}
          </> : null}
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
        if (!res.ok) throw new Error(sanitizeError((await res.text()).trim() || `HTTP ${res.status}`));
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
      <div className="subscription-layout">
        <section className="surface"><div className="sub-head"><div><p className="eyebrow">Subscription portal</p><h1>Your VPN subscription</h1><p>Copy and import this URL in your VPN client.</p></div><span className={`status ${data?.metrics.subscription_active ? "ok" : "warn"}`}>{data?.metrics.subscription_active ? "ACTIVE" : "INACTIVE"}</span></div></section>
        {pending ? <section className="surface">Loading subscription data...</section> : null}
        {error ? <section className="notice notice-error">{error}</section> : null}
        {data ? <><section className="stats-grid subscription-stats"><article className="stat-card"><span>Status</span><strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong></article><article className="stat-card"><span>Days left</span><strong>{data.metrics.days_left}</strong></article><article className="stat-card"><span>Servers</span><strong>{data.metrics.servers_count}</strong></article><article className="stat-card"><span>Devices</span><strong>{data.metrics.devices_count}</strong></article><article className="stat-card"><span>Traffic used</span><strong>{data.metrics.traffic_used_text}</strong></article><article className="stat-card"><span>Expires</span><strong>{data.metrics.expires_text}</strong></article></section><section className="surface"><div className="action-row"><button className="btn btn-primary" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>{copied ? "Copied" : "Copy URL"}</button><a className="btn btn-secondary" href={data.links.stats_url}>Refresh</a><a className="btn btn-secondary" href={data.links.raw_url}>Raw</a><a className="btn btn-secondary" href={data.links.b64_url}>Base64</a>{data.links.happ_import_url ? <a className="btn btn-secondary" href={data.links.happ_import_url}>Open in HApp</a> : null}{data.links.happ_download_url ? <a className="btn btn-secondary" href={data.links.happ_download_url} target="_blank" rel="noreferrer noopener">Download HApp</a> : null}</div><pre className="subscription-url-box">{data.links.subscription_url}</pre></section></> : null}
      </div>
    </main>
  );
}

export default function App() {
  const path = window.location.pathname;
  const sub = path.match(/^\/subscription\/(\d+)\/([^/?#]+)/);
  if (sub) return <SubscriptionPage telegramId={sub[1]} token={sub[2]} />;
  if (path === "/cabinet" || path.startsWith("/cabinet/")) return <CabinetPage />;
  return <LandingPage />;
}

