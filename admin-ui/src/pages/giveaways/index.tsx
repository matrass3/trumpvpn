import { FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminGiveaways, type AdminGiveaway } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { PageSection } from "../../shared/ui/PageSection";

export function GiveawaysPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [items, setItems] = useState<AdminGiveaway[]>([]);
  const [pending, setPending] = useState(false);

  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("channel_sub");
  const [prize, setPrize] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [duration, setDuration] = useState("1d");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminGiveaways();
      setItems(response.items || []);

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load giveaways");
    } finally {
      setPending(false);
    }
  }, [flash, navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await submitAdminActionSafely("/admin/action/giveaway/save", {
      title,
      kind,
      prize,
      starts_at: startsAt,
      duration,
      description,
      enabled,
    });
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || "Giveaway created");
      setTitle("");
      setPrize("");
      setDescription("");
    }
    await load();
  }

  async function giveawayAction(id: number, action: "toggle" | "draw" | "end" | "reroll" | "delete") {
    const result = await submitAdminActionSafely(`/admin/action/giveaway/${id}/${action}`);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || `Giveaway ${action} complete`);
    }
    await load();
  }

  return (
    <PageSection
      title="Giveaways"
      description="Create giveaways, pick winners, and close campaigns."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      <form className="form-grid" onSubmit={onCreate}>
        <input className="control-input" placeholder="Title" value={title} onChange={(event) => setTitle(event.target.value)} required />
        <select className="control-select" value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="channel_sub">Channel subscription</option>
          <option value="active_sub_min_deposit">Active subscription + min deposit</option>
          <option value="referral_leader">Referral leader</option>
        </select>
        <input className="control-input" placeholder="Prize" value={prize} onChange={(event) => setPrize(event.target.value)} />
        <input
          className="control-input"
          placeholder="Starts at YYYY-MM-DDTHH:MM"
          value={startsAt}
          onChange={(event) => setStartsAt(event.target.value)}
        />
        <input className="control-input" placeholder="Duration (1h, 1d)" value={duration} onChange={(event) => setDuration(event.target.value)} />
        <label className="toggle-field">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          <span>Enabled</span>
        </label>
        <textarea
          className="control-input"
          placeholder="Description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={3}
          style={{ gridColumn: "1 / -1", resize: "vertical" }}
        />
        <button className="btn" type="submit">
          Create Giveaway
        </button>
      </form>

      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <div className="table-shell" style={{ marginTop: 12 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Type</th>
              <th>Prize</th>
              <th>Window</th>
              <th>Participants</th>
              <th>Winners</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>
                  <div className="table-node">
                    <strong>{row.title}</strong>
                    <span>{row.description || "-"}</span>
                  </div>
                </td>
                <td>{row.kind_title}</td>
                <td>{row.prize || "-"}</td>
                <td>
                  {row.starts_at} - {row.ends_at}
                </td>
                <td>{row.participants}</td>
                <td>{(row.winners || []).map((w) => w.telegram_id).join(", ") || "-"}</td>
                <td>
                  <span className={`status-tag ${row.active ? "success" : row.enabled ? "warning" : "danger"}`}>
                    {row.active ? "active" : row.enabled ? "enabled" : "disabled"}
                  </span>
                </td>
                <td>
                  <div className="row-actions">
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void giveawayAction(row.id, "toggle")}>
                      Toggle
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void giveawayAction(row.id, "draw")}>
                      Draw
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void giveawayAction(row.id, "end")}>
                      End
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void giveawayAction(row.id, "reroll")}>
                      Reroll
                    </button>
                    <button className="btn btn-secondary btn-xs" type="button" onClick={() => void giveawayAction(row.id, "delete")}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!items.length ? (
              <tr>
                <td colSpan={9}>
                  <div className="empty-banner">No giveaways yet.</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </PageSection>
  );
}
