import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminServers, type AdminServerRow } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { PageSection } from "../../shared/ui/PageSection";

export function ServersPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [pending, setPending] = useState(false);
  const [items, setItems] = useState<AdminServerRow[]>([]);
  const [defaults, setDefaults] = useState<Record<string, string | number | boolean>>({});
  const [query, setQuery] = useState("");
  const [health, setHealth] = useState("all");

  const [vlessForm, setVlessForm] = useState({
    name: "",
    host: "",
    reality_block: "PUBLIC_KEY=\nSHORT_ID=\nSNI=www.cloudflare.com\nPORT=443",
    ssh_host: "",
    ssh_port: "",
    ssh_user: "",
    ssh_key_path: "",
  });

  const [hy2Form, setHy2Form] = useState({
    name: "",
    host: "",
    sni: "",
    port: "443",
    hy2_alpn: "h3",
    hy2_obfs: "",
    hy2_obfs_password: "",
    hy2_insecure: false,
    ssh_host: "",
    ssh_port: "",
    ssh_user: "",
    ssh_key_path: "",
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((row) => {
      if (health !== "all" && String(row.runtime.health || "").toLowerCase() !== health) {
        return false;
      }
      if (!q) {
        return true;
      }
      return `${row.name} ${row.host} ${row.protocol} ${row.ssh_host}`.toLowerCase().includes(q);
    });
  }, [health, items, query]);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminServers({ live: 0 });
      setItems(response.servers || []);
      setDefaults(response.defaults || {});
      setVlessForm((prev) => ({
        ...prev,
        ssh_port: String(response.defaults?.ssh_port || prev.ssh_port || "22"),
        ssh_user: String(response.defaults?.ssh_user || prev.ssh_user || "root"),
        ssh_key_path: String(response.defaults?.ssh_key_path || prev.ssh_key_path || ""),
      }));
      setHy2Form((prev) => ({
        ...prev,
        ssh_port: String(response.defaults?.ssh_port || prev.ssh_port || "22"),
        ssh_user: String(response.defaults?.ssh_user || prev.ssh_user || "root"),
        ssh_key_path: String(response.defaults?.ssh_key_path || prev.ssh_key_path || ""),
      }));
    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load servers");
    } finally {
      setPending(false);
    }
  }, [flash, navigate]);

  useEffect(() => {
    void load();
  }, [load]);


  async function runAction(path: string, body: Record<string, string | number | boolean> = {}) {
    const result = await submitAdminActionSafely(path, body);
    if (result.error) {
      flash.showError(result.error);
      return false;
    }
    flash.showMessage(result.message || "Action completed");
    await load();
    return true;
  }

  async function createVless(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await runAction("/admin/action/server/add", vlessForm);
    if (ok) {
      setVlessForm((prev) => ({ ...prev, name: "", host: "", ssh_host: "" }));
    }
  }

  async function createHy2(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await runAction("/admin/action/server/add-hysteria2", hy2Form);
    if (ok) {
      setHy2Form((prev) => ({ ...prev, name: "", host: "", sni: "", ssh_host: "" }));
    }
  }

  return (
    <PageSection
      title="Servers"
      description="Servers workspace: create nodes, monitor runtime, sync, restart, toggle, and delete."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
            {pending ? "Loading..." : "Refresh"}
          </button>
        </div>
      }
    >
      <div className="filter-row">
        <input
          className="control-input"
          placeholder="Search by name, host, protocol"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select className="control-select" value={health} onChange={(event) => setHealth(event.target.value)}>
          <option value="all">All health</option>
          <option value="ok">OK</option>
          <option value="degraded">Degraded</option>
          <option value="error">Error</option>
          <option value="skipped">Skipped</option>
        </select>
        <div className="filter-meta">Showing {filtered.length} / {items.length}</div>
      </div>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Protocol</th>
              <th>Host</th>
              <th>SSH</th>
              <th>Health</th>
              <th>Latency</th>
              <th>Clients</th>
              <th>Service</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.id}>
                <td>
                  <div className="table-node">
                    <strong>{row.name}</strong>
                    <span>{row.enabled ? "enabled" : "disabled"}</span>
                  </div>
                </td>
                <td>{row.protocol}</td>
                <td>{row.host}:{row.port}</td>
                <td>{row.ssh_host}</td>
                <td>
                  <span
                    className={`status-tag ${
                      row.runtime.health === "ok"
                        ? "success"
                        : row.runtime.health === "degraded" || row.runtime.health === "skipped"
                          ? "warning"
                          : "danger"
                    }`}
                  >
                    {row.runtime.health}
                  </span>
                </td>
                <td>{row.runtime.vpn_latency_text || "-"}</td>
                <td>{row.active_clients}</td>
                <td>{row.runtime.xray_state || "-"}</td>
                <td>
                  <div className="row-actions">
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/servers/${row.id}`)}>
                      Details
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void runAction(`/admin/action/server/${row.id}/restart`)}>
                      Restart
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void runAction(`/admin/action/server/${row.id}/sync-devices`)}>
                      Sync
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void runAction(`/admin/action/server/${row.id}/toggle-enabled`)}>
                      Toggle
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void runAction(`/admin/action/server/${row.id}/delete`)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!filtered.length ? (
              <tr>
                <td colSpan={9}>
                  <div className="empty-banner">No servers found.</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="split-2" style={{ marginTop: 14 }}>
        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Add VLESS Reality Server</h3>
          </div>
          <form className="form-grid" onSubmit={createVless}>
            <input className="control-input" placeholder="Name" value={vlessForm.name} onChange={(e) => setVlessForm((p) => ({ ...p, name: e.target.value }))} />
            <input className="control-input" placeholder="Host" value={vlessForm.host} onChange={(e) => setVlessForm((p) => ({ ...p, host: e.target.value }))} required />
            <textarea
              className="control-input"
              rows={5}
              value={vlessForm.reality_block}
              onChange={(e) => setVlessForm((p) => ({ ...p, reality_block: e.target.value }))}
              style={{ gridColumn: "1 / -1", resize: "vertical" }}
            />
            <input className="control-input" placeholder="SSH host" value={vlessForm.ssh_host} onChange={(e) => setVlessForm((p) => ({ ...p, ssh_host: e.target.value }))} />
            <input className="control-input" placeholder={`SSH port (${defaults.ssh_port ?? 22})`} value={vlessForm.ssh_port} onChange={(e) => setVlessForm((p) => ({ ...p, ssh_port: e.target.value }))} />
            <input className="control-input" placeholder={`SSH user (${defaults.ssh_user ?? "root"})`} value={vlessForm.ssh_user} onChange={(e) => setVlessForm((p) => ({ ...p, ssh_user: e.target.value }))} />
            <input className="control-input" placeholder="SSH key path" value={vlessForm.ssh_key_path} onChange={(e) => setVlessForm((p) => ({ ...p, ssh_key_path: e.target.value }))} />
            <button className="btn" type="submit">
              Add VLESS Server
            </button>
          </form>
        </section>

        <section className="subpanel">
          <div className="subpanel-head">
            <h3>Add Hysteria2 Server</h3>
          </div>
          <form className="form-grid" onSubmit={createHy2}>
            <input className="control-input" placeholder="Name" value={hy2Form.name} onChange={(e) => setHy2Form((p) => ({ ...p, name: e.target.value }))} required />
            <input className="control-input" placeholder="Host" value={hy2Form.host} onChange={(e) => setHy2Form((p) => ({ ...p, host: e.target.value }))} required />
            <input className="control-input" placeholder="SNI" value={hy2Form.sni} onChange={(e) => setHy2Form((p) => ({ ...p, sni: e.target.value }))} required />
            <input className="control-input" placeholder="Port" value={hy2Form.port} onChange={(e) => setHy2Form((p) => ({ ...p, port: e.target.value }))} />
            <input className="control-input" placeholder="ALPN" value={hy2Form.hy2_alpn} onChange={(e) => setHy2Form((p) => ({ ...p, hy2_alpn: e.target.value }))} />
            <input className="control-input" placeholder="OBFS" value={hy2Form.hy2_obfs} onChange={(e) => setHy2Form((p) => ({ ...p, hy2_obfs: e.target.value }))} />
            <input className="control-input" placeholder="OBFS password" value={hy2Form.hy2_obfs_password} onChange={(e) => setHy2Form((p) => ({ ...p, hy2_obfs_password: e.target.value }))} />
            <label className="toggle-field">
              <input
                type="checkbox"
                checked={hy2Form.hy2_insecure}
                onChange={(e) => setHy2Form((p) => ({ ...p, hy2_insecure: e.target.checked }))}
              />
              <span>Insecure</span>
            </label>
            <input className="control-input" placeholder="SSH host" value={hy2Form.ssh_host} onChange={(e) => setHy2Form((p) => ({ ...p, ssh_host: e.target.value }))} />
            <input className="control-input" placeholder={`SSH port (${defaults.ssh_port ?? 22})`} value={hy2Form.ssh_port} onChange={(e) => setHy2Form((p) => ({ ...p, ssh_port: e.target.value }))} />
            <input className="control-input" placeholder={`SSH user (${defaults.ssh_user ?? "root"})`} value={hy2Form.ssh_user} onChange={(e) => setHy2Form((p) => ({ ...p, ssh_user: e.target.value }))} />
            <input className="control-input" placeholder="SSH key path" value={hy2Form.ssh_key_path} onChange={(e) => setHy2Form((p) => ({ ...p, ssh_key_path: e.target.value }))} />
            <button className="btn" type="submit">
              Add HY2 Server
            </button>
          </form>
        </section>
      </div>
    </PageSection>
  );
}
