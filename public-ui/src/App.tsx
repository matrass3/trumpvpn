import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";

type PublicConfig = {
  bot_url: string;
  brand: string;
  bot_username?: string;
};

type SubscriptionPreview = {
  status: "ok";
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
  account: {
    telegram_id: number;
    username: string;
    balance_rub: number;
  };
  devices: string[];
  servers: string[];
};

type CabinetUserConfig = {
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
    trial_bonus_granted: boolean;
    pending_discount_promo_id: number | null;
    subscription_until: string | null;
    subscription_active: boolean;
    invited_count: number;
    referral_bonus_rub: number;
    configs: CabinetUserConfig[];
  };
  plans: Array<{
    id: string;
    label: string;
    months: number;
    price_rub: number;
    badge: string;
    days: number;
  }>;
  payment: {
    min_topup_rub: number;
    max_topup_rub: number;
    gateway: string;
    price_rub: number;
  };
  giveaways: Array<{
    id: number;
    title: string;
    description: string;
    prize: string;
    kind: string;
    joined: boolean;
    participants: number;
  }>;
  payments: Array<{
    invoice_id: number;
    status: string;
    amount_rub: number;
    payable_rub: number;
    kind: string;
    promo_code: string;
    promo_discount_percent: number;
    created_at: string;
    paid_at: string | null;
    pay_url: string;
  }>;
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

function formatInt(value: number | null | undefined) {
  return Intl.NumberFormat("en-US").format(Number(value || 0));
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
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
  const [config, setConfig] = useState<PublicConfig>({
    bot_url: "https://t.me/trumpvlessbot",
    brand: "TrumpVPN",
    bot_username: "trumpvlessbot",
  });

  useEffect(() => {
    void fetch("/api/public/config", { headers: { Accept: "application/json" } })
      .then(async (res) => {
        if (!res.ok) {
          return;
        }
        const payload = (await res.json()) as Partial<PublicConfig>;
        setConfig((prev) => ({
          bot_url: String(payload.bot_url || prev.bot_url),
          brand: String(payload.brand || prev.brand),
          bot_username: String(payload.bot_username || prev.bot_username || "trumpvlessbot"),
        }));
      })
      .catch(() => {
        // Keep defaults.
      });
  }, []);

  return config;
}

function useReveal() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(".reveal"));
    if (!nodes.length) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.18,
        rootMargin: "0px 0px -8% 0px",
      },
    );

    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
}

function LandingPage() {
  const config = usePublicConfig();
  useReveal();

  return (
    <main className="landing-page">
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />

      <section className="container hero reveal">
        <header className="topbar">
          <div className="brand-chip">
            <span className="brand-dot" />
            <span>{config.brand}</span>
          </div>
          <div className="hero-actions">
            <a className="btn btn-secondary" href="/cabinet">
              Personal Cabinet
            </a>
            <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
              Open Telegram Bot
            </a>
          </div>
        </header>

        <div className="hero-grid">
          <div>
            <p className="eyebrow">Premium privacy network</p>
            <h1>
              Fast VPN service
              <br />
              for daily work
            </h1>
            <p className="lead">
              Connect and manage your subscription in Telegram. Stable protocols,
              adaptive routing, and predictable connection quality every day.
            </p>
            <div className="hero-actions">
              <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
                Start in 1 minute
              </a>
              <a className="btn btn-secondary" href="/cabinet">
                Open Cabinet
              </a>
            </div>
          </div>

          <aside className="hero-card reveal" style={{ animationDelay: "120ms" }}>
            <p className="hero-card-title">Operational reliability</p>
            <div className="hero-stats">
              <div>
                <strong>24/7</strong>
                <span>node monitoring</span>
              </div>
              <div>
                <strong>2 protocols</strong>
                <span>VLESS Reality / Hysteria2</span>
              </div>
              <div>
                <strong>1 bot + cabinet</strong>
                <span>subscription, payments, devices and promos</span>
              </div>
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}

function sanitizeErrorMessage(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) {
    return "Request failed";
  }
  if (/502|504|bad gateway|gateway time-out|gateway timeout/i.test(text)) {
    return "Service is temporarily unavailable. Please refresh in 20-30 seconds.";
  }
  return text.slice(0, 300);
}

function TelegramLoginButton({ botUsername, onAuth }: { botUsername: string; onAuth: (payload: TelegramAuthPayload) => void }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !botUsername) {
      return;
    }

    window.onTelegramAuth = (user: TelegramAuthPayload) => {
      onAuth(user);
    };

    container.innerHTML = "";
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-userpic", "false");
    script.setAttribute("data-request-access", "write");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    container.appendChild(script);

    return () => {
      delete window.onTelegramAuth;
    };
  }, [botUsername, onAuth]);

  return <div className="tg-login-slot" ref={containerRef} />;
}

function CabinetPage() {
  const config = usePublicConfig();
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
  const [createdInvoice, setCreatedInvoice] = useState<{ invoice_id: number; pay_url: string; status: string } | null>(null);

  const loadCabinet = useCallback(async () => {
    setPending(true);
    setError("");
    try {
      const data = await apiJson<CabinetSnapshot>("/api/public/cabinet");
      setSnapshot(data);
      setUnauthorized(false);
      setTopupAmount((prev) => {
        const min = Number(data.payment?.min_topup_rub || 100);
        return prev < min ? min : prev;
      });
      if (!checkInvoiceId && data.payments?.length) {
        setCheckInvoiceId(Number(data.payments[0].invoice_id || 0));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load cabinet";
      if (/unauthorized/i.test(msg) || /401/.test(msg)) {
        setUnauthorized(true);
        setSnapshot(null);
      } else {
        setError(msg);
      }
    } finally {
      setPending(false);
    }
  }, [checkInvoiceId]);

  useEffect(() => {
    void loadCabinet();
  }, [loadCabinet]);

  async function withAction(action: () => Promise<void>) {
    setActionPending(true);
    setError("");
    setMessage("");
    try {
      await action();
      await loadCabinet();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setActionPending(false);
    }
  }

  async function onTelegramAuth(payload: TelegramAuthPayload) {
    await withAction(async () => {
      const result = await apiJson<{ ok: boolean }>("/api/public/auth/telegram", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!result.ok) {
        throw new Error("Telegram authorization failed");
      }
      setMessage("Login success");
    });
  }

  async function onLogout() {
    await withAction(async () => {
      await apiJson<{ ok: boolean }>("/api/public/auth/logout", { method: "POST" });
      setSnapshot(null);
      setUnauthorized(true);
      setMessage("Logged out");
    });
  }

  async function onCreatePayment(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      const result = await apiJson<{ invoice_id: number; pay_url: string; status: string }>("/api/public/cabinet/payments/create", {
        method: "POST",
        body: JSON.stringify({ amount_rub: Number(topupAmount || 0), gateway: topupGateway }),
      });
      setCreatedInvoice(result);
      setCheckInvoiceId(result.invoice_id);
      setMessage(`Invoice #${result.invoice_id} created`);
    });
  }

  async function onCheckPayment(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!checkInvoiceId) {
        throw new Error("Enter invoice id");
      }
      const result = await apiJson<{ status: string }>("/api/public/cabinet/payments/check", {
        method: "POST",
        body: JSON.stringify({ invoice_id: Number(checkInvoiceId) }),
      });
      setMessage(`Invoice status: ${result.status}`);
    });
  }

  async function onApplyPromo(event: FormEvent) {
    event.preventDefault();
    await withAction(async () => {
      if (!promoCode.trim()) {
        throw new Error("Enter promo code");
      }
      const result = await apiJson<{ message?: string }>("/api/public/cabinet/promo/apply", {
        method: "POST",
        body: JSON.stringify({ code: promoCode.trim() }),
      });
      setMessage(result.message || "Promo applied");
      setPromoCode("");
    });
  }

  async function onRenewFromBalance() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/renew-from-balance", { method: "POST" });
      setMessage("Subscription renewed from balance");
    });
  }

  async function onClaimWelcome() {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/welcome/claim", { method: "POST" });
      setMessage("Welcome bonus processed");
    });
  }

  async function onPurchasePlan(planId: string) {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/purchase-plan", {
        method: "POST",
        body: JSON.stringify({ plan_id: planId }),
      });
      setMessage("Plan purchased");
    });
  }

  async function onJoinGiveaway(giveawayId: number) {
    await withAction(async () => {
      await apiJson("/api/public/cabinet/giveaways/join", {
        method: "POST",
        body: JSON.stringify({ giveaway_id: giveawayId }),
      });
      setMessage("Giveaway joined");
    });
  }

  return (
    <main className="site cabinet-page">
      <section className="card cabinet-head">
        <div>
          <p className="eyebrow">Personal cabinet</p>
          <h1>Account and subscription</h1>
          <p className="sub-note">Manage subscription, payments, plans, promos and giveaways from one place.</p>
        </div>
        <div className="actions">
          <button className="btn btn-secondary" onClick={() => void loadCabinet()} disabled={pending || actionPending} type="button">
            {pending ? "Loading..." : "Refresh"}
          </button>
          {snapshot ? (
            <button className="btn btn-secondary" onClick={() => void onLogout()} disabled={actionPending} type="button">
              Logout
            </button>
          ) : null}
        </div>
      </section>

      {message ? <div className="success-banner">{message}</div> : null}
      {error ? <div className="error-banner">{error}</div> : null}

      {pending && !snapshot ? <div className="card sub-loading">Loading cabinet...</div> : null}

      {!pending && unauthorized ? (
        <section className="card cabinet-login-card">
          <h2>Login via Telegram</h2>
          <p className="sub-note">Use secure Telegram login. New users are registered automatically.</p>
          <TelegramLoginButton botUsername={String(config.bot_username || "trumpvlessbot")} onAuth={(payload) => void onTelegramAuth(payload)} />
        </section>
      ) : null}

      {snapshot ? (
        <>
          <section className="sub-metrics">
            <article className="card metric">
              <span>Status</span>
              <strong>{snapshot.user.subscription_active ? "Active" : "Inactive"}</strong>
            </article>
            <article className="card metric">
              <span>Balance</span>
              <strong>{formatInt(snapshot.user.balance_rub)} RUB</strong>
            </article>
            <article className="card metric">
              <span>Expires</span>
              <strong>{formatDate(snapshot.user.subscription_until)}</strong>
            </article>
            <article className="card metric">
              <span>Invited</span>
              <strong>{formatInt(snapshot.user.invited_count)}</strong>
            </article>
            <article className="card metric">
              <span>Referral bonus</span>
              <strong>{formatInt(snapshot.user.referral_bonus_rub)} RUB</strong>
            </article>
            <article className="card metric">
              <span>Configs</span>
              <strong>{formatInt(snapshot.user.configs.length)}</strong>
            </article>
          </section>

          <section className="sub-bottom-grid" style={{ marginTop: 12 }}>
            <article className="card">
              <h2>Quick actions</h2>
              <div className="actions">
                <button className="btn btn-primary" type="button" onClick={() => void onRenewFromBalance()} disabled={actionPending}>
                  Renew from balance
                </button>
                <button className="btn btn-secondary" type="button" onClick={() => void onClaimWelcome()} disabled={actionPending}>
                  Claim welcome bonus
                </button>
              </div>

              <form className="cabinet-inline-form" onSubmit={(event) => void onApplyPromo(event)}>
                <input className="control-input" value={promoCode} placeholder="Promo code" onChange={(event) => setPromoCode(event.target.value)} />
                <button className="btn btn-secondary" type="submit" disabled={actionPending}>Apply promo</button>
              </form>
            </article>

            <article className="card">
              <h2>Top up balance</h2>
              <form className="cabinet-inline-form" onSubmit={(event) => void onCreatePayment(event)}>
                <input
                  className="control-input"
                  type="number"
                  min={snapshot.payment.min_topup_rub}
                  max={snapshot.payment.max_topup_rub}
                  value={topupAmount}
                  onChange={(event) => setTopupAmount(Number(event.target.value || 0))}
                />
                <select className="control-select" value={topupGateway} onChange={(event) => setTopupGateway(event.target.value)}>
                  <option value="cryptopay">cryptopay</option>
                  <option value="platega">platega</option>
                  <option value="platega_card">platega_card</option>
                  <option value="platega_sbp">platega_sbp</option>
                  <option value="platega_crypto">platega_crypto</option>
                  <option value="yoomoney">yoomoney</option>
                </select>
                <button className="btn btn-primary" type="submit" disabled={actionPending}>Create invoice</button>
              </form>
              <p className="sub-note">Allowed: {snapshot.payment.min_topup_rub} - {snapshot.payment.max_topup_rub} RUB</p>
              {createdInvoice ? (
                <p className="sub-note">
                  Invoice #{createdInvoice.invoice_id}: <a href={createdInvoice.pay_url} target="_blank" rel="noreferrer noopener">open payment link</a>
                </p>
              ) : null}

              <form className="cabinet-inline-form" onSubmit={(event) => void onCheckPayment(event)}>
                <input
                  className="control-input"
                  type="number"
                  placeholder="Invoice ID"
                  value={checkInvoiceId || ""}
                  onChange={(event) => setCheckInvoiceId(Number(event.target.value || 0))}
                />
                <button className="btn btn-secondary" type="submit" disabled={actionPending}>Check payment</button>
              </form>
            </article>
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <h2>Plans</h2>
            <div className="plan-grid">
              {snapshot.plans.map((plan) => (
                <article key={plan.id} className="plan-card">
                  <strong>{plan.label}</strong>
                  <div>{formatInt(plan.price_rub)} RUB</div>
                  <div className="sub-note">{plan.days} days - {plan.badge}</div>
                  <button className="btn btn-secondary" type="button" onClick={() => void onPurchasePlan(plan.id)} disabled={actionPending}>
                    Buy plan
                  </button>
                </article>
              ))}
            </div>
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <h2>Your payments</h2>
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Status</th>
                    <th>Amount</th>
                    <th>Gateway</th>
                    <th>Created</th>
                    <th>Pay</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.payments.map((row) => (
                    <tr key={row.invoice_id}>
                      <td>{row.invoice_id}</td>
                      <td>{row.status}</td>
                      <td>{formatInt(row.amount_rub)} RUB</td>
                      <td>{row.kind}</td>
                      <td>{formatDate(row.created_at)}</td>
                      <td>
                        {row.pay_url ? (
                          <a href={row.pay_url} target="_blank" rel="noreferrer noopener">pay</a>
                        ) : (
                          "-"
                        )}
                      </td>
                    </tr>
                  ))}
                  {!snapshot.payments.length ? (
                    <tr>
                      <td colSpan={6}><div className="empty-banner">No payments yet.</div></td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <h2>Giveaways</h2>
            <div className="plan-grid">
              {snapshot.giveaways.map((g) => (
                <article key={g.id} className="plan-card">
                  <strong>{g.title}</strong>
                  <div className="sub-note">{g.description || g.kind}</div>
                  <div className="sub-note">Participants: {g.participants}</div>
                  <button className="btn btn-secondary" type="button" disabled={actionPending || g.joined} onClick={() => void onJoinGiveaway(g.id)}>
                    {g.joined ? "Joined" : "Join"}
                  </button>
                </article>
              ))}
              {!snapshot.giveaways.length ? <div className="empty-banner">No active giveaways.</div> : null}
            </div>
          </section>

          <section className="card" style={{ marginTop: 12 }}>
            <h2>Device configs</h2>
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Server</th>
                    <th>Protocol</th>
                    <th>Device</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.user.configs.map((cfg) => (
                    <tr key={cfg.id}>
                      <td>{cfg.id}</td>
                      <td>{cfg.server_name}</td>
                      <td>{cfg.protocol}</td>
                      <td>{cfg.device_name}</td>
                      <td>{cfg.is_active ? "active" : "revoked"}</td>
                    </tr>
                  ))}
                  {!snapshot.user.configs.length ? (
                    <tr>
                      <td colSpan={5}><div className="empty-banner">No configs.</div></td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </>
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
    setPending(true);
    setError("");
    void fetch(`/api/public/subscription/${telegramId}/${token}${search}`, {
      headers: { Accept: "application/json" },
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = (await res.text()).trim();
          throw new Error(sanitizeErrorMessage(text || `HTTP ${res.status}`));
        }
        const payload = (await res.json()) as SubscriptionPreview;
        setData(payload);
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Failed to load subscription preview";
        setError(message);
      })
      .finally(() => {
        setPending(false);
      });
  }, [search, telegramId, token]);

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Ignore clipboard errors in unsupported environments.
    }
  }

  return (
    <main className="site subscription-page">
      <section className="card sub-hero">
        <div className="sub-hero-head">
          <div>
            <p className="eyebrow">Subscription portal</p>
            <h1>Your VPN subscription</h1>
            <p className="lead sub-lead">Use this page to copy subscription URLs and manage client imports quickly.</p>
          </div>
          <span className={`status ${data?.metrics.subscription_active ? "ok" : "warn"}`}>
            {data?.metrics.subscription_active ? "ACTIVE" : "INACTIVE"}
          </span>
        </div>
      </section>

      {pending ? <div className="card sub-loading">Loading subscription data...</div> : null}
      {error ? <div className="card error">{error}</div> : null}

      {data ? (
        <>
          <section className="sub-metrics">
            <article className="card metric"><span>Status</span><strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong></article>
            <article className="card metric"><span>Days left</span><strong>{data.metrics.days_left}</strong></article>
            <article className="card metric"><span>Servers</span><strong>{data.metrics.servers_count}</strong></article>
            <article className="card metric"><span>Devices</span><strong>{data.metrics.devices_count}</strong></article>
            <article className="card metric"><span>Traffic used</span><strong>{data.metrics.traffic_used_text}</strong></article>
            <article className="card metric"><span>Expires</span><strong>{data.metrics.expires_text}</strong></article>
          </section>

          <section className="card sub-url-card">
            <div className="sub-url-head">
              <div>
                <h2>Subscription URL</h2>
                <p className="sub-note">Open this URL in your VPN app. Browser mode is for preview only.</p>
              </div>
              <div className="sub-url-actions">
                <button className="btn btn-primary" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>
                  {copied ? "Copied" : "Copy URL"}
                </button>
                <a className="btn btn-secondary" href={data.links.stats_url}>Refresh</a>
                <a className="btn btn-secondary" href={data.links.raw_url}>Raw</a>
                <a className="btn btn-secondary" href={data.links.b64_url}>Base64</a>
                {data.links.happ_import_url ? <a className="btn btn-secondary" href={data.links.happ_import_url}>Open in HApp</a> : null}
                {data.links.happ_download_url ? <a className="btn btn-secondary" href={data.links.happ_download_url} target="_blank" rel="noreferrer noopener">Download HApp</a> : null}
              </div>
            </div>
            <pre className="url-box">{data.links.subscription_url}</pre>
          </section>

          <section className="sub-bottom-grid">
            <article className="card sub-account-card">
              <h2>Account</h2>
              <dl className="sub-account-list">
                <div><dt>Telegram ID</dt><dd>{data.account.telegram_id}</dd></div>
                <div><dt>Username</dt><dd>{data.account.username || "-"}</dd></div>
                <div><dt>Balance</dt><dd>{data.account.balance_rub} RUB</dd></div>
              </dl>
            </article>

            <article className="card sub-resources-card">
              <div>
                <h3>Devices</h3>
                <div className="chips">
                  {data.devices.length ? data.devices.map((x) => <span key={x} className="chip">{x}</span>) : <span className="muted">No devices</span>}
                </div>
              </div>
              <div className="sub-servers-block">
                <h3>Servers</h3>
                <div className="chips">
                  {data.servers.length ? data.servers.map((x) => <span key={x} className="chip">{x}</span>) : <span className="muted">No servers</span>}
                </div>
              </div>
            </article>
          </section>
        </>
      ) : null}
    </main>
  );
}

export default function App() {
  const path = window.location.pathname;
  const subMatch = path.match(/^\/subscription\/(\d+)\/([^/?#]+)/);
  if (subMatch) {
    return <SubscriptionPage telegramId={subMatch[1]} token={subMatch[2]} />;
  }
  if (path.startsWith("/cabinet")) {
    return <CabinetPage />;
  }
  return <LandingPage />;
}