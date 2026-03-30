import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getAdminPayments, type AdminPayment } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

type StatusFilter = "all" | "active" | "paid" | "rejected";

export function PaymentsPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminPayment[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(() => String(searchParams.get("q") || ""));
  const [status, setStatus] = useState<StatusFilter>(() => (searchParams.get("status") as StatusFilter) || "all");
  const [kind, setKind] = useState(() => String(searchParams.get("kind") || "all"));
  const [page, setPage] = useState(() => {
    const value = Number(searchParams.get("page") || 1);
    return Number.isFinite(value) && value > 0 ? value : 1;
  });

  const kinds = useMemo(() => {
    const values = new Set<string>(["all"]);
    for (const item of items) {
      values.add(item.kind || "-");
    }
    return Array.from(values);
  }, [items]);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminPayments({ q, status, kind, page, page_size: 50 });
      setItems(response.items || []);
      setPagination(response.pagination || null);

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load payments");
    } finally {
      setPending(false);
    }
  }, [flash, kind, navigate, page, q, status]);

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
    if (kind !== "all") {
      params.set("kind", kind);
    }
    if (page > 1) {
      params.set("page", String(page));
    }
    setSearchParams(params, { replace: true });
  }, [kind, page, q, setSearchParams, status]);

  async function paymentAction(invoiceId: number, action: "approve" | "reject") {
    const result = await submitAdminActionSafely(`/admin/action/payment/${invoiceId}/${action}`);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || `Payment ${invoiceId} ${action}`);
    }
    await load();
  }

  return (
    <PageSection
      title="Payments"
      description="Payment invoices with status tracking and manual approve/reject actions."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      <div className="filter-row filter-row-wide">
        <input
          className="control-input"
          placeholder="Search: invoice id, telegram, promo, hash"
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
          <option value="all">All status</option>
          <option value="active">Active</option>
          <option value="paid">Paid</option>
          <option value="rejected">Rejected</option>
        </select>
        <select
          className="control-select"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value);
            setPage(1);
          }}
        >
          {kinds.map((kindValue) => (
            <option key={kindValue} value={kindValue}>
              {kindValue}
            </option>
          ))}
        </select>
        <div className="filter-meta">{pagination ? `Total ${pagination.total}` : ""}</div>
      </div>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell">
        <table className="data-table">
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Telegram</th>
              <th>Amount</th>
              <th>Payable</th>
              <th>Credited</th>
              <th>Referral Bonus</th>
              <th>Kind</th>
              <th>Promo</th>
              <th>Status</th>
              <th>Paid At</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.invoice_id}>
                <td>{row.invoice_id}</td>
                <td>{row.telegram_id}</td>
                <td>{row.amount_rub}</td>
                <td>{row.payable_rub}</td>
                <td>{row.credited_rub}</td>
                <td>{row.referral_bonus_rub}</td>
                <td>{row.kind}</td>
                <td>
                  {row.promo_code || "-"} ({row.promo_discount_percent || 0}%)
                </td>
                <td>
                  <span
                    className={`status-tag ${
                      row.status === "paid" ? "success" : row.status === "rejected" ? "danger" : "warning"
                    }`}
                  >
                    {row.status}
                  </span>
                </td>
                <td>{row.paid_at}</td>
                <td>
                  <div className="row-actions">
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() => void paymentAction(row.invoice_id, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      className="btn btn-secondary btn-xs"
                      type="button"
                      onClick={() => void paymentAction(row.invoice_id, "reject")}
                    >
                      Reject
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={11}>
                  <div className="empty-banner">No payments found.</div>
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
