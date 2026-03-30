export const ROUTES = {
  login: "/login",
  overview: "/overview",
  users: "/users",
  servers: "/servers",
  configs: "/configs",
  subscriptions: "/subscriptions",
  payments: "/payments",
  promos: "/promos",
  giveaways: "/giveaways",
  audit: "/audit",
  settings: "/settings",
} as const;

export type RouteValue = (typeof ROUTES)[keyof typeof ROUTES];

export const ADMIN_NAV_ITEMS: Array<{ to: RouteValue; label: string }> = [
  { to: ROUTES.overview, label: "Overview" },
  { to: ROUTES.users, label: "Users" },
  { to: ROUTES.servers, label: "Servers" },
  { to: ROUTES.configs, label: "Configs" },
  { to: ROUTES.subscriptions, label: "Subscriptions" },
  { to: ROUTES.payments, label: "Payments" },
  { to: ROUTES.promos, label: "Promos" },
  { to: ROUTES.giveaways, label: "Giveaways" },
  { to: ROUTES.audit, label: "Audit" },
  { to: ROUTES.settings, label: "Settings" },
];
