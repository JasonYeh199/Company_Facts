import { ArrowRight, ChartNoAxesCombined, DatabaseZap, FileSearch } from "lucide-react";
import Link from "next/link";

import { SearchBox } from "@/components/search-box";
import { api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";

async function loadStatus(): Promise<SetupStatus | null> {
  try {
    return await api.setup();
  } catch {
    return null;
  }
}

export default async function Home() {
  const status = await loadStatus();
  const needsSetup = !status || status.supported_company_count === 0;
  return (
    <div className="home-page">
      <section className="hero">
        <div className="eyebrow"><span />SEC 原始申報 · 可驗證的投研數據</div>
        <h1>從一筆數字，<br />追到它的申報來源。</h1>
        <p className="hero-copy">
          搜尋美股公司，查看標準化三表、季度趨勢與修訂歷程。每個指標都保留 XBRL tag、accession 與 SEC filing 連結。
        </p>
        <SearchBox />
        <div className="hero-meta">
          <span><strong>{status?.supported_company_count.toLocaleString("zh-TW") ?? "—"}</strong> 家 US-GAAP 公司</span>
          <span><strong>15</strong> 項核心指標</span>
          <span><strong>100%</strong> SEC 可追溯</span>
        </div>
      </section>

      {needsSetup ? (
        <section className="setup-banner">
          <div>
            <span className="section-kicker">GET STARTED</span>
            <h2>{status ? "資料庫尚未匯入" : "API 尚未連線"}</h2>
            <p>
              {status
                ? "完成 SEC User-Agent 設定後，啟動首次全量同步。畫面會持續顯示下載與匯入進度。"
                : "請先啟動 FastAPI 與 PostgreSQL 服務，再回到資料同步頁確認環境。"}
            </p>
          </div>
          <Link href="/setup" className="button primary">檢查環境 <ArrowRight size={17} /></Link>
        </section>
      ) : null}

      <section className="feature-grid">
        <article>
          <span className="feature-icon"><ChartNoAxesCombined /></span>
          <span className="section-kicker">NORMALIZED</span>
          <h3>財報趨勢，不只是原始標籤</h3>
          <p>將公司歷年使用的不同 US-GAAP tags 對應至一致指標，提供年度、單季與 TTM 序列。</p>
        </article>
        <article>
          <span className="feature-icon"><FileSearch /></span>
          <span className="section-kicker">TRACEABLE</span>
          <h3>保留每次重述的脈絡</h3>
          <p>預設顯示最新修訂值，同時保留申報日、表單、原始值與所有歷次版本。</p>
        </article>
        <article>
          <span className="feature-icon"><DatabaseZap /></span>
          <span className="section-kicker">FIRST-PARTY</span>
          <h3>直接來自 SEC EDGAR</h3>
          <p>不混入第三方行情或估值推算，將資料品質與來源透明度放在第一位。</p>
        </article>
      </section>
    </div>
  );
}

