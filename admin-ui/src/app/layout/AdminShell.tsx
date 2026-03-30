import { FormEvent, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { logoutSession } from "../../features/auth/api/sessionApi";
import { ADMIN_NAV_ITEMS, ROUTES } from "../../shared/config/routes";

export function AdminShell() {
  const navigate = useNavigate();
  const [quickJump, setQuickJump] = useState("");
  const [clock, setClock] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const quickHints = useMemo(() => ADMIN_NAV_ITEMS.map((item) => item.label.toLowerCase()), []);

  async function onLogout() {
    await logoutSession();
    navigate(ROUTES.login, { replace: true });
  }

  function onQuickJumpSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = quickJump.trim().toLowerCase();
    if (!normalized) {
      return;
    }
    const target = ADMIN_NAV_ITEMS.find((item) => {
      const label = item.label.toLowerCase();
      return label.startsWith(normalized) || item.to.toLowerCase().includes(normalized);
    });
    if (!target) {
      return;
    }
    setQuickJump("");
    navigate(target.to);
  }

  return (
    <div className="admin-root">
      <aside className="nav-panel">
        <div className="nav-brand">
          <strong>TRUMPVPN</strong>
          <span>Control Room</span>
        </div>

        <div className="session-pill">
          <span className="session-dot" />
          Session Online
        </div>

        <form className="jump-form" onSubmit={onQuickJumpSubmit}>
          <input
            className="jump-input"
            value={quickJump}
            onChange={(event) => setQuickJump(event.target.value)}
            placeholder="Quick jump (users, servers...)"
            list="quick-jump-list"
          />
          <datalist id="quick-jump-list">
            {quickHints.map((hint) => (
              <option key={hint} value={hint} />
            ))}
          </datalist>
        </form>

        <nav className="nav-links">
          {ADMIN_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              <span className="nav-link-mark">{item.label[0]}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="workspace">
        <header className="workspace-head">
          <div className="workspace-head-title">
            <h1>Network Operations Console</h1>
            <p>{clock.toLocaleString()}</p>
          </div>
          <div className="workspace-head-actions">
            <button className="btn btn-secondary" type="button" onClick={() => navigate(ROUTES.overview)}>
              Dashboard
            </button>
            <button className="btn" type="button" onClick={onLogout}>
              Logout
            </button>
          </div>
        </header>

        <main className="workspace-body">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
