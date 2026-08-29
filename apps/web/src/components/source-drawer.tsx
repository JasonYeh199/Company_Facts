"use client";

import { ExternalLink, GitCommitHorizontal, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatValue, type Scale } from "@/lib/format";
import type { MetricPoint } from "@/lib/types";

export function SourceDrawer({
  cik,
  point,
  scale,
  onClose,
}: {
  cik: string;
  point: MetricPoint | null;
  scale: Scale;
  onClose: () => void;
}) {
  const [revisions, setRevisions] = useState<MetricPoint[]>([]);

  useEffect(() => {
    if (!point) return;
    let alive = true;
    api
      .revisions(cik, point.metric, point.frequency, point.period_end)
      .then((items) => alive && setRevisions(items))
      .catch(() => alive && setRevisions([point]));
    return () => {
      alive = false;
    };
  }, [cik, point]);

  if (!point) return null;
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="source-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`${point.name_zh} 資料來源`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="section-kicker">DATA LINEAGE</span>
            <h2>{point.name_zh}</h2>
            <p>{point.name_en} · {point.period_end}</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="關閉"><X /></button>
        </header>
        <section className="source-value">
          <small>目前顯示值</small>
          <strong>{formatValue(point.value, point.unit, scale)}</strong>
          <span>{point.unit} · {point.is_derived ? "衍生計算" : "原始申報"}</span>
        </section>
        <section>
          <div className="drawer-section-title">
            <GitCommitHorizontal size={17} />
            <h3>修訂歷程</h3>
            <span>{point.revision_count} 個版本</span>
          </div>
          <div className="revision-list">
            {(revisions.length ? revisions : [point]).map((revision, index) => (
              <article key={`${revision.source.accession}-${index}`}>
                <div className="revision-head">
                  <strong>{formatValue(revision.value, revision.unit, scale)}</strong>
                  {index === 0 ? <span className="status-pill supported">目前版本</span> : null}
                </div>
                <dl>
                  <div><dt>申報日</dt><dd>{revision.source.filed ?? "—"}</dd></div>
                  <div><dt>表單</dt><dd>{revision.source.form ?? "衍生"}</dd></div>
                  <div><dt>Accession</dt><dd>{revision.source.accession ?? "—"}</dd></div>
                  <div><dt>品質</dt><dd>{revision.quality}</dd></div>
                </dl>
                {revision.source.url ? (
                  <a href={revision.source.url} target="_blank" rel="noreferrer">
                    在 SEC 查看原始申報 <ExternalLink size={14} />
                  </a>
                ) : null}
                {revision.source.lineage.length ? (
                  <details>
                    <summary>查看 {revision.source.lineage.length} 筆來源 fact</summary>
                    <pre>{JSON.stringify(revision.source.lineage, null, 2)}</pre>
                  </details>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
