"use client";

import { History } from "lucide-react";

import { formatValue, type Scale } from "@/lib/format";
import type { MetricPoint } from "@/lib/types";

export function StatementTable({
  title,
  codes,
  metrics,
  scale,
  onPoint,
}: {
  title: string;
  codes: string[];
  metrics: Record<string, MetricPoint[]>;
  scale: Scale;
  onPoint: (point: MetricPoint) => void;
}) {
  const periods = Array.from(
    new Set(codes.flatMap((code) => (metrics[code] ?? []).map((point) => point.period_end))),
  )
    .sort()
    .slice(-6);
  const rows = codes
    .map((code) => ({ code, points: metrics[code] ?? [] }))
    .filter((row) => row.points.length > 0);
  if (!rows.length) return null;
  return (
    <section className="panel statement-panel">
      <div className="panel-title"><h2>{title}</h2><span>點擊數值查看來源</span></div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>指標</th>{periods.map((period) => <th key={period}>{period}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(({ code, points }) => {
              const definition = points[0];
              return (
                <tr key={code}>
                  <th><strong>{definition.name_zh}</strong><small>{definition.name_en}</small></th>
                  {periods.map((period) => {
                    const point = points.find((item) => item.period_end === period);
                    return (
                      <td key={period}>
                        {point ? (
                          <button className="value-button" onClick={() => onPoint(point)}>
                            {formatValue(point.value, point.unit, scale)}
                            {point.revision_count > 1 ? <History size={12} /> : null}
                            {point.is_derived ? <sup>D</sup> : null}
                          </button>
                        ) : "—"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

