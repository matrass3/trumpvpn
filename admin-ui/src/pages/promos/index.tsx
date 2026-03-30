import { FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminPromos, type AdminPromo, type PromoUse } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { Pager, type PaginationMeta } from "../../shared/ui/Pager";
import { PageSection } from "../../shared/ui/PageSection";

export function PromosPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminPromo[]>([]);
  const [uses, setUses] = useState<PromoUse[]>([]);
  const [usesPagination, setUsesPagination] = useState<PaginationMeta | null>(null);
  const [pending, setPending] = useState(false);
  const [usesQ, setUsesQ] = useState("");
  const [usesPage, setUsesPage] = useState(1);

  const [code, setCode] = useState("");
  const [kind, setKind] = useState("balance_rub");
  const [valueInt, setValueInt] = useState("100");
  const [maxUsesTotal, setMaxUsesTotal] = useState("0");
  const [maxUsesPerUser, setMaxUsesPerUser] = useState("1");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [enabled, setEnabled] = useState(true);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminPromos({ uses_q: usesQ, uses_page: usesPage, uses_page_size: 100 });
      setItems(response.items || []);
      setUses(response.uses.items || []);
      setUsesPagination(response.uses.pagination || null);

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load promos");
    } finally {
      setPending(false);
    }
  }, [flash, navigate, usesPage, usesQ]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSavePromo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await submitAdminActionSafely("/admin/action/promo/save", {
      code,
      kind,
      value_int: valueInt,
      max_uses_total: maxUsesTotal,
      max_uses_per_user: maxUsesPerUser,
      starts_at: startsAt,
      ends_at: endsAt,
      enabled,
    });
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || `Promo ${code} saved`);
      setCode("");
    }
    await load();
  }

  async function promoAction(promoId: number, action: "toggle" | "delete") {
    const result = await submitAdminActionSafely(`/admin/action/promo/${promoId}/${action}`);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || `Promo ${action}`);
    }
    await load();
  }

  return (
    <PageSection
      title="Promos"
      description="Create, update, enable, and archive promo codes."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      <form className="form-grid" onSubmit={onSavePromo}>
        <input className="control-input" placeholder="Code" value={code} onChange={(e) => setCode(e.target.value)} required />
        <select className="control-select" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="balance_rub">Balance RUB</option>
          <option value="topup_discount_percent">Topup Discount %</option>
          <option value="subscription_days">Subscription Days</option>
        </select>
        <input className="control-input" placeholder="Value" value={valueInt} onChange={(e) => setValueInt(e.target.value)} required />
        <input
          className="control-input"
          placeholder="Max total uses (0=inf)"
          value={maxUsesTotal}
          onChange={(e) => setMaxUsesTotal(e.target.value)}
        />
        <input
          className="control-input"
          placeholder="Max per user (0=inf)"
          value={maxUsesPerUser}
          onChange={(e) => setMaxUsesPerUser(e.target.value)}
        />
        <input
          className="control-input"
          placeholder="Starts at YYYY-MM-DDTHH:MM"
          value={startsAt}
          onChange={(e) => setStartsAt(e.target.value)}
        />
        <input
          className="control-input"
          placeholder="Ends at YYYY-MM-DDTHH:MM"
          value={endsAt}
          onChange={(e) => setEndsAt(e.target.value)}
        />
        <label className="toggle-field">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>Enabled</span>
        </label>
        <button className="btn" type="submit">
          Save Promo
        </button>
      </form>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell" style={{ marginTop: 12 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Code</th>
              <th>Kind</th>
              <th>Value</th>
              <th>Uses</th>
              <th>Limits</th>
              <th>Window</th>
              <th>Enabled</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((promo) => (
              <tr key={promo.id}>
                <td>{promo.id}</td>
                <td>{promo.code}</td>
                <td>{promo.kind}</td>
                <td>{promo.value_int}</td>
                <td>{promo.uses_total}</td>
                <td>
                  total {promo.max_uses_total || "inf"} / user {promo.max_uses_per_user || "inf"}
                </td>
                <td>
                  {promo.starts_at} - {promo.ends_at}
                </td>
                <td>
                  <span className={`status-tag ${promo.enabled ? "success" : "warning"}`}>{promo.enabled ? "yes" : "no"}</span>
                </td>
                <td>
                  <div className="row-actions">
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void promoAction(promo.id, "toggle")}>
                      Toggle
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void promoAction(promo.id, "delete")}>
                      Archive
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={9}>
                  <div className="empty-banner">No promos created yet.</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <section className="subpanel" style={{ marginTop: 14 }}>
        <div className="subpanel-head">
          <h3>Promo Uses</h3>
          <input
            className="control-input"
            placeholder="Search by code / tg id / kind"
            value={usesQ}
            onChange={(event) => {
              setUsesQ(event.target.value);
              setUsesPage(1);
            }}
            style={{ maxWidth: 320 }}
          />
        </div>
        <div className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Code</th>
                <th>Telegram</th>
                <th>Kind</th>
                <th>Value</th>
                <th>Invoice</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {uses.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.code}</td>
                  <td>{row.telegram_id}</td>
                  <td>{row.kind}</td>
                  <td>{row.value_int}</td>
                  <td>{row.payment_invoice_id ?? "-"}</td>
                  <td>{row.created_at}</td>
                </tr>
              ))}
              {!uses.length ? (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-banner">No promo uses found.</div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <Pager pagination={usesPagination} onPageChange={setUsesPage} />
      </section>
    </PageSection>
  );
}
