import { useMemo } from "react";

export type BarChartPoint = {
  label: string;
  value: number;
};

type BarChartProps = {
  title: string;
  points: BarChartPoint[];
  color?: string;
  formatter?: (value: number) => string;
  emptyText?: string;
};

function formatDefault(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value)) : "-";
}

export function BarChart({
  title,
  points,
  color = "#4aa3ff",
  formatter = formatDefault,
  emptyText = "No samples",
}: BarChartProps) {
  const prepared = useMemo(() => {
    const clean = points
      .map((point) => ({ label: String(point.label || ""), value: Math.max(0, Number(point.value || 0)) }))
      .filter((point) => Number.isFinite(point.value));
    if (!clean.length) {
      return null;
    }

    const max = Math.max(1, ...clean.map((x) => x.value));
    const width = 980;
    const height = 240;
    const left = 24;
    const right = 18;
    const top = 20;
    const bottom = 34;
    const plotW = width - left - right;
    const plotH = height - top - bottom;
    const slot = plotW / clean.length;
    const barW = Math.max(6, slot * 0.66);

    const bars = clean.map((point, index) => {
      const h = (point.value / max) * plotH;
      const x = left + slot * index + (slot - barW) / 2;
      const y = top + plotH - h;
      return { ...point, x, y, w: barW, h };
    });

    const first = bars[0];
    const mid = bars[Math.floor((bars.length - 1) / 2)];
    const last = bars[bars.length - 1];

    return {
      width,
      height,
      left,
      top,
      plotW,
      plotH,
      max,
      bars,
      xLabels: [
        { text: first.label, x: first.x },
        { text: mid.label, x: mid.x + mid.w / 2 },
        { text: last.label, x: last.x + last.w },
      ],
      yLabels: [max, Math.round(max / 2), 0],
      total: clean.reduce((acc, item) => acc + item.value, 0),
    };
  }, [points]);

  return (
    <div className="chart-card">
      <div className="chart-card-head">
        <h4>{title}</h4>
        <span className="chart-value">{prepared ? formatter(prepared.total) : "-"}</span>
      </div>
      {!prepared ? (
        <div className="empty-banner">{emptyText}</div>
      ) : (
        <svg className="chart-svg" viewBox={`0 0 ${prepared.width} ${prepared.height}`} role="img" aria-label={title}>
          {[0, 0.5, 1].map((ratio) => {
            const y = prepared.top + prepared.plotH * ratio;
            return <line key={ratio} x1={prepared.left} y1={y} x2={prepared.left + prepared.plotW} y2={y} className="chart-grid-line" />;
          })}

          {prepared.bars.map((bar) => (
            <rect key={`${bar.label}-${bar.x}`} x={bar.x} y={bar.y} width={bar.w} height={bar.h} rx="5" fill={color} opacity="0.82" />
          ))}

          {prepared.yLabels.map((value, index) => {
            const y = prepared.top + (prepared.plotH * index) / Math.max(1, prepared.yLabels.length - 1);
            return (
              <text key={index} x="2" y={y + 4} className="chart-y-label">
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
