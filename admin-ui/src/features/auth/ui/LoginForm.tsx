import { useNavigate } from "react-router-dom";
import { ROUTES } from "../../../shared/config/routes";
import { useLoginForm } from "../model/useLoginForm";

export function LoginForm() {
  const navigate = useNavigate();
  const { adminId, password, pending, error, setAdminId, setPassword, onSubmit } = useLoginForm({
    onSuccess: () => navigate(ROUTES.overview, { replace: true }),
  });

  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <label className="field">
        <span>Admin Telegram ID</span>
        <input
          className="control-input"
          value={adminId}
          onChange={(event) => setAdminId(event.target.value)}
          autoComplete="username"
          required
        />
      </label>
      <label className="field">
        <span>Password</span>
        <input
          className="control-input"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <button className="btn auth-submit" type="submit" disabled={pending}>
        {pending ? "Signing in..." : "Enter Console"}
      </button>
      {error ? <div className="error-banner">{error}</div> : null}
    </form>
  );
}
