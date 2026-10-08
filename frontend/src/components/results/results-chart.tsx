"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ResultColumn } from "@/lib/api/types";
import { MAX_BARS, key, type ChartSpec } from "@/lib/chart";
import { formatNumber } from "@/lib/format";

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];

const tooltipStyle = {
  backgroundColor: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: "0.5rem",
  color: "var(--popover-foreground)",
  fontSize: 12,
};

function compact(value: unknown): string {
  if (typeof value !== "number") return String(value);
  return Math.abs(value) >= 10_000
    ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)
    : formatNumber(value);
}

export function ResultsChart({ spec, columns }: { spec: ChartSpec; columns: ResultColumn[] }) {
  const xKey = key(columns, spec.x);
  const series = spec.ys.map((y, i) => ({
    dataKey: key(columns, y),
    name: columns[y]?.name ?? `column ${y + 1}`,
    color: COLORS[i % COLORS.length],
  }));
  const xName = columns[spec.x]?.name ?? "";
  const title =
    spec.kind === "line"
      ? `${series.map((s) => s.name).join(", ")} over ${xName}`
      : `${series.map((s) => s.name).join(", ")} by ${xName}`;

  return (
    <figure className="grid grid-cols-1 gap-2">
      <figcaption className="text-sm text-muted-foreground">
        {title}
        {spec.kind === "bar" && spec.points.length === MAX_BARS ? ` (first ${MAX_BARS})` : ""}
      </figcaption>
      <div className="h-72 w-full sm:h-80" role="img" aria-label={`Chart: ${title}`}>
        <ResponsiveContainer width="100%" height="100%">
          {spec.kind === "line" ? (
            <LineChart data={spec.points} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" minTickGap={24} />
              <YAxis tickFormatter={compact} tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" width={56} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => compact(v)} />
              {series.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} /> : null}
              {series.map((s) => (
                <Line
                  key={s.dataKey}
                  type="monotone"
                  dataKey={s.dataKey}
                  name={s.name}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={spec.points.length <= 40}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart
              data={spec.points}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" tickFormatter={compact} tick={{ fontSize: 12 }} stroke="var(--muted-foreground)" />
              <YAxis
                type="category"
                dataKey={xKey}
                width={120}
                tick={{ fontSize: 12 }}
                stroke="var(--muted-foreground)"
                tickFormatter={(v: unknown) => {
                  const text = String(v);
                  return text.length > 18 ? `${text.slice(0, 17)}…` : text;
                }}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => compact(v)} cursor={{ fill: "var(--muted)" }} />
              {series.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} /> : null}
              {series.map((s) => (
                <Bar
                  key={s.dataKey}
                  dataKey={s.dataKey}
                  name={s.name}
                  fill={s.color}
                  radius={[0, 4, 4, 0]}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
