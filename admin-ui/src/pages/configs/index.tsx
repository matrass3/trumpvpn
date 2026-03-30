import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getAdminConfigs, type AdminConfig } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

type StatusFilter = "all" | "active" | "revoked";

export function ConfigsPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminConfig[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(() => String(searchParams.get("q") || ""));
  const [status, setStatus] = useState<StatusFilter>(() => (searchParams.get("status") as StatusFilter) || "all");
  const [page, setPage] = useState(() => {
    const value = Number(searchParams.get("page") || 1);
    return Number.isFinite(value) && value > 0 ? value : 1;
  });

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminConfigs({ q, status, page, page_size: 50 });
      setItems(response.items || []);
      setPagination(response.pagination || null);

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load configs");
    } finally {
      setPending(false);
    }
  }, [flash, navigate, page, q, status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (q.trim()) {
      params.set("q", q.trim());
    }
    if (status !== "all") {
      params.set("status", status);
    }
    if (page > 1) {
      params.set("page", String(page));
    }
    setSearchParams(params, { replace: true });
  }, [page, q, setSearchParams, status]);

  async function revokeConfig(configId: number) {
    const result = await submitAdminActionSafely(`/admin/action/config/${configId}/delete`);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || `Config #${configId} revoked`);
    }
    await load();
  }

  return (
    <PageSection
      title="Configs"
      description="Client config list with revoke actions using current admin endpoints."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      <div className="filter-row">
        <input
          className="control-input"
          placeholder="Search by telegram, server, device"
          value={q}
          onChange={(event) => {
            setQ(event.target.value);
            setPage(1);
          }}
        />
        <select
          className="control-select"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as StatusFilter);
            setPage(1);
          }}
        >
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="revoked">Revoked</option>
        </select>
        <div className="filter-meta">{pagination ? `Total ${pagination.total}` : ""}</div>
      </div>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Telegram</th>
              <th>Server</th>
              <th>Device</th>
              <th>Status</th>
              <th>Created</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>{row.telegram_id}</td>
                <td>{row.server}</td>
                <td>{row.device_name}</td>
                <td>
                  <span className={`status-tag ${row.is_active ? "success" : "warning"}`}>
                    {row.is_active ? "active" : "revoked"}
                  </span>
                </td>
                <td>{row.created_at}</td>
                <td>
                  <button
                    className="btn btn-secondary btn-xs"
                    type="button"
                    disabled={!row.is_active}
                    onClick={() => void revokeConfig(row.id)}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={7}>
                  <div className="empty-banner">No configs found.</div>
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
