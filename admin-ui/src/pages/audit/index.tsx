import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminAudit, type AdminAuditRow } from "../../shared/api/adminData";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

export function AuditPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminAuditRow[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);
  const [q, setQ] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [availableActions, setAvailableActions] = useState<string[]>([]);
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminAudit({ q, action: actionFilter, page, page_size: 100 });
      setItems(response.items || []);
      setPagination(response.pagination || null);
      setAvailableActions(response.filters?.available_actions || []);

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load audit");
    } finally {
      setPending(false);
    }
  }, [actionFilter, flash, navigate, page, q]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageSection
      title="Audit"
      description="Administrator action log with search, filters, and pagination."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      <div className="filter-row filter-row-wide">
        <input
          className="control-input"
          placeholder="Search action, entity, id, path, details"
          value={q}
          onChange={(event) => {
            setQ(event.target.value);
            setPage(1);
          }}
        />
        <select
          className="control-select"
          value={actionFilter}
          onChange={(event) => {
            setActionFilter(event.target.value);
            setPage(1);
          }}
        >
          <option value="all">All actions</option>
          {availableActions.map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
        </select>
        <div className="filter-meta">{pagination ? `Total ${pagination.total}` : ""}</div>
      </div>

      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Created</th>
              <th>Admin</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Entity ID</th>
              <th>Path</th>
              <th>IP</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>{row.created_at}</td>
                <td>{row.admin_telegram_id}</td>
                <td>{row.action}</td>
                <td>{row.entity_type}</td>
                <td>{row.entity_id}</td>
                <td>{row.request_path}</td>
                <td>{row.remote_addr}</td>
                <td>
                  <code className="code-cell">{row.details_json || "-"}</code>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={9}>
                  <div className="empty-banner">No audit rows.</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <Pager pagination={pagination} onPageChange={setPage} />
    </PageSection>
  );
}
