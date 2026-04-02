import { usePublicConfig } from "../hooks/usePublicConfig";

export function LandingPage() {
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