import type { RuntimeServer } from "../api/serversApi";

function healthTone(health: string): "success" | "warning" | "danger" {
  const value = String(health || "").toLowerCase();
  if (value === "ok") {
    return "success";
  }
  if (value === "degraded" || value === "skipped") {
    return "warning";
  }
  return "danger";
}

type ServerRuntimeListProps = {
  rows: RuntimeServer[];
};

export function ServerRuntimeList({ rows }: ServerRuntimeListProps) {
  if (!rows.length) {
    return <div className="empty-banner">No servers matched current filter.</div>;
  }

  return (
    <div className="table-shell">
      <table className="data-table">
        <thead>
          <tr>
            <th>Node</th>
            <th>Health</th>
            <th>Protocol</th>
            <th>Route</th>
            <th>Latency</th>
            <th>Active Configs</th>
            <th>Established</th>
            <th>Service</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tone = healthTone(row.runtime.health);
            return (
              <tr key={row.id}>
                <td>
                  <div className="table-node">
                    <strong>{row.name}</strong>
                    <span>{row.enabled ? "enabled" : "disabled"}</span>
                  </div>
                </td>
                <td>
                  <span className={`status-tag ${tone}`}>{row.runtime.health || "unknown"}</span>
                </td>
                <td>{row.protocol}</td>
                <td>
                  {row.host}:{row.port}
                </td>
                <td>{row.runtime.vpn_latency_text || "-"}</td>
                <td>{row.active_clients}</td>
                <td>{row.runtime.established_connections ?? "-"}</td>
                <td>{row.runtime.xray_state || "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
