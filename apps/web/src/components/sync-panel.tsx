"use client";

import {
  AlertTriangle,
  CheckCircle2,
  DatabaseZap,
  HardDrive,
  LineChart,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { SetupStatus, SyncRun } from "@/lib/types";

function statusName(status: string) {
  return (
    {
      pending: "等待中",
      running: "執行中",
      completed: "已完成",
      completed_with_errors: "部分完成",
      failed: "失敗",
      unsupported: "供應商不支援",
      cancelled: "已取消",
    }[status] ?? status
  );
}

function runName(run: SyncRun) {
  if (run.kind === "bulk") return "全市場基本面";
  if (run.kind === "top100") return "市值前 100 基本面";
  if (run.kind === "prices") return "Top 100 Tiingo EOD";
  if (run.kind === "price_company") return `股價 CIK ${run.cik}`;
  return `基本面 CIK ${run.cik}`;
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
        setMessage("無法連線至 API。請確認 FastAPI 與 PostgreSQL 已啟動。");
      }
    };
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const startSync = async (kind: "bulk" | "top100" | "prices") => {
    setMessage("正在建立同步工作…");
    try {
      await api.createSync(kind);
      setRuns(await api.syncRuns());
      setMessage(
        kind === "prices"
          ? "Tiingo 工作已排入佇列；Starter 方案同步 100 檔約需 2–3 小時。"
          : "SEC 工作已排入佇列，可留在此頁查看進度。",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "無法建立同步工作");
    }
  };

  if (!status) {
    return (
      <div className="empty-page">
        <AlertTriangle />
        <h1>API 尚未連線</h1>
        <p>請確認 FastAPI 與 PostgreSQL 已啟動。</p>
      </div>
    );
  }

  const readOnlySnapshot = status.data_dir.startsWith("vercel://");
  const privateSnapshot = status.data_dir === "vercel://private-snapshot";
  const active = runs.some((run) => ["pending", "running"].includes(run.status));
  return (
    <div className="setup-page">
      <header className="page-intro">
        <span className="section-kicker">DATA OPERATIONS</span>
        <h1>資料設定與同步</h1>
        <p>管理 SEC Company Facts 與內部限定的 Tiingo Daily EOD 股價資料。</p>
      </header>

      <section className="readiness-grid price-readiness-grid">
        <article className={status.sec_configured ? "ready" : "warning"}>
          {status.sec_configured ? <CheckCircle2 /> : <AlertTriangle />}
          <div>
            <small>{readOnlySnapshot ? "DEPLOYMENT MODE" : "SEC USER-AGENT"}</small>
            <strong>{readOnlySnapshot ? "唯讀 Snapshot" : status.sec_configured ? "已設定" : "尚未設定"}</strong>
            <span>{readOnlySnapshot ? "公開站不執行同步" : "SEC EDGAR 存取識別"}</span>
          </div>
        </article>
        <article className={readOnlySnapshot || status.tiingo_configured ? "ready" : "warning"}>
          {readOnlySnapshot || status.tiingo_configured ? <CheckCircle2 /> : <AlertTriangle />}
          <div>
            <small>TIINGO TOKEN</small>
            <strong>{privateSnapshot ? "私人快照" : readOnlySnapshot ? "內部限定" : status.tiingo_configured ? "已設定" : "尚未設定"}</strong>
            <span>{privateSnapshot ? `${status.price_company_count} 家已有價格` : readOnlySnapshot ? "不輸出價格資料" : `${status.price_company_count} 家已有價格`}</span>
          </div>
        </article>
        <article className={status.free_gib >= status.disk_requirement_gib ? "ready" : "warning"}>
          <HardDrive />
          <div>
            <small>儲存空間</small>
            <strong>{readOnlySnapshot ? "靜態資料" : `${status.free_gib} GiB`}</strong>
            <span>{readOnlySnapshot ? "Vercel read-only" : `建議至少 ${status.disk_requirement_gib} GiB`}</span>
          </div>
        </article>
        <article className="ready">
          <DatabaseZap />
          <div>
            <small>公司覆蓋</small>
            <strong>{status.supported_company_count.toLocaleString("zh-TW")} 家</strong>
            <span>最新價格 {status.latest_price_date ?? "尚未匯入"}</span>
          </div>
        </article>
      </section>

      <section className="panel bootstrap-panel">
        <div>
          <span className="section-kicker">FUNDAMENTALS</span>
          <h2>SEC Company Facts</h2>
          <p>更新市值前 100 家或完整 US-GAAP 公司資料。</p>
        </div>
        {!readOnlySnapshot ? (
          <div className="sync-actions">
            <button className="button primary" disabled={!status.sec_configured || status.free_gib < 60 || active} onClick={() => startSync("top100")}>
              <RefreshCw size={17} />同步前 100
            </button>
            <button className="button secondary" disabled={!status.sec_configured || status.free_gib < 60 || active} onClick={() => startSync("bulk")}>
              <DatabaseZap size={17} />完整同步
            </button>
          </div>
        ) : null}
      </section>

      <section className="panel bootstrap-panel price-bootstrap-panel">
        <div>
          <span className="section-kicker">DAILY EOD · INTERNAL USE</span>
          <h2>Tiingo 股價資料</h2>
          <p>首次抓取最近十年；日常增量同步並重算技術指標、風險與 Top 100 排名。</p>
        </div>
        {!readOnlySnapshot ? (
          <button className="button primary" disabled={!status.tiingo_configured || active} onClick={() => startSync("prices")}>
            <LineChart size={17} />同步股價
          </button>
        ) : (
          <span className="status-pill unsupported">{privateSnapshot ? "請由本機更新私人快照" : "公開站不提供 Tiingo 資料"}</span>
        )}
      </section>

      {message ? <p className="operation-message">{message}</p> : null}
      <section className="panel runs-panel">
        <div className="panel-title"><h2>同步歷程</h2><span>每 5 秒更新</span></div>
        {runs.length === 0 ? <p className="muted">尚未建立同步工作。</p> : runs.map((run) => {
          const progress = run.progress_total
            ? Math.min(100, (run.progress_current / run.progress_total) * 100)
            : 0;
          const success = ["completed", "completed_with_errors"].includes(run.status);
          const failedItems = run.price_items?.filter((item) => ["failed", "unsupported"].includes(item.status)) ?? [];
          return (
            <article className="run-row" key={run.id}>
              <span className={`run-state ${run.status}`}>
                {run.status === "running" ? <LoaderCircle className="spin" /> : success ? <CheckCircle2 /> : <DatabaseZap />}
              </span>
              <div className="run-copy">
                <div><strong>{runName(run)}</strong><span>{statusName(run.status)}</span></div>
                <p>{run.error ?? run.message ?? "—"}</p>
                <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
                {failedItems.length ? <details className="sync-item-errors"><summary>{failedItems.length} 檔 ticker 需要處理</summary>{failedItems.map((item) => <div key={item.ticker}><b>{item.ticker}</b><span>{statusName(item.status)} · {item.error ?? "未知錯誤"}</span></div>)}</details> : null}
              </div>
              <time>{run.created_at.slice(0, 16).replace("T", " ")}</time>
            </article>
          );
        })}
      </section>
    </div>
  );
}
