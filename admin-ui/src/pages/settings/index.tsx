import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAdminSettings } from "../../shared/api/adminData";
import { submitAdminActionSafely } from "../../shared/api/adminAction";
import { isUnauthorizedError } from "../../shared/api/httpClient";
import { ROUTES } from "../../shared/config/routes";
import { useFlash } from "../../shared/hooks/useFlash";
import { PageSection } from "../../shared/ui/PageSection";

type FormMap = Record<string, string>;

const numericKeys = new Set([
  "api_port",
  "admin_telegram_id",
  "giveaway_admin_telegram_id",
  "admin_session_hours",
  "subscription_price_rub",
  "subscription_days_per_month",
  "welcome_bonus_days",
  "referral_bonus_percent",
  "max_active_configs_per_user",
  "min_topup_rub",
  "max_topup_rub",
  "payments_notify_chat_id",
  "crypto_pay_invoice_expires_in",
  "platega_payment_method",
  "platega_payment_method_card",
  "platega_payment_method_sbp",
  "platega_payment_method_crypto",
]);

const secretKeys = [
  "admin_panel_password",
  "admin_session_secret",
  "internal_api_token",
  "crypto_pay_api_token",
  "yoomoney_notification_secret",
  "platega_merchant_id",
  "platega_api_key",
  "bot_token",
];

export function SettingsPage() {
  const navigate = useNavigate();
  const flash = useFlash();

  const [pending, setPending] = useState(false);
  const [formData, setFormData] = useState<FormMap>({});
  const [masked, setMasked] = useState<Record<string, string>>({});
  const [secretData, setSecretData] = useState<FormMap>({});

  const editableKeys = useMemo(() => Object.keys(formData).sort(), [formData]);

  const load = useCallback(async () => {
    setPending(true);
    try {
      const response = await getAdminSettings();
      const values: FormMap = {};
      for (const [key, value] of Object.entries(response.values || {})) {
        values[key] = String(value ?? "");
      }
      setFormData(values);
      setMasked(response.masked || {});

    } catch (error) {
      if (isUnauthorizedError(error)) {
        navigate(ROUTES.login, { replace: true });
        return;
      }
      flash.showError(error instanceof Error ? error.message : "Failed to load settings");
    } finally {
      setPending(false);
    }
  }, [flash, navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload: Record<string, string> = { ...formData };
    if (payload.max_active_configs_per_user !== undefined) {
      payload.MAX_ACTIVE_CONFIGS_PER_USER = payload.max_active_configs_per_user;
      delete payload.max_active_configs_per_user;
    }
    for (const key of secretKeys) {
      const value = String(secretData[key] || "").trim();
      if (value) {
        payload[key] = value;
      }
    }
    const result = await submitAdminActionSafely("/admin/settings/update", payload);
    if (result.error) {
      flash.showError(result.error);
    } else {
      flash.showMessage(result.message || "Settings updated");
      setSecretData({});
      await load();
    }
  }

  return (
    <PageSection
      title="Settings"
      description="Runtime panel settings persisted to .env through existing backend workflow."
      actions={
        <button className="btn btn-secondary" type="button" onClick={() => void load()} disabled={pending}>
          {pending ? "Loading..." : "Refresh"}
        </button>
      }
    >
      {flash.message ? <div className="success-banner">{flash.message}</div> : null}
      {flash.error ? <div className="error-banner">{flash.error}</div> : null}

      <form onSubmit={onSubmit} className="settings-grid">
        {editableKeys.map((key) => (
          <label className="field" key={key}>
            <span>{key}</span>
            <input
              className="control-input"
              type={numericKeys.has(key) ? "number" : "text"}
              value={formData[key] ?? ""}
              onChange={(event) =>
                setFormData((prev) => ({
                  ...prev,
                  [key]: event.target.value,
                }))
              }
            />
          </label>
        ))}

        <div className="subpanel" style={{ gridColumn: "1 / -1" }}>
          <div className="subpanel-head">
            <h3>Secrets (leave empty to keep unchanged)</h3>
          </div>
          <div className="settings-grid">
            {secretKeys.map((key) => (
              <label className="field" key={key}>
                <span>
                  {key} <small className="muted-inline">current: {masked[key] || "-"}</small>
                </span>
                <input
                  className="control-input"
                  type="password"
                  value={secretData[key] ?? ""}
                  onChange={(event) =>
                    setSecretData((prev) => ({
                      ...prev,
                      [key]: event.target.value,
                    }))
                  }
                  placeholder="(unchanged)"
                />
              </label>
            ))}
          </div>
        </div>

        <div style={{ gridColumn: "1 / -1" }}>
          <button className="btn" type="submit">
            Save settings
          </button>
        </div>
      </form>
    </PageSection>
  );
}
