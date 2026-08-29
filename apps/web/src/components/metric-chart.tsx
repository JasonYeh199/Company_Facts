"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatValue, type Scale, unitLabel } from "@/lib/format";
import type { MetricPoint } from "@/lib/types";

export function MetricChart({ points, scale }: { points: MetricPoint[]; scale: Scale }) {
  const data = useMemo(
    () =>
      points.map((point) => ({
        period: point.period_end,
        value: Number(point.value),
        unit: point.unit,
      })),
    [points],
  );
  const unit = points.at(-1)?.unit ?? "USD";
  return (
    <div className="chart-wrap" aria-label="指標趨勢圖">
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={data} margin={{ top: 12, right: 10, left: 6, bottom: 0 }}>
          <defs>
            <linearGradient id="metricFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#0f8b8d" stopOpacity={0.28} />
              <stop offset="95%" stopColor="#0f8b8d" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#e4e9e7" vertical={false} strokeDasharray="4 4" />
          <XAxis dataKey="period" tickLine={false} axisLine={false} tick={{ fill: "#6f7a77", fontSize: 12 }} />
          <YAxis
            width={72}
            tickLine={false}
            axisLine={false}
            tick={{ fill: "#6f7a77", fontSize: 12 }}
            tickFormatter={(value) => formatValue(String(value), unit, scale)}
          />
          <Tooltip
            formatter={(value) => [formatValue(String(value), unit, scale), unitLabel(unit, scale)]}
            contentStyle={{ borderRadius: 12, border: "1px solid #dce3e0", boxShadow: "0 14px 32px rgba(14, 35, 34, .1)" }}
          />
          <Area type="monotone" dataKey="value" stroke="#0f8b8d" strokeWidth={2.5} fill="url(#metricFill)" activeDot={{ r: 5 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

