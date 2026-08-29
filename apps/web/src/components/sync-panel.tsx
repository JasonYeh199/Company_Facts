"use client";

import { AlertTriangle, CheckCircle2, DatabaseZap, HardDrive, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { SetupStatus, SyncRun } from "@/lib/types";

function statusName(status: string) {
  return { pending: "等待中", running: "執行中", completed: "完成", failed: "失敗", cancelled: "已取消" }[status] ?? status;
}

export function SyncPanel({ initial }: { initial: SetupStatus | null }) {
  const [status, setStatus] = useState(initial);
  const [runs, setRuns] = useState<SyncRun[]>(initial?.latest_sync ? [initial.latest_sync] : []);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const refresh = async () => {
      try {
        const [next, nextRuns] = await Promise.all([api.setup(), api.syncRuns()]);
        setStatus(next);
        setRuns(nextRuns);
      } catch {
        setMessage("API 暫時無法連線");
      }
    };
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const bootstrap = async (kind: "bulk" | "top100") => {
    setMessage(kind === "top100" ? "建立市值前 100 同步工作…" : "建立全量同步工作…");
    try {
      await api.createSync(kind);
      setRuns(await api.syncRuns());
      setMessage("已加入佇列；可離開此頁，worker 會繼續處理。首次匯入可能需要較長時間。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "無法建立同步工作");
    }
  };

  if (!status) {
    return <div className="empty-page"><AlertTriangle /><h1>API 尚未連線</h1><p>請確認 FastAPI 與 PostgreSQL 已啟動。</p></div>;
  }
  return (
    <div className="setup-page">
      <header className="page-intro"><span className="section-kicker">DATA OPERATIONS</span><h1>資料環境與同步</h1><p>第一次匯入會下載 SEC bulk archives，並逐家公司建立 raw facts 與 canonical metrics。</p></header>
      <section className="readiness-grid">
        <article className={status.sec_configured ? "ready" : "warning"}>
          {status.sec_configured ? <CheckCircle2 /> : <AlertTriangle />}<div><small>SEC USER-AGENT</small><strong>{status.sec_configured ? "已設定" : "需要設定"}</strong><span>{status.sec_configured ? "符合自動化存取要求" : "請編輯根目錄 .env"}</span></div>
        </article>
        <article className={status.free_gib >= status.disk_requirement_gib ? "ready" : "warning"}>
          <HardDrive /><div><small>可用磁碟</small><strong>{status.free_gib} GiB</strong><span>最低需求 {status.disk_requirement_gib} GiB</span></div>
        </article>
        <article className="ready">
          <DatabaseZap /><div><small>資料庫</small><strong>{status.supported_company_count.toLocaleString("zh-TW")} 家</strong><span>{status.company_count.toLocaleString("zh-TW")} 家證券主檔</span></div>
        </article>
      </section>
      <section className="panel bootstrap-panel">
        <div><span className="section-kicker">FOCUSED BOOTSTRAP</span><h2>SEC Bulk Bootstrap</h2><p>建議先同步市值前 100；系統會重用 SEC ZIP，成功後每日美東 04:00 自動檢查更新。</p></div>
        <div className="sync-actions">
          <button className="button primary" disabled={!status.sec_configured || status.free_gib < 60 || runs.some((run) => ["pending", "running"].includes(run.status))} onClick={() => bootstrap("top100")}><RefreshCw size={17} />同步市值前 100</button>
          <button className="button secondary" disabled={!status.sec_configured || status.free_gib < 60 || runs.some((run) => ["pending", "running"].includes(run.status))} onClick={() => bootstrap("bulk")}><DatabaseZap size={17} />同步全市場</button>
        </div>
      </section>
      {message ? <p className="operation-message">{message}</p> : null}
      <section className="panel runs-panel">
        <div className="panel-title"><h2>同步紀錄</h2><span>每 5 秒更新</span></div>
        {runs.length === 0 ? <p className="muted">尚未建立同步工作。</p> : runs.map((run) => {
          const progress = run.progress_total ? Math.min(100, run.progress_current / run.progress_total * 100) : 0;
          return (
            <article className="run-row" key={run.id}>
              <span className={`run-state ${run.status}`}>{run.status === "running" ? <LoaderCircle className="spin" /> : run.status === "completed" ? <CheckCircle2 /> : <DatabaseZap />}</span>
              <div className="run-copy"><div><strong>{run.kind === "bulk" ? "全量資料庫" : run.kind === "top100" ? "市值前 100" : `CIK ${run.cik}`}</strong><span>{statusName(run.status)}</span></div><p>{run.error ?? run.message ?? "—"}</p><div className="progress-track"><span style={{ width: `${progress}%` }} /></div></div>
              <time>{run.created_at.slice(0, 16).replace("T", " ")}</time>
            </article>
          );
        })}
      </section>
    </div>
  );
}
