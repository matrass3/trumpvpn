import { FormEvent, useState } from "react";
import { loginByCredentials } from "../api/sessionApi";

type UseLoginFormOptions = {
  onSuccess: () => void;
};

export function useLoginForm({ onSuccess }: UseLoginFormOptions) {
  const [adminId, setAdminId] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      await loginByCredentials(adminId.trim(), password);
      onSuccess();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unable to sign in";
      setError(message);
    } finally {
      setPending(false);
    }
  }

  return {
    adminId,
    password,
    pending,
    error,
    setAdminId,
    setPassword,
    onSubmit,
  };
}
