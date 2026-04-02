import { sanitizeError } from "./format";

export async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(sanitizeError((await response.text()).trim() || `HTTP ${response.status}`));
  }
  return (await response.json()) as T;
}

export function trackEvent(event: string, meta: Record<string, unknown> = {}) {
  void fetch("/api/public/analytics/event", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ event, meta }),
  }).catch(() => undefined);
}