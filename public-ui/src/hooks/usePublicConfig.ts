import { useEffect, useState } from "react";
import type { PublicConfig } from "../types";

export function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig>({
    bot_url: "https://t.me/trumpvlessbot",
    brand: "TrumpVPN",
    bot_username: "trumpvlessbot",
    support_url: "https://t.me/trumpvpnhelp",
  });

  useEffect(() => {
    void fetch("/api/public/config")
      .then(async (res) => (res.ok ? ((await res.json()) as Partial<PublicConfig>) : null))
      .then((payload) => {
        if (!payload) return;
        setConfig((prev) => ({
          bot_url: String(payload.bot_url || prev.bot_url),
          brand: String(payload.brand || prev.brand),
          bot_username: String(payload.bot_username || prev.bot_username || "trumpvlessbot"),
          support_url: String(payload.support_url || prev.support_url || "https://t.me/trumpvpnhelp"),
        }));
      })
      .catch(() => undefined);
  }, []);

  return config;
}