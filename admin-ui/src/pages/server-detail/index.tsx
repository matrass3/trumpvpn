import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getAdminServerDetail,
  getAdminServerRuntimeCheck,
  type AdminServerDetail,
} from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { PageSection } from "../../shared/ui/PageSection";

function toInt(value: string | undefined): number {
  const parsed = Number(value || "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatRuntimeHealth(health: string | undefined): "success" | "warning" | "danger" {
  const normalized = String(health || "").toLowerCase();
  if (normalized === "ok") {
    return "success";
  }
  if (normalized === "degraded" || normalized === "skipped") {
    return "warning";
  }
  return "danger";
}

export function ServerDetailPage() {
  const navigate = useNavigate();
  const flash = useFlash();
  const params = useParams<{ serverId: string }>();
  const serverId = Number(params.serverId || 0);

  const [pending, setPending] = useState(false);
  const [checkPending, setCheckPending] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [detail, setDetail] = useState<AdminServerDetail | null>(null);

  const server = detail?.server ?? null;
  const runtime = detail?.runtime ?? null;
  const metrics = detail?.metrics ?? null;

  const load = useCallback(
    async (fresh = false) => {
      if (!serverId || serverId <= 0) {
        flash.showError("Invalid server id");
        return;
      }
      setPending(true);
      try {
        const snapshot = await getAdminServerDetail(serverId, { live: 1, fresh: fresh ? 1 : 0 });
        setDetail(snapshot);
      } catch (error) {
        if (isUnauthorizedError(error)) {
          navigate(ROUTES.login, { replace: true });
          return;
        }
        flash.showError(error instanceof Error ? error.message : "Failed to load server detail");
      } finally {
        setPending(false);
      }
    },
    [flash, navigate, serverId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) {
      return;
    }
    const timer = window.setInterval(() => {
      void load();
    }, 12000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, load]);

  const patchServer = useCallback(
    <K extends keyof AdminServerDetail["server"]>(key: K, value: AdminServerDetail["server"][K]) => {
      setDetail((prev) => {
        if (!prev) {
          return prev;
        }
        return {
          ...prev,
          server: {
            ...prev.server,
            [key]: value,
          },
        };
      });
    },
    [],
  );

  async function runAction(path: string, body: Record<string, string | number | boolean> = {}) {
    const result = await submitAdminActionSafely(path, body);
    if (result.error) {
      flash.showError(result.error);
      return false;
    }
    flash.showMessage(result.message || "Action completed");
    return true;
  }

  async function onRuntimeCheck() {
    if (!serverId || serverId <= 0) {
      return;
    }
    setCheckPending(true);
    try {
      await getAdminServerRuntimeCheck(serverId);
      flash.showMessage("Runtime check completed");
      await load(true);
    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Runtime check failed");
    } finally {
      setCheckPending(false);
    }
  }

  async function onSaveServer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!server) {
      return;
    }
    const ok = await runAction(`/admin/action/server/${server!.id}/update`, {
      ...server,
      enabled: Boolean(server!.enabled),
      hy2_insecure: Boolean(server!.hy2_insecure),
    });
    if (ok) {
      await load(true);
    }
  }

  async function onDeleteServer() {
    if (!server) {
      return;
    }
    const confirmed = window.confirm(`Delete server ${server!.name}?`);
    if (!confirmed) {
      return;
    }
    const ok = await runAction(`/admin/action/server/${server!.id}/delete`);
    if (ok) {
      navigate(ROUTES.servers, { replace: true });
    }
  }

  const historyRows = useMemo(() => {
    return {
      latency: (detail?.latency_points || []).slice(-20).reverse(),
      load: (detail?.load_points || []).slice(-20).reverse(),
      connections: (detail?.connection_points || []).slice(-20).reverse(),
      daily: (detail?.daily_points || []).slice(-14).reverse(),
    };
  }, [detail]);

  return (
    <PageSection
      title={server ? `Server - ${server!.name}` : "Server"}
      description="Full node operations card: runtime, metrics, live devices, history, editing and critical actions."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={() => navigate(ROUTES.servers)}>
            Back
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => void load(true)} disabled={pending}>
            {pending ? "Loading..." : "Refresh"}
          </button>
          <button className="btn btn-secondary" type="button" onClick={onRuntimeCheck} disabled={checkPending || pending}>
            {checkPending ? "Checking..." : "Check runtime"}
          </button>
          <label className="toggle-field">
            <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
            <span>Auto refresh (12s)</span>
          </label>
        </div>
      }
    >
      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      {!detail ? (
        <div className="empty-banner">{pending ? "Loading server detail..." : "Server not found."}</div>
      ) : (
        <>
          <div className="metric-grid">
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone primary" />
                <h3>Health</h3>
              </div>
              <div className="metric-value">
                <span className={`status-tag ${formatRuntimeHealth(runtime?.health)}`}>{runtime?.health || "-"}</span>
              </div>
              <div className="metric-note">Service {runtime?.xray_state || "-"}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone warning" />
                <h3>Latency</h3>
              </div>
              <div className="metric-value">{runtime?.vpn_latency_text || "-"}</div>
              <div className="metric-note">Loadavg {runtime?.loadavg || "-"}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone success" />
                <h3>Active Configs</h3>
              </div>
              <div className="metric-value">{metrics?.active_configs ?? 0}</div>
              <div className="metric-note">Users {metrics?.active_users ?? 0} | Devices {metrics?.active_devices ?? 0}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone primary" />
                <h3>Established</h3>
              </div>
              <div className="metric-value">{metrics?.established_connections ?? 0}</div>
              <div className="metric-note">Live devices now {metrics?.live_active_devices_count ?? 0}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone warning" />
                <h3>Created / Revoked 24h</h3>
              </div>
              <div className="metric-value">
                {metrics?.created_24h ?? 0} / {metrics?.revoked_24h ?? 0}
              </div>
              <div className="metric-note">Total configs {metrics?.total_configs ?? 0}</div>
            </article>
          </div>

          <div className="split-2" style={{ marginTop: 14 }}>
            <section className="subpanel">
              <div className="subpanel-head">
                <h3>Runtime</h3>
              </div>
              <div className="table-shell">
                <table className="data-table">
                  <tbody>
                    <tr>
                      <td>Host</td>
                      <td>{server!.host}:{server!.port}</td>
                      <td>Protocol</td>
                      <td>{server!.protocol}</td>
                    </tr>
                    <tr>
                      <td>SNI</td>
                      <td>{server!.sni}</td>
                      <td>Service</td>
                      <td>{runtime?.service_name || "-"}</td>
                    </tr>
                    <tr>
                      <td>Version</td>
                      <td>{runtime?.version || "-"}</td>
                      <td>Uptime</td>
                      <td>{runtime?.uptime || "-"}</td>
                    </tr>
                    <tr>
                      <td>RAM Used</td>
                      <td>{runtime?.mem_used_pct ?? "-"}%</td>
                      <td>Loadavg</td>
                      <td>{runtime?.loadavg || "-"}</td>
                    </tr>
                    <tr>
                      <td>Net RX</td>
                      <td>{runtime?.net_rx_text || "-"}</td>
                      <td>Net TX</td>
                      <td>{runtime?.net_tx_text || "-"}</td>
                    </tr>
                    <tr>
                      <td>Reachable</td>
                      <td>{runtime?.vpn_reachable ? "yes" : "no"}</td>
                      <td>Port open</td>
                      <td>{runtime?.port_open ? "yes" : "no"}</td>
                    </tr>
                    <tr>
                      <td>Error</td>
                      <td colSpan={3}>{runtime?.error || "-"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section className="subpanel">
              <div className="subpanel-head">
                <h3>Danger Zone</h3>
              </div>
              <div className="row-actions" style={{ marginBottom: 10 }}>
                <button className="btn btn-secondary" type="button" onClick={() => void runAction(`/admin/action/server/${server!.id}/restart`).then(async (ok) => ok && load(true))}>
                  Restart service
                </button>
                <button className="btn btn-secondary" type="button" onClick={() => void runAction(`/admin/action/server/${server!.id}/sync-devices`).then(async (ok) => ok && load(true))}>
                  Sync devices
                </button>
                <button className="btn btn-secondary" type="button" onClick={() => void runAction(`/admin/action/server/${server!.id}/toggle-enabled`).then(async (ok) => ok && load(true))}>
                  {server!.enabled ? "Disable server" : "Enable server"}
                </button>
                <button className="btn btn-secondary" type="button" onClick={() => void onDeleteServer()}>
                  Delete server
                </button>
              </div>
              <div className="data-stamp">Delete removes the server and all linked local records.</div>
            </section>
          </div>

          <section className="subpanel" style={{ marginTop: 14 }}>
            <div className="subpanel-head">
              <h3>Edit Server</h3>
            </div>
            <form className="form-grid" onSubmit={onSaveServer}>
              <input className="control-input" value={server!.name} onChange={(e) => patchServer("name", e.target.value)} />
              <select className="control-select" value={server!.protocol} onChange={(e) => patchServer("protocol", e.target.value)}>
                <option value="vless_reality">vless_reality</option>
                <option value="hysteria2">hysteria2</option>
              </select>
              <input className="control-input" value={server!.host} onChange={(e) => patchServer("host", e.target.value)} />
              <input className="control-input" value={server!.port} onChange={(e) => patchServer("port", toInt(e.target.value))} />
              <input className="control-input" value={server!.sni} onChange={(e) => patchServer("sni", e.target.value)} />
              <input className="control-input" value={server!.public_key} onChange={(e) => patchServer("public_key", e.target.value)} />
              <input className="control-input" value={server!.short_id} onChange={(e) => patchServer("short_id", e.target.value)} />
              <input className="control-input" value={server!.fingerprint} onChange={(e) => patchServer("fingerprint", e.target.value)} />
              <input className="control-input" value={server!.hy2_alpn} onChange={(e) => patchServer("hy2_alpn", e.target.value)} />
              <input className="control-input" value={server!.hy2_obfs} onChange={(e) => patchServer("hy2_obfs", e.target.value)} />
              <input className="control-input" value={server!.hy2_obfs_password} onChange={(e) => patchServer("hy2_obfs_password", e.target.value)} />
              <label className="toggle-field">
                <input type="checkbox" checked={server!.hy2_insecure} onChange={(e) => patchServer("hy2_insecure", e.target.checked)} />
                <span>HY2 insecure</span>
              </label>
              <input className="control-input" value={server!.ssh_host} onChange={(e) => patchServer("ssh_host", e.target.value)} />
              <input className="control-input" value={server!.ssh_port} onChange={(e) => patchServer("ssh_port", toInt(e.target.value))} />
              <input className="control-input" value={server!.ssh_user} onChange={(e) => patchServer("ssh_user", e.target.value)} />
              <input className="control-input" value={server!.ssh_key_path} onChange={(e) => patchServer("ssh_key_path", e.target.value)} />
              <input className="control-input" value={server!.remote_add_script} onChange={(e) => patchServer("remote_add_script", e.target.value)} />
              <input className="control-input" value={server!.remote_remove_script} onChange={(e) => patchServer("remote_remove_script", e.target.value)} />
              <label className="toggle-field">
                <input type="checkbox" checked={server!.enabled} onChange={(e) => patchServer("enabled", e.target.checked)} />
                <span>Enabled</span>
              </label>
              <button className="btn" type="submit">
                Save server
              </button>
            </form>
          </section>

          <div className="split-2" style={{ marginTop: 14 }}>
            <section className="subpanel">
              <div className="subpanel-head">
                <h3>Live Active Devices</h3>
              </div>
              {detail.live_active_devices_error ? <div className="error-banner">{detail.live_active_devices_error}</div> : null}
              <div className="table-shell">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Device</th>
                      <th>Telegram</th>
                      <th>Traffic delta</th>
                      <th>Configs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.live_active_devices.map((row) => (
                      <tr key={`${row.telegram_id}-${row.device_name}`}>
                        <td>{row.device_name}</td>
                        <td>{row.telegram_id}</td>
                        <td>{row.traffic_delta_text}</td>
                        <td>{row.server_config_count}</td>
                      </tr>
                    ))}
                    {!detail.live_active_devices.length ? (
                      <tr>
                        <td colSpan={4}>
                          <div className="empty-banner">No active devices in sample window.</div>
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
                      <th>Device</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Revoked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.recent_configs.map((row) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td>{row.telegram_id}</td>
                        <td>{row.device_name}</td>
                        <td>
                          <span className={`status-tag ${row.is_active ? "success" : "warning"}`}>
                            {row.is_active ? "active" : "revoked"}
                          </span>
                        </td>
                        <td>{row.created_at}</td>
                        <td>{row.revoked_at}</td>
                      </tr>
                    ))}
                    {!detail.recent_configs.length ? (
                      <tr>
                        <td colSpan={6}>
                          <div className="empty-banner">No configs found.</div>
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
                <h3>Latency / Load / Connections (last 20)</h3>
              </div>
              <div className="table-shell">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Latency ms</th>
                      <th>Load1</th>
                      <th>Established</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyRows.latency.map((row, index) => (
                      <tr key={`${row.ts}-${index}`}>
                        <td>{row.ts}</td>
                        <td>{row.latency_ms}</td>
                        <td>{historyRows.load[index]?.load1 ?? 0}</td>
                        <td>{historyRows.connections[index]?.established_connections ?? 0}</td>
                      </tr>
                    ))}
                    {!historyRows.latency.length ? (
                      <tr>
                        <td colSpan={4}>
                          <div className="empty-banner">No history samples.</div>
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="subpanel">
              <div className="subpanel-head">
                <h3>New Configs per Day (14d)</h3>
              </div>
              <div className="table-shell">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyRows.daily.map((row) => (
                      <tr key={row.day}>
                        <td>{row.day}</td>
                        <td>{row.count}</td>
                      </tr>
                    ))}
                    {!historyRows.daily.length ? (
                      <tr>
                        <td colSpan={2}>
                          <div className="empty-banner">No daily stats.</div>
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      )}
    </PageSection>
  );
}
