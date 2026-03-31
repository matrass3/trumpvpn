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

function LandingPage() {
  const config = usePublicConfig();

  return (
    <main className="site">
      <section className="hero card">
        <p className="kicker">Secure VPN service</p>
        <h1>{config.brand}</h1>
        <p className="lead">
          Быстрый и стабильный VPN для телефона и ПК. Управление подпиской и устройствами - через Telegram-бота.
        </p>
        <div className="actions">
          <a className="btn" href={config.bot_url} target="_blank" rel="noreferrer noopener">
            Открыть бота
          </a>
          <a className="btn ghost" href="/admin/">
            Админка
          </a>
        </div>
      </section>

      <section className="grid-3">
        <article className="card feature">
          <h3>Подключение за минуту</h3>
          <p>Получите конфиг прямо в боте и импортируйте в клиент одним нажатием.</p>
        </article>
        <article className="card feature">
          <h3>Подписка и баланс</h3>
          <p>Пополнение, продление, устройства и статусы подписки в одном месте.</p>
        </article>
        <article className="card feature">
          <h3>Мультипротокол</h3>
          <p>Поддержка VLESS Reality и Hysteria2, выбор оптимального сервера по ситуации.</p>
        </article>
      </section>
    </main>
  );
}

function SubscriptionPage({ telegramId, token }: { telegramId: string; token: string }) {
  const [data, setData] = useState<SubscriptionPreview | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");

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
          throw new Error(text || `HTTP ${res.status}`);
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
    } catch {
      // Ignore clipboard errors in unsupported environments.
    }
  }

  return (
    <main className="site">
      <section className="card sub-head">
        <div>
          <h1>Subscription</h1>
          <p className="lead">Откройте URL подписки в VPN-клиенте. В браузере доступен только предпросмотр.</p>
        </div>
        <span className={`status ${data?.metrics.subscription_active ? "ok" : "warn"}`}>
          {data?.metrics.subscription_active ? "ACTIVE" : "INACTIVE"}
        </span>
      </section>

      {pending ? <div className="card">Загрузка...</div> : null}
      {error ? <div className="card error">{error}</div> : null}

      {data ? (
        <>
          <section className="grid-5">
            <article className="card metric"><span>Status</span><strong>{data.metrics.subscription_active ? "Active" : "Inactive"}</strong></article>
            <article className="card metric"><span>Days left</span><strong>{data.metrics.days_left}</strong></article>
            <article className="card metric"><span>Servers</span><strong>{data.metrics.servers_count}</strong></article>
            <article className="card metric"><span>Devices</span><strong>{data.metrics.devices_count}</strong></article>
            <article className="card metric"><span>Traffic used</span><strong>{data.metrics.traffic_used_text}</strong></article>
          </section>

          <section className="card">
            <h2>Ссылка подписки</h2>
            <div className="actions">
              <button className="btn" type="button" onClick={() => void copyUrl(data.links.subscription_url)}>Скопировать URL</button>
              <a className="btn ghost" href={data.links.stats_url}>Обновить</a>
              <a className="btn ghost" href={data.links.raw_url}>Raw</a>
              <a className="btn ghost" href={data.links.b64_url}>Base64</a>
              {data.links.happ_import_url ? <a className="btn" href={data.links.happ_import_url}>Открыть в HApp</a> : null}
              {data.links.happ_download_url ? <a className="btn ghost" href={data.links.happ_download_url} target="_blank" rel="noreferrer noopener">Скачать HApp</a> : null}
            </div>
            <pre className="url-box">{data.links.subscription_url}</pre>
          </section>

          <section className="card">
            <h2>Аккаунт</h2>
            <p>
              Telegram ID: {data.account.telegram_id} · Username: {data.account.username || "-"} · Balance: {data.account.balance_rub} RUB · Expires: {data.metrics.expires_text}
            </p>
            <div className="chips">
              {data.devices.length ? data.devices.map((x) => <span key={x} className="chip">{x}</span>) : <span className="muted">Нет устройств</span>}
            </div>
            <div className="chips">
              {data.servers.length ? data.servers.map((x) => <span key={x} className="chip">{x}</span>) : <span className="muted">Нет серверов</span>}
            </div>
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
