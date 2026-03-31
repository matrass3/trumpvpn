import { useMemo } from "react";

export type LineChartPoint = {
  label: string;
  value: number;
};

type LineChartProps = {
  title: string;
  points: LineChartPoint[];
  color?: string;
  formatter?: (value: number) => string;
  emptyText?: string;
};

function chartSlug(input: string): string {
  const value = String(input || "line-chart").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return value || "line-chart";
}

function formatDefault(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) >= 100) {
    return String(Math.round(value));
  }
  if (Math.abs(value) >= 10) {
    return value.toFixed(1);
  }
  return value.toFixed(2);
}

export function LineChart({
  title,
  points,
  color = "#3ed3a4",
  formatter = formatDefault,
  emptyText = "No samples",
}: LineChartProps) {
  const slug = useMemo(() => chartSlug(title), [title]);

  const prepared = useMemo(() => {
    const clean = points
      .map((point) => ({ label: String(point.label || ""), value: Number(point.value || 0) }))
      .filter((point) => Number.isFinite(point.value));

    if (!clean.length) {
      return null;
    }

    const min = Math.min(...clean.map((x) => x.value));
    const max = Math.max(...clean.map((x) => x.value));
    const range = max - min || 1;
    const width = 980;
    const height = 240;
    const left = 38;
    const right = 18;
    const top = 20;
    const bottom = 34;
    const plotW = width - left - right;
    const plotH = height - top - bottom;

    const dot = (index: number, value: number) => {
      const x = left + (plotW * index) / Math.max(1, clean.length - 1);
      const y = top + ((max - value) / range) * plotH;
      return { x, y };
    };

    const line = clean
      .map((point, index) => {
        const { x, y } = dot(index, point.value);
        return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");

    const area = `${line} L${(left + plotW).toFixed(2)} ${(top + plotH).toFixed(2)} L${left.toFixed(2)} ${(top + plotH).toFixed(2)} Z`;

    const first = clean[0];
    const mid = clean[Math.floor((clean.length - 1) / 2)];
    const last = clean[clean.length - 1];

    return {
      width,
      height,
      left,
      top,
      plotW,
      plotH,
      min,
      max,
      lastValue: last.value,
      line,
      area,
      xLabels: [
        { text: first.label, x: left },
        { text: mid.label, x: left + plotW / 2 },
        { text: last.label, x: left + plotW },
      ],
      yLabels: [max, min + range / 2, min],
    };
  }, [points]);

  return (
    <div className="chart-card">
      <div className="chart-card-head">
        <h4>{title}</h4>
        <span className="chart-value">{prepared ? formatter(prepared.lastValue) : "-"}</span>
      </div>
      {!prepared ? (
        <div className="empty-banner">{emptyText}</div>
      ) : (
        <svg className="chart-svg" viewBox={`0 0 ${prepared.width} ${prepared.height}`} role="img" aria-label={title}>
          <defs>
            <linearGradient id={`grad-${slug}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0.03" />
            </linearGradient>
          </defs>

          {[0, 0.5, 1].map((ratio) => {
            const y = prepared.top + prepared.plotH * ratio;
            return <line key={ratio} x1={prepared.left} y1={y} x2={prepared.left + prepared.plotW} y2={y} className="chart-grid-line" />;
          })}

          <path d={prepared.area} fill={`url(#grad-${slug})`} />
          <path d={prepared.line} stroke={color} strokeWidth="3" fill="none" strokeLinecap="round" />

          {prepared.yLabels.map((value, index) => {
            const y = prepared.top + (prepared.plotH * index) / Math.max(1, prepared.yLabels.length - 1);
            return (
              <text key={index} x="4" y={y + 4} className="chart-y-label">
                {formatter(value)}
              </text>
            );
          })}

          {prepared.xLabels.map((label, index) => (
            <text key={index} x={label.x} y={prepared.top + prepared.plotH + 22} textAnchor={index === 0 ? "start" : index === 2 ? "end" : "middle"} className="chart-x-label">
              {label.text}
            </text>
          ))}
        </svg>
      )}
    </div>
  );
}
