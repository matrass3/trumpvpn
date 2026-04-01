import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useOverviewSnapshot } from "../../features/overview/model/useOverviewSnapshot";
import { OverviewKpiGrid } from "../../features/overview/ui/OverviewKpiGrid";
import { ROUTES } from "../../shared/config/routes";
import { PageSection } from "../../shared/ui/PageSection";

function money(value: number | undefined): string {
  if (value === undefined || value === null) {
    return "-";
  }
  return `${Intl.NumberFormat("ru-RU").format(value)} RUB`;
}

export function OverviewPage() {
  const navigate = useNavigate();
  const { snapshot, pending, error, refresh } = useOverviewSnapshot({
    onUnauthorized: () => navigate(ROUTES.login, { replace: true }),
  });
  const quickActions = useMemo(
    () => [
      { title: "Manage Users", desc: "Users, subscriptions, devices, blocks.", to: ROUTES.users },
      { title: "Server Fleet", desc: "Provisioning, monitoring, runtime controls.", to: ROUTES.servers },
      { title: "Payments", desc: "Approve/reject and payment diagnostics.", to: ROUTES.payments },
      { title: "Promos & Giveaways", desc: "Campaign lifecycle and engagement.", to: ROUTES.promos },
    ],
    [],
  );

  const topSpenders = snapshot?.analytics?.top?.spenders || [];
  const topReferrers = snapshot?.analytics?.top?.referrers || [];
  const recentPayments = snapshot?.recent_payments || [];
  const recentConfigs = snapshot?.recent_configs || [];
  const serverRows = snapshot?.servers || [];

  return (
    <PageSection
      title="Executive Dashboard"
      description="Operational command center with live KPIs, fleet health and monetization analytics."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={refresh} disabled={pending}>
            {pending ? "Syncing..." : "Refresh now"}
          </button>
        </div>
      }
    >
      <div className="data-stamp">Source time: {snapshot?.generated_at ?? "-"}</div>
      {error ? <div className="error-banner">{error}</div> : null}

      <OverviewKpiGrid summary={snapshot?.summary ?? null} />

      <div className="action-grid">
        {quickActions.map((action) => (
          <button key={action.title} className="action-card" type="button" onClick={() => navigate(action.to)}>
            <h3>{action.title}</h3>
            <p>{action.desc}</p>
          </button>
        ))}
      </div>

      <div className="split-2" style={{ marginTop: 14 }}>
        <section className="subpanel">
          <div className="subpanel-head">
            <h3>User Growth & Monetization</h3>
          </div>
          <div className="metric-grid">
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone primary" />
                <h3>Users 24h / 7d / 30d</h3>
              </div>
              <div className="metric-value">
                {(snapshot?.analytics?.users?.new_24h ?? 0)} / {(snapshot?.analytics?.users?.new_7d ?? 0)} / {(snapshot?.analytics?.users?.new_30d ?? 0)}
              </div>
              <div className="metric-note">New registrations</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone warning" />
                <h3>Revenue 7d / 30d</h3>
              </div>
              <div className="metric-value">
                {money(snapshot?.analytics?.monetization?.revenue_7d)} / {money(snapshot?.analytics?.monetization?.revenue_30d)}
              </div>
              <div className="metric-note">Paid invoices only</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone success" />
                <h3>Paid Users Total / 30d</h3>
              </div>
              <div className="metric-value">
                {(snapshot?.analytics?.monetization?.paid_users_total ?? 0)} / {(snapshot?.analytics?.monetization?.paid_users_30d ?? 0)}
              </div>
              <div className="metric-note">Conversion activity</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone warning" />
                <h3>Expiring 3d / 7d</h3>
              </div>
              <div className="metric-value">
                {(snapshot?.analytics?.users?.expiring_3d ?? 0)} / {(snapshot?.analytics?.users?.expiring_7d ?? 0)}
              </div>
              <div className="metric-note">Retention risk window</div>
            </article>
          </div>
        </section>

        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Fleet Runtime</h3>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Server</th>
                  <th>Health</th>
                  <th>Protocol</th>
                  <th>Latency</th>
                  <th>Clients</th>
                  <th>Service</th>
                </tr>
              </thead>
              <tbody>
                {serverRows.slice(0, 10).map((server) => (
                  <tr key={server.id}>
                    <td>{server.name}</td>
                    <td>
                      <span
                        className={`status-tag ${
                          server.runtime?.health === "ok"
                            ? "success"
                            : server.runtime?.health === "degraded" || server.runtime?.health === "skipped"
                              ? "warning"
                              : "danger"
                        }`}
                      >
                        {server.runtime?.health || "-"}
                      </span>
                    </td>
                    <td>{server.protocol}</td>
                    <td>{server.runtime?.vpn_latency_text || "-"}</td>
                    <td>{server.active_clients}</td>
                    <td>{server.runtime?.xray_state || "-"}</td>
                  </tr>
                ))}
                {!serverRows.length ? (
                  <tr>
                    <td colSpan={6}>
                      <div className="empty-banner">No servers in snapshot.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="split-2" style={{ marginTop: 14 }}>
        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Top Spenders</h3>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Telegram</th>
                  <th>Username</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {topSpenders.map((item) => (
                  <tr key={`${item.telegram_id}-spender`}>
                    <td>{item.telegram_id}</td>
                    <td>{item.username || "-"}</td>
                    <td>{money(item.total_rub)}</td>
                  </tr>
                ))}
                {!topSpenders.length ? (
                  <tr>
                    <td colSpan={3}>
                      <div className="empty-banner">No spenders data.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Top Referrers</h3>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Telegram</th>
                  <th>Username</th>
                  <th>Referrals</th>
                  <th>Bonus</th>
                </tr>
              </thead>
              <tbody>
                {topReferrers.map((item) => (
                  <tr key={`${item.telegram_id}-ref`}>
                    <td>{item.telegram_id}</td>
                    <td>{item.username || "-"}</td>
                    <td>{item.referrals}</td>
                    <td>{money(item.bonus_rub)}</td>
                  </tr>
                ))}
                {!topReferrers.length ? (
                  <tr>
                    <td colSpan={4}>
                      <div className="empty-banner">No referrer data.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="split-2" style={{ marginTop: 14 }}>
        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Recent Payments</h3>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Telegram</th>
                  <th>Amount</th>
                  <th>Kind</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {recentPayments.slice(0, 20).map((payment) => (
                  <tr key={payment.invoice_id}>
                    <td>{payment.invoice_id}</td>
                    <td>{payment.telegram_id}</td>
                    <td>{money(payment.amount_rub)}</td>
                    <td>{payment.kind}</td>
                    <td>{payment.status}</td>
                  </tr>
                ))}
                {!recentPayments.length ? (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty-banner">No payments.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Recent Configs</h3>
          </div>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Telegram</th>
                  <th>Server</th>
                  <th>Device</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {recentConfigs.slice(0, 20).map((cfg) => (
                  <tr key={cfg.id}>
                    <td>{cfg.id}</td>
                    <td>{cfg.telegram_id}</td>
                    <td>{cfg.server}</td>
                    <td>{cfg.device_name}</td>
                    <td>
                      <span className={`status-tag ${cfg.is_active ? "success" : "warning"}`}>
                        {cfg.is_active ? "active" : "revoked"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!recentConfigs.length ? (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty-banner">No configs.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </PageSection>
  );
}


