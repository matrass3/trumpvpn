declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string;
        ready?: () => void;
        expand?: () => void;
        openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
        openTelegramLink?: (url: string) => void;
        colorScheme?: "light" | "dark";
        MainButton?: {
          isVisible?: boolean;
          setText?: (text: string) => void;
          show?: () => void;
          hide?: () => void;
          enable?: () => void;
          disable?: () => void;
          onClick?: (cb: () => void) => void;
          offClick?: (cb: () => void) => void;
        };
        BackButton?: {
          isVisible?: boolean;
          show?: () => void;
          hide?: () => void;
          onClick?: (cb: () => void) => void;
          offClick?: (cb: () => void) => void;
        };
        HapticFeedback?: {
          impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
          notificationOccurred?: (kind: "error" | "success" | "warning") => void;
          selectionChanged?: () => void;
        };
      };
    };
  }
}

export function triggerImpact(style: "light" | "medium" | "heavy" = "light") {
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred?.(style);
}

export function triggerNotify(kind: "error" | "success" | "warning") {
  window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred?.(kind);
}

function extractRawQueryParam(name: string): string {
  const query = window.location.search.startsWith("?") ? window.location.search.slice(1) : "";
  if (!query) return "";
  const parts = query.split("&");
  for (const item of parts) {
    if (!item) continue;
    const eqPos = item.indexOf("=");
    const key = eqPos >= 0 ? item.slice(0, eqPos) : item;
    if (key === name) return eqPos >= 0 ? item.slice(eqPos + 1) : "";
  }
  return "";
}

export function getTelegramMiniAppInitData() {
  const direct = String(window.Telegram?.WebApp?.initData || "").trim();
  if (direct) return direct;
  const raw = extractRawQueryParam("tgWebAppData") || extractRawQueryParam("initData");
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export function ensureTelegramWebAppSdk() {
  const onReady = () => {
    window.Telegram?.WebApp?.ready?.();
    window.Telegram?.WebApp?.expand?.();
  };
  onReady();
  if (window.Telegram?.WebApp) return;
  const exists = document.querySelector('script[data-telegram-webapp="1"]');
  if (exists) return;
  const script = document.createElement("script");
  script.src = "https://telegram.org/js/telegram-web-app.js";
  script.async = true;
  script.setAttribute("data-telegram-webapp", "1");
  script.onload = onReady;
  document.head.appendChild(script);
}
