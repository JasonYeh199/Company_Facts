import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Company } from "@/lib/types";

import { PriceAnalysis } from "./price-analysis";

const lockedCompany: Company = {
  cik: "0000320193",
  name: "Apple Inc.",
  supported: true,
  accounting_standard: "us-gaap",
  tickers: [{ ticker: "AAPL", exchange: "Nasdaq", is_active: true }],
  price_coverage: {
    ticker: "AAPL",
    status: "locked",
    start_date: null,
    end_date: null,
    last_synced_at: null,
    reason: "Tiingo 授權限定內部／本機環境使用",
  },
};

describe("PriceAnalysis", () => {
  it("does not expose Tiingo data in a public snapshot", () => {
    render(<PriceAnalysis company={lockedCompany} />);
    expect(screen.getByRole("heading", { name: "股價分析限定內部環境" })).toBeInTheDocument();
    expect(screen.getByText("Tiingo 授權限定內部／本機環境使用")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /前往資料同步/ })).toHaveAttribute("href", "/setup");
  });
});
