"use client";

import { ExternalLink, Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { FactsPage } from "@/lib/types";

export function FactsExplorer({ cik }: { cik: string }) {
  const [concept, setConcept] = useState("");
  const [form, setForm] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<FactsPage | null>(null);
  const [loading, setLoading] = useState(true);

  const load = (nextOffset = offset) => {
    setLoading(true);
    api
      .facts(cik, { concept, form, offset: nextOffset, limit: 50 })
      .then(setData)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let alive = true;
    api
      .facts(cik, { offset: 0, limit: 50 })
      .then((result) => alive && setData(result))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [cik]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setOffset(0);
    load(0);
  };

  return (
    <section className="panel facts-panel">
      <div className="panel-title">
        <div><span className="section-kicker">RAW FACTS</span><h2>原始 XBRL Facts</h2></div>
        <span>{data?.total.toLocaleString("zh-TW") ?? "—"} 筆</span>
      </div>
      <form className="fact-filters" onSubmit={submit}>
        <label><Search size={16} /><input value={concept} onChange={(e) => setConcept(e.target.value)} placeholder="Concept 名稱" /></label>
        <select value={form} onChange={(event) => setForm(event.target.value)} aria-label="申報表單">
          <option value="">全部表單</option><option>10-K</option><option>10-Q</option><option>10-K/A</option><option>10-Q/A</option>
        </select>
        <button className="button secondary" type="submit">套用篩選</button>
      </form>
      {loading ? <div className="loading-row">載入 facts…</div> : (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Concept</th><th>期間</th><th>數值</th><th>單位</th><th>Form</th><th>Filed</th><th>來源</th></tr></thead>
            <tbody>
              {data?.items.map((fact) => (
                <tr key={fact.id}>
                  <th><strong>{fact.concept}</strong><small>{fact.taxonomy}</small></th>
                  <td>{fact.period_start ? `${fact.period_start} → ` : ""}{fact.period_end}</td>
                  <td className="mono">{fact.value}</td><td>{fact.unit}</td><td>{fact.form}</td><td>{fact.filed}</td>
                  <td><a className="external-icon" href={fact.source_url} target="_blank" rel="noreferrer" aria-label="SEC filing"><ExternalLink size={15} /></a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pagination">
        <button disabled={offset === 0} onClick={() => { const next = Math.max(0, offset - 50); setOffset(next); load(next); }}>上一頁</button>
        <span>{offset + 1}–{Math.min(offset + 50, data?.total ?? 0)}</span>
        <button disabled={!data || offset + 50 >= data.total} onClick={() => { const next = offset + 50; setOffset(next); load(next); }}>下一頁</button>
      </div>
    </section>
  );
}
