type Summary = {
  total_users: number;
  active_subscriptions: number;
  total_servers?: number;
  enabled_servers?: number;
  total_configs?: number;
  active_configs?: number;
  paid_invoices: number;
  revenue_rub: number;
  live_users_now?: number;
  connected_now?: number;
};

type OverviewKpiGridProps = {
  summary: Summary | null;
};

function formatInt(value: number | undefined): string {
  if (value === undefined || value === null) {
    return "-";
  }
  return Intl.NumberFormat("ru-RU").format(value);
}

function formatRub(value: number | undefined): string {
  if (value === undefined || value === null) {
    return "-";
  }
  return `${Intl.NumberFormat("ru-RU").format(value)} RUB`;
}

export function OverviewKpiGrid({ summary }: OverviewKpiGridProps) {
  const totalUsers = summary?.total_users ?? 0;
  const activeSubs = summary?.active_subscriptions ?? 0;
  const subRate = totalUsers > 0 ? Math.round((activeSubs / totalUsers) * 100) : 0;

  const metrics = [
    {
      title: "Total Users",
      value: formatInt(summary?.total_users),
      note: `Subscribed: ${subRate}%`,
      tone: "primary",
    },
    {
      title: "Active Subscriptions",
      value: formatInt(summary?.active_subscriptions),
      note: "Current billing cycle",
      tone: "success",
    },
    {
      title: "Active Configs",
      value: formatInt(summary?.active_configs),
      note: `Total configs: ${formatInt(summary?.total_configs)}`,
      tone: "primary",
    },
    {
      title: "Servers",
      value: `${formatInt(summary?.enabled_servers)} / ${formatInt(summary?.total_servers)}`,
      note: "Enabled / Total",
      tone: "warning",
    },
    {
      title: "Paid Invoices",
      value: formatInt(summary?.paid_invoices),
      note: "Confirmed payments",
      tone: "warning",
    },
    {
      title: "Revenue",
      value: formatRub(summary?.revenue_rub),
      note: "Gross revenue",
      tone: "warning",
    },
    {
      title: "Live Users Now",
      value: formatInt(summary?.live_users_now),
      note: "Realtime estimate",
      tone: "success",
    },
    {
      title: "Connections",
      value: formatInt(summary?.connected_now),
      note: "Established now",
      tone: "primary",
    },
  ] as const;

  return (
    <div className="metric-grid">
      {metrics.map((metric) => (
        <article className="metric-card" key={metric.title}>
          <div className="metric-head">
            <span className={`metric-tone ${metric.tone}`} />
            <h3>{metric.title}</h3>
          </div>
          <div className="metric-value">{metric.value}</div>
          <div className="metric-note">{metric.note}</div>
        </article>
      ))}
    </div>
  );
}
