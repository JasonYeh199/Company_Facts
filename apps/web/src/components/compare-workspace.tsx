"use client";

import { GitCompareArrows, Plus, Search, X } from "lucide-react";
import { FormEvent, useState } from "react";

import { api } from "@/lib/api";
import { formatValue, tickerOf } from "@/lib/format";
import type { Company, CompareData } from "@/lib/types";

const metricOptions = [
  ["revenue", "營收"],
  ["net_income", "淨利"],
  ["eps_diluted", "稀釋 EPS"],
  ["free_cash_flow", "自由現金流"],
  ["revenue_yoy", "營收年增率"],
  ["operating_margin", "營業利益率"],
  ["roe", "ROE"],
  ["debt_to_equity", "負債權益比"],
];

export function CompareWorkspace() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Company[]>([]);
  const [selected, setSelected] = useState<Company[]>([]);
  const [frequency, setFrequency] = useState("annual");
  const [metrics, setMetrics] = useState(["revenue", "net_income", "eps_diluted", "free_cash_flow", "roe"]);
  const [data, setData] = useState<CompareData | null>(null);
  const [message, setMessage] = useState("");

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setResults(await api.search(query.trim()));
  };
  const add = (company: Company) => {
    if (selected.some((item) => item.cik === company.cik)) return;
    if (selected.length >= 5) return setMessage("最多比較五家公司");
    if (!company.supported) return setMessage("此公司不是首版支援的 US-GAAP universe");
    setSelected([...selected, company]);
    setResults([]);
    setQuery("");
    setMessage("");
  };
  const compare = async () => {
    if (selected.length < 2) return setMessage("請至少選擇兩家公司");
    setMessage("載入比較資料…");
    try {
      setData(await api.compare(selected.map((item) => item.cik), frequency, metrics));
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "比較資料載入失敗");
    }
  };

  return (
    <div className="compare-page">
      <header className="page-intro">
        <span className="section-kicker">COMPANY COMPARISON</span>
        <h1>把公司的基本面，放在同一張桌上。</h1>
        <p>最多比較五家公司。數值依各公司 fiscal period 呈現，不會假裝財務年度完全相同。</p>
      </header>
      <section className="panel compare-builder">
        <div className="selected-companies">
          {selected.map((company) => (
            <span key={company.cik}><b>{tickerOf(company)}</b>{company.name}<button onClick={() => setSelected(selected.filter((item) => item.cik !== company.cik))} aria-label={`移除 ${company.name}`}><X size={13} /></button></span>
          ))}
          {selected.length < 5 ? <span className="slot"><Plus size={15} />加入公司</span> : null}
        </div>
        <form className="compare-search" onSubmit={search}>
          <Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋 ticker 或公司名稱" /><button className="button secondary">搜尋</button>
        </form>
        {results.length ? (
          <div className="compare-results">
            {results.map((company) => <button key={company.cik} onClick={() => add(company)}><b>{tickerOf(company)}</b><span>{company.name}</span><small>{company.supported ? "US-GAAP" : "未支援"}</small></button>)}
          </div>
        ) : null}
        <div className="compare-options">
          <div className="segmented">
            {[["annual", "年度"], ["quarterly", "季度"], ["ttm", "TTM"]].map(([value, label]) => <button key={value} className={frequency === value ? "active" : ""} onClick={() => setFrequency(value)}>{label}</button>)}
          </div>
          <div className="metric-chips">
            {metricOptions.map(([code, label]) => <button key={code} className={metrics.includes(code) ? "active" : ""} onClick={() => setMetrics(metrics.includes(code) ? metrics.filter((item) => item !== code) : [...metrics, code])}>{label}</button>)}
          </div>
          <button className="button primary" onClick={compare}><GitCompareArrows size={16} />開始比較</button>
        </div>
        {message ? <p className="form-message">{message}</p> : null}
      </section>

      {data ? (
        <section className="panel compare-table">
          <div className="panel-title"><h2>最新一期比較</h2><span>各欄顯示實際 period end</span></div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>公司</th>{metrics.map((code) => <th key={code}>{metricOptions.find(([item]) => item === code)?.[1] ?? code}</th>)}</tr></thead>
              <tbody>
                {data.companies.map((company) => (
                  <tr key={company.cik}>
                    <th><strong>{tickerOf(company)}</strong><small>{company.name}</small></th>
                    {metrics.map((code) => {
                      const point = data.series[company.cik]?.[code]?.at(-1);
                      return <td key={code}>{point ? <><strong>{formatValue(point.value, point.unit, "million")}</strong><small>{point.period_end}</small></> : "—"}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

