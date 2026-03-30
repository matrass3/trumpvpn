import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminUsers, type AdminUser } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

type StatusFilter = "all" | "active" | "expired" | "no_sub" | "blocked";

export function UsersPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminUser[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);

  const [quickTelegramId, setQuickTelegramId] = useState("");
  const [quickDays, setQuickDays] = useState("30");

  const canPrev = useMemo(() => Boolean(pagination?.has_prev), [pagination]);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminUsers({ q, status, page, page_size: 50 });
      setItems(response.items || []);
      setPagination(response.pagination || null);
    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      const message = error instanceof Error ? error.message : "Failed to load users";
      flash.showError(message);
    } finally {
      setPending(false);
    }
  }, [flash, navigate, page, q, status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runAction(actionPath: string, body: Record<string, string | number | boolean> = {}) {
    const result = await submitAdminActionSafely(actionPath, body);
    if (result.error) {
      flash.showError(result.error);
    } else if (result.message) {
      flash.showMessage(result.message);
    } else {
      flash.showMessage("Action completed");
    }
    await load();
  }

  return (
    <PageSection
      title="Users"
      description="Users workspace: subscriptions, blocking, devices, configs, and payments."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
            {pending ? "Loading..." : "Refresh"}
          </button>
        </div>
      }
    >
      <div className="inline-form-row">
        <input
          className="control-input"
          placeholder="Quick telegram id"
          value={quickTelegramId}
          onChange={(event) => setQuickTelegramId(event.target.value)}
        />
        <input
          className="control-input"
          placeholder="Days"
          value={quickDays}
          onChange={(event) => setQuickDays(event.target.value)}
        />
        <div className="row-actions">
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() =>
              void runAction("/admin/action/subscription/add", {
                telegram_id: quickTelegramId,
                days: quickDays,
              })
            }
          >
            Add days
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() =>
              void runAction("/admin/action/user/revoke-configs", {
                telegram_id: quickTelegramId,
              })
            }
          >
            Revoke configs
          </button>
        </div>
      </div>

      <div className="filter-row">
        <input
          className="control-input"
          placeholder="Search by telegram id or username"
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
          <option value="all">All users</option>
          <option value="active">Active subscription</option>
          <option value="expired">Expired subscription</option>
          <option value="no_sub">No subscription</option>
          <option value="blocked">Blocked</option>
        </select>
        <div className="filter-meta">{pagination ? `Total ${pagination.total}` : ""}</div>
      </div>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>Telegram</th>
              <th>User</th>
              <th>Subscription</th>
              <th>Balance</th>
              <th>Configs</th>
              <th>Payments</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.telegram_id}>
                <td>{row.telegram_id}</td>
                <td>{row.username || "-"}</td>
                <td>{row.subscription_until}</td>
                <td>{row.balance_rub}</td>
                <td>{row.configs_active}/{row.configs_total}</td>
                <td>{row.paid_count} / {row.paid_sum} RUB</td>
                <td>
                  <span className={`status-tag ${row.is_blocked ? "danger" : row.subscription_active ? "success" : "warning"}`}>
                    {row.is_blocked ? "blocked" : row.subscription_active ? "active" : "inactive"}
                  </span>
                </td>
                <td>
                  <div className="row-actions">
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/configs?q=${row.telegram_id}`)}>
                      Configs
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/payments?q=${row.telegram_id}`)}>
                      Payments
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/users/${row.telegram_id}/devices`)}>
                      Devices
                    </button>
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() => void runAction(`/admin/action/user/${row.telegram_id}/toggle-block`)}
                    >
                      {row.is_blocked ? "Unblock" : "Block"}
                    </button>
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() => void runAction(`/admin/action/user/${row.telegram_id}/revoke-configs`)}
                    >
                      Revoke
                    </button>
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() =>
                        void runAction("/admin/action/subscription/add", {
                          telegram_id: row.telegram_id,
                          days: quickDays,
                        })
                      }
                    >
                      +Days
                    </button>
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() => void runAction(`/admin/action/subscription/remove/${row.telegram_id}`)}
                    >
                      Remove sub
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={8}>
                  <div className="empty-banner">No users found.</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <Pager
        pagination={pagination}
        onPageChange={(nextPage) => {
          if (nextPage === page) {
            return;
          }
          if (nextPage < page && !canPrev) {
            return;
          }
          setPage(nextPage);
        }}
      />
    </PageSection>
  );
}
