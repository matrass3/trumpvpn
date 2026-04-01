import { Navigate, createBrowserRouter } from "react-router-dom";
import { App } from "../App";
import { AdminShell } from "../layout/AdminShell";
import { ROUTES } from "../../shared/config/routes";
import { LoginPage } from "../../pages/login";
import { OverviewPage } from "../../pages/overview";
import { ServersPage } from "../../pages/servers";
import { UsersPage } from "../../pages/users";
import { ConfigsPage } from "../../pages/configs";
import { SubscriptionsPage } from "../../pages/subscriptions";
import { PaymentsPage } from "../../pages/payments";
import { PromosPage } from "../../pages/promos";
import { GiveawaysPage } from "../../pages/giveaways";
import { AuditPage } from "../../pages/audit";
import { SettingsPage } from "../../pages/settings";
import { ServerDetailPage } from "../../pages/server-detail";
import { UserDevicesPage } from "../../pages/user-devices";

const isLocalDevHost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
const routerBase = isLocalDevHost && window.location.port === "5173" ? "/" : "/admin";

export const appRouter = createBrowserRouter(
  [
    {
      path: "/",
      element: <App />,
      children: [
        { path: ROUTES.login, element: <LoginPage /> },
        {
          element: <AdminShell />,
          children: [
            { index: true, element: <Navigate to={ROUTES.overview} replace /> },
            { path: ROUTES.overview.slice(1), element: <OverviewPage /> },
            { path: ROUTES.servers.slice(1), element: <ServersPage /> },
            { path: "servers/:serverId", element: <ServerDetailPage /> },
            { path: ROUTES.users.slice(1), element: <UsersPage /> },
            { path: "users/:telegramId/devices", element: <UserDevicesPage /> },
            { path: ROUTES.configs.slice(1), element: <ConfigsPage /> },
            { path: ROUTES.subscriptions.slice(1), element: <SubscriptionsPage /> },
            { path: ROUTES.payments.slice(1), element: <PaymentsPage /> },
            { path: ROUTES.promos.slice(1), element: <PromosPage /> },
            { path: ROUTES.giveaways.slice(1), element: <GiveawaysPage /> },
            { path: ROUTES.audit.slice(1), element: <AuditPage /> },
            { path: ROUTES.settings.slice(1), element: <SettingsPage /> },
            { path: "*", element: <Navigate to={ROUTES.overview} replace /> },
          ],
        },
        { path: "*", element: <Navigate to={ROUTES.login} replace /> },
      ],
    },
  ],
  { basename: routerBase },
);
