import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getAdminSubscriptions, type AdminSubscription } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

type StatusFilter = "all" | "active" | "expired";

export function SubscriptionsPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminSubscription[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);

  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(() => String(searchParams.get("q") || ""));
  const [status, setStatus] = useState<StatusFilter>(() => (searchParams.get("status") as StatusFilter) || "all");
  const [page, setPage] = useState(() => {
    const value = Number(searchParams.get("page") || 1);
    return Number.isFinite(value) && value > 0 ? value : 1;
  });

  const [addTelegramId, setAddTelegramId] = useState("");
  const [addDays, setAddDays] = useState("30");

  const summary = useMemo(() => {
    const total = items.length;
    const active = items.filter((item) => item.is_active).length;
    return {
      total,
      active,
      expired: Math.max(0, total - active),
    };
  }, [items]);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminSubscriptions({ q, status, page, page_size: 50 });
      setItems(response.items || []);
      setPagination(response.pagination || null);
    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load subscriptions");
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

  async function onAddSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await submitAdminActionSafely("/admin/action/subscription/add", {
      telegram_id: addTelegramId,
      days: addDays,
    });
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || "Subscription updated");
      setAddTelegramId("");
    }
    await load();
  }

  async function removeSubscription(telegramId: number) {
    const result = await submitAdminActionSafely(`/admin/action/subscription/remove/${telegramId}`);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || "Subscription removed");
    }
    await load();
  }

  return (
    <PageSection
      title="Subscriptions"
      description="React page with full legacy functionality: add/extend, remove, filter, search and pagination."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
            {pending ? "Loading..." : "Refresh"}
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => navigate(ROUTES.payments)}>
            Open payments
          </button>
        </div>
      }
    >
      <div className="metric-grid" style={{ marginBottom: 12 }}>
        <article className="metric-card">
          <div className="metric-head">
            <span className="metric-tone primary" />
            <h3>Rows shown</h3>
          </div>
          <div className="metric-value">{summary.total}</div>
          <div className="metric-note">Current page</div>
        </article>
        <article className="metric-card">
          <div className="metric-head">
            <span className="metric-tone success" />
            <h3>Active</h3>
          </div>
          <div className="metric-value">{summary.active}</div>
          <div className="metric-note">In current list</div>
        </article>
        <article className="metric-card">
          <div className="metric-head">
            <span className="metric-tone warning" />
            <h3>Expired</h3>
          </div>
          <div className="metric-value">{summary.expired}</div>
          <div className="metric-note">In current list</div>
        </article>
      </div>

      <form className="inline-form-row" onSubmit={onAddSubscription}>
        <input
          className="control-input"
          placeholder="Telegram ID"
          value={addTelegramId}
          onChange={(event) => setAddTelegramId(event.target.value)}
          required
        />
        <input
          className="control-input"
          placeholder="Days"
          value={addDays}
          onChange={(event) => setAddDays(event.target.value)}
          required
        />
        <button className="btn" type="submit">
          Add / Extend
        </button>
      </form>

      <div className="filter-row">
        <input
          className="control-input"
          placeholder="Search by telegram or username"
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
          <option value="expired">Expired</option>
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
              <th>Balance</th>
              <th>Until</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.telegram_id}>
                <td>{row.telegram_id}</td>
                <td>{row.username || "-"}</td>
                <td>{row.balance_rub}</td>
                <td>{row.subscription_until}</td>
                <td>
                  <span className={`status-tag ${row.is_active ? "success" : "warning"}`}>
                    {row.is_active ? "active" : "expired"}
                  </span>
                </td>
                <td>
                  <div className="row-actions">
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/users?q=${row.telegram_id}`)}>
                      User
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => navigate(`/payments?q=${row.telegram_id}`)}>
                      Payments
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void removeSubscription(row.telegram_id)}>
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={6}>
                  <div className="empty-banner">No subscriptions found.</div>
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
