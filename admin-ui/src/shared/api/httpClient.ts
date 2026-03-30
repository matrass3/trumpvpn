const devLocalBase = `${window.location.protocol}//${window.location.hostname}:8001/admin/api`;
const defaultApiBase = window.location.port === "5173" ? devLocalBase : "/admin/api";
export const API_BASE = import.meta.env.VITE_ADMIN_API_BASE ?? defaultApiBase;

function isLoginRedirect(response: Response): boolean {
  return response.redirected && response.url.includes("/admin/login");
}

function buildHeaders(initHeaders?: HeadersInit): HeadersInit {
  return {
    Accept: "application/json",
    ...(initHeaders ?? {}),
  };
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export async function apiGetJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: buildHeaders(init.headers),
  });

  if (response.status === 401 || isLoginRedirect(response)) {
    throw new ApiError("UNAUTHORIZED", 401);
  }

  if (!response.ok) {
    const text = (await response.text()).trim();
    throw new ApiError(text || `HTTP ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}
