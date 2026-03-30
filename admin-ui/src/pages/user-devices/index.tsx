import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getAdminUserDevices, type UserDevicesResponse } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { PageSection } from "../../shared/ui/PageSection";

export function UserDevicesPage() {
  const navigate = useNavigate();
  const flash = useFlash();
  const params = useParams<{ telegramId: string }>();
  const telegramId = Number(params.telegramId || 0);

  const [pending, setPending] = useState(false);
  const [data, setData] = useState<UserDevicesResponse | null>(null);

  const load = useCallback(async () => {
    if (!telegramId || telegramId <= 0) {
      flash.showError("Invalid telegram id");
      return;
    }
    setPending(true);
    try {
      const response = await getAdminUserDevices(telegramId);
      setData(response);
    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load user devices");
    } finally {
      setPending(false);
    }
  }, [flash, navigate, telegramId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function deleteDevice(deviceName: string) {
    if (!data) {
      return;
    }
    const confirmed = window.confirm(`Delete device ${deviceName}?`);
    if (!confirmed) {
      return;
    }
    const result = await submitAdminActionSafely(`/admin/action/user/${data.user.telegram_id}/device/delete`, {
      device_name: deviceName,
    });
    if (result.error) {
      flash.showError(result.error);
      return;
    }
    flash.showMessage(result.message || "Device deleted");
    await load();
  }

  return (
    <PageSection
      title={data ? `User Devices - ${data.user.telegram_id}` : "User Devices"}
      description="Full device management for a user, including deletion of all related configs."
      actions={
        <div className="toolbar-actions">
          <button className="btn btn-secondary" type="button" onClick={() => navigate(ROUTES.users)}>
            Back to users
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
            {pending ? "Loading..." : "Refresh"}
          </button>
        </div>
      }
    >
      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      {!data ? (
        <div className="empty-banner">{pending ? "Loading devices..." : "User not found."}</div>
      ) : (
        <>
          <div className="metric-grid">
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone primary" />
                <h3>Telegram</h3>
              </div>
              <div className="metric-value">{data.user.telegram_id}</div>
              <div className="metric-note">{data.user.username || "-"}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone success" />
                <h3>Subscription</h3>
              </div>
              <div className="metric-value">{data.user.subscription_until}</div>
              <div className="metric-note">{data.user.subscription_active ? "active" : "inactive"}</div>
            </article>
            <article className="metric-card">
              <div className="metric-head">
                <span className="metric-tone warning" />
                <h3>Balance</h3>
              </div>
              <div className="metric-value">{data.user.balance_rub} RUB</div>
              <div className="metric-note">{data.user.is_blocked ? "blocked" : "not blocked"}</div>
            </article>
          </div>

          <div className="table-shell" style={{ marginTop: 14 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Configs total</th>
                  <th>Configs active</th>
                  <th>Servers</th>
                  <th>Last config</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.device_name}>
                    <td>{row.device_name}</td>
                    <td>{row.configs_total}</td>
                    <td>{row.configs_active}</td>
                    <td>{row.servers_text}</td>
                    <td>{row.last_config_at}</td>
                    <td>
                      <button className="btn btn-secondary btn-xs" type="button" onClick={() => void deleteDevice(row.device_name)}>
                        Delete device
                      </button>
                    </td>
                  </tr>
                ))}
                {!data.items.length ? (
                  <tr>
                    <td colSpan={6}>
                      <div className="empty-banner">No devices.</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      )}
    </PageSection>
  );
}
