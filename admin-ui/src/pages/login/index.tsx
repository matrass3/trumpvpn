import { LoginForm } from "../../features/auth/ui/LoginForm";

export function LoginPage() {
  return (
    <main className="auth-root">
      <section className="auth-intro">
        <div className="auth-badge">TRUMPVPN ADMIN</div>
        <h1>Secure Network Operations Console</h1>
        <p>
          Professional control surface for VPN fleet management, subscriptions, billing and campaign operations.
        </p>
        <ul>
          <li>Realtime node health and latency tracking</li>
          <li>Operational control over users, configs and payments</li>
          <li>Cookie-based auth bound to your current FastAPI backend</li>
        </ul>
      </section>

      <section className="auth-card">
        <div className="auth-card-head">
          <h2>Sign in</h2>
          <p>Use your admin Telegram ID and panel password.</p>
        </div>
        <LoginForm />
      </section>
    </main>
  );
}
