"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  CalendarDays,
  Database,
  RefreshCw,
} from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { formatValue, tickerOf, type Scale } from "@/lib/format";
import type { Company, MetricPoint, MetricSeries } from "@/lib/types";

import { FactsExplorer } from "./facts-explorer";
import { MetricChart } from "./metric-chart";
import { SourceDrawer } from "./source-drawer";
import { StatementTable } from "./statement-table";

const kpiCodes = ["revenue", "net_income", "eps_diluted", "free_cash_flow", "roe"];
const incomeCodes = ["revenue", "gross_profit", "operating_income", "net_income", "eps_basic", "eps_diluted"];
const balanceCodes = ["cash_and_equivalents", "current_assets", "total_assets", "current_liabilities", "total_liabilities", "total_equity", "total_debt"];
const cashFlowCodes = ["operating_cash_flow", "capital_expenditures", "free_cash_flow"];
const ratioCodes = ["revenue_yoy", "net_income_yoy", "eps_yoy", "gross_margin", "operating_margin", "net_margin", "fcf_margin", "current_ratio", "debt_to_equity", "roa", "roe"];

export function CompanyDashboard({
  company,
  initial,
}: {
  company: Company;
  initial: MetricSeries;
}) {
  const [data, setData] = useState(initial);
  const [frequency, setFrequency] = useState("annual");
  const [scale, setScale] = useState<Scale>("million");
  const [selectedMetric, setSelectedMetric] = useState("revenue");
  const [selectedPoint, setSelectedPoint] = useState<MetricPoint | null>(null);
  const [view, setView] = useState<"analysis" | "facts">("analysis");
  const [loading, setLoading] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");

  const changeFrequency = async (next: string) => {
    if (next === frequency) return;
    setFrequency(next);
    setLoading(true);
    try {
      setData(await api.metrics(company.cik, next));
    } finally {
      setLoading(false);
    }
  };

  const availableChartMetrics = useMemo(
    () => Object.entries(data.metrics).filter(([, points]) => points.length > 1),
    [data],
  );
  const chartCode = data.metrics[selectedMetric]?.length ? selectedMetric : availableChartMetrics[0]?.[0];
  const chartPoints = chartCode ? data.metrics[chartCode] : [];
  const chartDefinition = chartPoints[0];

  const refresh = async () => {
    try {
      await api.createSync("company", company.cik);
      setSyncMessage("已加入同步佇列");
    } catch (error) {
      setSyncMessage(error instanceof Error ? error.message : "無法建立同步工作");
    }
  };

  return (
    <div className="company-page">
      <section className="company-hero">
        <div className="company-identity">
          <div className="company-monogram">{tickerOf(company).slice(0, 2)}</div>
          <div>
            <div className="company-tags">
              <span>{company.tickers.map((item) => item.ticker).join(" / ")}</span>
              <span>{company.tickers[0]?.exchange}</span>
              <span className="verified"><BadgeCheck size={14} />US-GAAP</span>
            </div>
            <h1>{company.name}</h1>
            <p>CIK {company.cik} · SIC {company.sic ?? "—"} · Fiscal year end {company.fiscal_year_end ?? "—"}</p>
          </div>
        </div>
        <div className="company-actions">
          <button className="button secondary" onClick={refresh}><RefreshCw size={16} />更新此公司</button>
          {syncMessage ? <small>{syncMessage}</small> : null}
        </div>
      </section>

      <div className="subnav">
        <div className="view-tabs">
          <button className={view === "analysis" ? "active" : ""} onClick={() => setView("analysis")}>財務分析</button>
          <button className={view === "facts" ? "active" : ""} onClick={() => setView("facts")}>Raw Facts</button>
        </div>
        <div className="freshness"><Database size={14} />更新於 {company.last_synced_at?.slice(0, 10) ?? "尚未同步"}</div>
      </div>

      {view === "facts" ? <FactsExplorer cik={company.cik} /> : (
        <>
          <div className="toolbar panel">
            <div className="segmented" aria-label="資料頻率">
              {[["annual", "年度"], ["quarterly", "季度"], ["ttm", "TTM"]].map(([value, label]) => (
                <button key={value} className={frequency === value ? "active" : ""} onClick={() => changeFrequency(value)}>{label}</button>
              ))}
            </div>
            <label className="scale-select">顯示單位
              <select value={scale} onChange={(event) => setScale(event.target.value as Scale)}>
                <option value="raw">原值</option><option value="thousand">千</option><option value="million">百萬</option><option value="billion">十億</option>
              </select>
            </label>
          </div>
          {loading ? <div className="loading-row">載入 {frequency} 資料…</div> : null}

          <section className="kpi-grid">
            {kpiCodes.map((code) => {
              const points = data.metrics[code] ?? [];
              const latest = points.at(-1);
              const previous = points.at(-2);
              const change = latest && previous && Number(previous.value) !== 0
                ? (Number(latest.value) - Number(previous.value)) / Math.abs(Number(previous.value)) * 100
                : null;
              return (
                <article className="kpi-card" key={code}>
                  <div><span>{latest?.name_zh ?? code}</span><small>{latest?.name_en ?? "Unavailable"}</small></div>
                  <strong>{latest ? formatValue(latest.value, latest.unit, scale) : "—"}</strong>
                  <footer>
                    <span>{latest?.period_end ?? "未申報"}</span>
                    {change !== null ? (
                      <span className={change >= 0 ? "positive" : "negative"}>
                        {change >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{Math.abs(change).toFixed(1)}%
                      </span>
                    ) : <span>—</span>}
                  </footer>
                </article>
              );
            })}
          </section>

          {chartDefinition ? (
            <section className="panel chart-panel">
              <div className="panel-title">
                <div><span className="section-kicker">TREND</span><h2>{chartDefinition.name_zh}趨勢</h2></div>
                <select value={chartCode} onChange={(event) => setSelectedMetric(event.target.value)} aria-label="圖表指標">
                  {availableChartMetrics.map(([code, points]) => <option key={code} value={code}>{points[0].name_zh} · {points[0].name_en}</option>)}
                </select>
              </div>
              <MetricChart points={chartPoints} scale={scale} />
              <div className="chart-foot"><CalendarDays size={14} />實際 period end；公司財務年度可能不等同曆年</div>
            </section>
          ) : null}

          <StatementTable title="損益表 · Income Statement" codes={incomeCodes} metrics={data.metrics} scale={scale} onPoint={setSelectedPoint} />
          <StatementTable title="資產負債表 · Balance Sheet" codes={balanceCodes} metrics={data.metrics} scale={scale} onPoint={setSelectedPoint} />
          <StatementTable title="現金流量表 · Cash Flow" codes={cashFlowCodes} metrics={data.metrics} scale={scale} onPoint={setSelectedPoint} />
          <StatementTable title="衍生分析 · Ratios" codes={ratioCodes} metrics={data.metrics} scale={scale} onPoint={setSelectedPoint} />
        </>
      )}
      <SourceDrawer cik={company.cik} point={selectedPoint} scale={scale} onClose={() => setSelectedPoint(null)} />
    </div>
  );
}

