import { useEffect, useMemo, useState } from "react";
import "./styles.css";

type PublicConfig = {
  bot_url: string;
  brand: string;
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

function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig>({
    bot_url: "https://t.me/trumpvlessbot",
    brand: "TrumpVPN",
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
          <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
            Open Telegram Bot
          </a>
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
              <a className="btn btn-secondary" href="#how-it-works">
                How it works
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
                <strong>1 bot</strong>
                <span>subscription and device management</span>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <section className="container stats reveal" style={{ animationDelay: "80ms" }}>
        <article className="stat-card">
          <p>Connection</p>
          <h3>up to 1 minute</h3>
          <span>no manual setup</span>
        </article>
        <article className="stat-card">
          <p>Platforms</p>
          <h3>iOS - Android - macOS - Windows</h3>
          <span>one subscription for all devices</span>
        </article>
        <article className="stat-card">
          <p>Support</p>
          <h3>via Telegram</h3>
          <span>full control in one interface</span>
        </article>
      </section>

      <section className="container features reveal">
        <div className="section-head">
          <p className="eyebrow">Why TrumpVPN</p>
          <h2>Service architecture without extra complexity</h2>
        </div>
        <div className="feature-grid">
          <article className="feature-card">
            <h3>Instant onboarding</h3>
            <p>The bot provides a subscription URL and ready configs, so you can connect right away.</p>
          </article>
          <article className="feature-card">
            <h3>Flexible network</h3>
            <p>Two protocols for different scenarios: everyday stability and a stronger mode for difficult networks.</p>
          </article>
          <article className="feature-card">
            <h3>Device control</h3>
            <p>Manage devices and configs from one account: add, revoke, and refresh in a few clicks.</p>
          </article>
          <article className="feature-card">
            <h3>Transparent billing</h3>
            <p>Balance, renewals, statuses, and payment history are available in one place.</p>
          </article>
        </div>
      </section>

      <section id="how-it-works" className="container steps reveal">
        <div className="section-head">
          <p className="eyebrow">How it works</p>
          <h2>Three steps to secure connection</h2>
        </div>
        <div className="step-grid">
          <article className="step-card">
            <span>01</span>
            <h3>Open the bot</h3>
            <p>Launch the Telegram bot and create your profile in one click.</p>
          </article>
          <article className="step-card">
            <span>02</span>
            <h3>Get config</h3>
            <p>Choose your device and import the subscription into your VPN client automatically.</p>
          </article>
          <article className="step-card">
            <span>03</span>
            <h3>Work without limits</h3>
            <p>Switch protocol or update device in the same bot whenever needed.</p>
          </article>
        </div>
      </section>

      <section className="container cta reveal">
        <div>
          <p className="eyebrow">Ready to connect</p>
          <h2>Activate your VPN now</h2>
          <p className="lead">Open the Telegram bot, activate your plan, and connect in one short session.</p>
        </div>
        <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
          Go to bot
        </a>
      </section>
    </main>
  );
}

function sanitizeErrorMessage(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) {
    return "Failed to load subscription data";
  }
  if (/502|504|bad gateway|gateway time-out|gateway timeout/i.test(text)) {
    return "Service is temporarily unavailable. Please refresh the page in 20-30 seconds.";
  }
  return text.slice(0, 280);
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
            <article className="card metric">
              <span>Status</span>
              <strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong>
            </article>
            <article className="card metric">
              <span>Days left</span>
              <strong>{data.metrics.days_left}</strong>
            </article>
            <article className="card metric">
              <span>Servers</span>
              <strong>{data.metrics.servers_count}</strong>
            </article>
            <article className="card metric">
              <span>Devices</span>
              <strong>{data.metrics.devices_count}</strong>
            </article>
            <article className="card metric">
              <span>Traffic used</span>
              <strong>{data.metrics.traffic_used_text}</strong>
            </article>
            <article className="card metric">
              <span>Expires</span>
              <strong>{data.metrics.expires_text}</strong>
            </article>
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
                <div>
                  <dt>Telegram ID</dt>
                  <dd>{data.account.telegram_id}</dd>
                </div>
                <div>
                  <dt>Username</dt>
                  <dd>{data.account.username || "-"}</dd>
                </div>
                <div>
                  <dt>Balance</dt>
                  <dd>{data.account.balance_rub} RUB</dd>
                </div>
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
  const match = path.match(/^\/subscription\/(\d+)\/([^/?#]+)/);
  if (match) {
    return <SubscriptionPage telegramId={match[1]} token={match[2]} />;
  }
  return <LandingPage />;
}