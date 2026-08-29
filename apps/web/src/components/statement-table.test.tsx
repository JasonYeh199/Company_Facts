import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MetricPoint } from "@/lib/types";

import { StatementTable } from "./statement-table";

const point: MetricPoint = {
  metric: "revenue",
  name_en: "Revenue",
  name_zh: "營收",
  statement: "income",
  frequency: "annual",
  period_start: "2024-01-01",
  period_end: "2024-12-31",
  fiscal_year: 2024,
  fiscal_period: "FY",
  value: "1000000000",
  unit: "USD",
  is_derived: false,
  quality: "reported",
  revision_count: 2,
  source: {
    accession: "0000000001-25-000001",
    form: "10-K",
    filed: "2025-02-01",
    url: "https://www.sec.gov/example",
    lineage: [],
  },
};

describe("StatementTable", () => {
  it("shows available values and opens lineage from the value button", () => {
    const onPoint = vi.fn();
    render(
      <StatementTable
        title="損益表"
        codes={["revenue", "gross_profit"]}
        metrics={{ revenue: [point] }}
        scale="million"
        onPoint={onPoint}
      />,
    );
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.queryByText("gross_profit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /1,000/ }));
    expect(onPoint).toHaveBeenCalledWith(point);
  });
});

