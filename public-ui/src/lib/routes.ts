import type { CabinetSection } from "../types";

export function pathFromSection(section: CabinetSection) {
  return section === "dashboard" ? "/cabinet" : `/cabinet/${section}`;
}

export function sectionFromPath(pathname: string): CabinetSection {
  const clean = pathname.replace(/\/+$/, "");
  if (!clean || clean === "/cabinet") return "dashboard";
  if (!clean.startsWith("/cabinet/")) return "dashboard";
  const raw = clean.slice("/cabinet/".length);
  if (raw === "overview") return "dashboard";
  if (raw === "plans") return "subscription";
  if (raw === "account") return "referrals";
  if (raw === "dashboard" || raw === "subscription" || raw === "balance" || raw === "referrals" || raw === "giveaways" || raw === "help") {
    return raw;
  }
  return "dashboard";
}