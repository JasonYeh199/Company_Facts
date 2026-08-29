"use client";

import { ArrowUpRight, LoaderCircle, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { tickerOf } from "@/lib/format";
import type { Company } from "@/lib/types";

export function SearchBox({ compact = false }: { compact?: boolean }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Company[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    if (query.trim().length < 1) return;
    const currentId = ++requestId.current;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const companies = await api.search(query.trim());
        if (currentId === requestId.current) setResults(companies);
      } catch (reason) {
        if (currentId === requestId.current) {
          setError(reason instanceof Error ? reason.message : "搜尋服務暫時無法使用");
        }
      } finally {
        if (currentId === requestId.current) setLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  return (
    <div className={`search-shell ${compact ? "search-compact" : ""}`}>
      <Search aria-hidden size={compact ? 18 : 21} />
      <input
        aria-label="搜尋公司"
        value={query}
        onChange={(event) => {
          const value = event.target.value;
          setQuery(value);
          if (!value.trim()) {
            setResults([]);
            setError("");
          }
        }}
        placeholder="輸入 Ticker、公司名稱或 CIK，例如 AAPL"
        autoComplete="off"
      />
      {loading && <LoaderCircle className="spin" aria-label="搜尋中" size={19} />}
      {query && !loading && (
        <div className="search-results" role="listbox">
          {error ? <p className="search-message error-text">{error}</p> : null}
          {!error && results.length === 0 ? (
            <p className="search-message">沒有符合的公司</p>
          ) : null}
          {results.map((company) => (
            <Link
              href={`/company/${company.cik}`}
              key={company.cik}
              className="search-result"
              onClick={() => setQuery("")}
            >
              <span className="ticker-tile">{tickerOf(company).slice(0, 5)}</span>
              <span className="result-copy">
                <strong>{company.name}</strong>
                <small>{company.tickers.map((item) => `${item.ticker} · ${item.exchange}`).join(" / ")}</small>
              </span>
              <span className={`status-pill ${company.supported ? "supported" : "unsupported"}`}>
                {company.supported ? "US-GAAP" : "未支援"}
              </span>
              <ArrowUpRight size={16} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
