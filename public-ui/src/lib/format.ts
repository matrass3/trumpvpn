export function fmtRub(value: number | null | undefined) {
  return `${Intl.NumberFormat("ru-RU").format(Number(value || 0))} RUB`;
}

export function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ru-RU");
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function getDaysLeft(value: string | null | undefined) {
  const end = parseDate(value);
  if (!end) return 0;
  const delta = end.getTime() - Date.now();
  if (delta <= 0) return 0;
  return Math.ceil(delta / 86400000);
}

export function sanitizeError(raw: string) {
  const text = String(raw || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!text) return "Request failed";
  if (/502|504|bad gateway|gateway timeout|gateway time-out/i.test(text)) {
    return "Service is temporarily unavailable. Try again in 20-30 seconds.";
  }
  return text.slice(0, 320);
}

export function planLabel(plan: { label: string; months: number; days: number }) {
  const label = String(plan.label || "").trim();
  if (label && !/(?:\u0420.|\u00D0.|\u00D1.){2,}/.test(label) && !label.includes("\uFFFD")) return label;
  const m = plan.months > 0 ? plan.months : Math.max(1, Math.round(plan.days / 30));
  if (m === 1) return "1 month";
  if (m === 3) return "3 months";
  if (m === 6) return "6 months";
  if (m === 12) return "1 year";
  return `${m} months`;
}

export function noticeTitleByKind(kind: "info" | "success" | "warn" | "error") {
  if (kind === "success") return "Success";
  if (kind === "warn") return "Warning";
  if (kind === "error") return "Error";
  return "Info";
}