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
            Открыть Telegram-бота
          </a>
        </header>

        <div className="hero-grid">
          <div>
            <p className="eyebrow">Premium privacy network</p>
            <h1>
              Быстрый VPN-сервис
              <br />
              для повседневной работы
            </h1>
            <p className="lead">
              Подключение и управление подпиской в Telegram. Стабильные протоколы,
              адаптивная маршрутизация и предсказуемое качество соединения каждый день.
            </p>
            <div className="hero-actions">
              <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
                Начать за 1 минуту
              </a>
              <a className="btn btn-secondary" href="#how-it-works">
                Как это работает
              </a>
            </div>
          </div>

          <aside className="hero-card reveal" style={{ animationDelay: "120ms" }}>
            <p className="hero-card-title">Операционная надежность</p>
            <div className="hero-stats">
              <div>
                <strong>24/7</strong>
                <span>мониторинг узлов</span>
              </div>
              <div>
                <strong>2 протокола</strong>
                <span>VLESS Reality / Hysteria2</span>
              </div>
              <div>
                <strong>1 бот</strong>
                <span>управление подпиской и устройствами</span>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <section className="container stats reveal" style={{ animationDelay: "80ms" }}>
        <article className="stat-card">
          <p>Подключение</p>
          <h3>до 1 минуты</h3>
          <span>без ручной конфигурации</span>
        </article>
        <article className="stat-card">
          <p>Платформы</p>
          <h3>iOS · Android · macOS · Windows</h3>
          <span>единая подписка для всех устройств</span>
        </article>
        <article className="stat-card">
          <p>Поддержка</p>
          <h3>через Telegram</h3>
          <span>весь контроль в одном интерфейсе</span>
        </article>
      </section>

      <section className="container features reveal">
        <div className="section-head">
          <p className="eyebrow">Почему TrumpVPN</p>
          <h2>Сервисная архитектура без лишней сложности</h2>
        </div>
        <div className="feature-grid">
          <article className="feature-card">
            <h3>Моментальный старт</h3>
            <p>Бот формирует ссылку подписки и готовые конфиги. Вы подключаетесь сразу, без длинной настройки.</p>
          </article>
          <article className="feature-card">
            <h3>Гибкая сеть</h3>
            <p>Два протокола под разные сценарии: стабильная повседневная работа и усиленный режим для сложных сетей.</p>
          </article>
          <article className="feature-card">
            <h3>Контроль устройств</h3>
            <p>Управляйте устройствами и конфигами из одного аккаунта: добавление, отзыв и обновление в пару кликов.</p>
          </article>
          <article className="feature-card">
            <h3>Прозрачная подписка</h3>
            <p>Баланс, продление, статусы и история операций доступны в одном месте без скрытых шагов.</p>
          </article>
        </div>
      </section>

      <section id="how-it-works" className="container steps reveal">
        <div className="section-head">
          <p className="eyebrow">Как это работает</p>
          <h2>Три шага до защищенного подключения</h2>
        </div>
        <div className="step-grid">
          <article className="step-card">
            <span>01</span>
            <h3>Откройте бота</h3>
            <p>Запустите Telegram-бота и создайте профиль в один клик.</p>
          </article>
          <article className="step-card">
            <span>02</span>
            <h3>Получите конфиг</h3>
            <p>Выберите устройство и импортируйте подписку в клиент автоматически.</p>
          </article>
          <article className="step-card">
            <span>03</span>
            <h3>Работайте без ограничений</h3>
            <p>При необходимости переключайте протокол или обновляйте устройство в том же боте.</p>
          </article>
        </div>
      </section>

      <section className="container cta reveal">
        <div>
          <p className="eyebrow">Готово к подключению</p>
          <h2>Подключите VPN-сервис сейчас</h2>
          <p className="lead">Переходите в Telegram-бота, активируйте подписку и подключитесь за одну сессию.</p>
        </div>
        <a className="btn btn-primary" href={config.bot_url} target="_blank" rel="noreferrer noopener">
          Перейти в бота
        </a>
      </section>
    </main>
  );
}

function sanitizeErrorMessage(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) {
    return "Не удалось загрузить данные подписки";
  }
  if (/502|504|bad gateway|gateway time-out|gateway timeout/i.test(text)) {
    return "Сервис временно недоступен. Попробуйте обновить страницу через 20-30 секунд.";
  }
  return text.slice(0, 280);
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