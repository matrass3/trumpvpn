import { ApiError, isUnauthorizedError } from "./httpClient";

export type AdminActionResult = {
  ok: boolean;
  message: string;
  error: string;
  finalUrl: string;
};

function parseActionResultUrl(rawUrl: string): AdminActionResult {
  const url = new URL(rawUrl, window.location.origin);
  const message = String(url.searchParams.get("msg") || "").trim();
  const error = String(url.searchParams.get("error") || "").trim();
  return {
    ok: !error,
    message,
    error,
    finalUrl: url.toString(),
  };
}

function toFormEncoded(body: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(body)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof value === "boolean") {
      params.set(key, value ? "1" : "0");
      continue;
    }
    params.set(key, String(value));
  }
  return params.toString();
}

export async function submitAdminAction(
  actionPath: string,
  body: Record<string, string | number | boolean | null | undefined> = {},
): Promise<AdminActionResult> {
  const response = await fetch(actionPath, {
    method: "POST",
    credentials: "include",
    redirect: "follow",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: toFormEncoded(body),
  });

  if (response.status === 401 || response.url.includes("/admin/login")) {
    throw new ApiError("UNAUTHORIZED", 401);
  }

  if (!response.ok) {
    throw new ApiError(`HTTP ${response.status}`, response.status);
  }

  return parseActionResultUrl(response.url);
}

export async function submitAdminActionSafely(
  actionPath: string,
  body: Record<string, string | number | boolean | null | undefined> = {},
): Promise<AdminActionResult> {
  try {
    return await submitAdminAction(actionPath, body);
  } catch (error) {
    if (isUnauthorizedError(error)) {
      window.location.assign("/login");
      return {
        ok: false,
        message: "",
        error: "UNAUTHORIZED",
        finalUrl: window.location.href,
      };
    }
    const message = error instanceof Error ? error.message : "Unknown action error";
    return {
      ok: false,
      message: "",
      error: message,
      finalUrl: window.location.href,
    };
  }
}
