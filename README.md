# Fundamental Lens

以 SEC EDGAR Company Facts 為唯一財報來源的美股 Fundamental Database v1。系統保存完整標準 XBRL facts，並將公司歷年使用的不同 tags 正規化為一致指標，提供繁中個股研究、來源追溯、修訂歷程與五家公司比較。

## 功能

- 目前掛牌公司 ticker／名稱／CIK 搜尋；基金排除，IFRS 公司顯示未支援。
- 15 項核心指標：Revenue、Gross Profit、Operating Income、Net Income、Basic/Diluted EPS、Cash、Current/Total Assets、Current/Total Liabilities、Equity、Debt、OCF、CapEx。
- Annual、discrete quarter、TTM、Q4 推導，以及 FCF、YoY、margins、current ratio、debt-to-equity、ROA、ROE。
- 最新修訂值、歷次 accession、原始 XBRL tag、lineage 與 SEC filing 連結。
- Raw Facts Explorer、最多五家公司比較、Top 100／全市場／單一公司同步狀態。

## 快速啟動

需求：Docker Desktop、至少 60 GiB 可用空間，以及可接收聯絡的 email。

```powershell
Copy-Item .env.example .env
```

編輯 `.env`，將 `SEC_USER_AGENT` 改成真實的產品名稱與聯絡信箱，例如：

```dotenv
SEC_USER_AGENT=Acme Fundamental Research data-team@acme.com
```

啟動所有服務：

```powershell
docker compose up --build
```

若預設連接埠已被其他服務使用，可在 `.env` 調整 `POSTGRES_PORT`、`API_PORT`、
`WEB_PORT`，並同步更新 `NEXT_PUBLIC_API_BASE_URL` 與 `API_CORS_ORIGINS`。

開啟：

- Web：http://localhost:3000
- OpenAPI：http://localhost:8000/docs
- Health：http://localhost:8000/health

第一次進入「資料同步」頁，確認 User-Agent 與磁碟檢查通過後，建議先啟動「市值前 100」匯入。名單採 [CompaniesMarketCap 美國公司排名](https://companiesmarketcap.com/usa/largest-companies-in-the-usa-by-market-cap/?page=1) 的 2026-08-29 快照，再套用目前掛牌、非基金及具 `us-gaap` Company Facts 的條件，因此實際支援公司數可能略少於 100；需要時仍可切換全市場同步。

官方 archives 目前約 2.8 GiB 壓縮後、23 GiB 解壓後；系統直接從 ZIP 串流讀取，不會先展開全部 JSON，且 Top 100 與全市場模式會重用相同下載檔。完成第一次 bootstrap 後，worker 每日美東 04:00 檢查 ETag／Last-Modified，並沿用最近一次完成的同步範圍。

## Vercel 前端部署

Vercel 專案的 Root Directory 設為 `apps/web`。前端可獨立部署，但完整查詢仍需要可公開連線的 FastAPI；請在 Vercel 同時設定：

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://your-api.example.com/api/v1
API_INTERNAL_BASE_URL=https://your-api.example.com/api/v1
```

若未設定，公開版會顯示 API 未連線狀態。PostgreSQL、SEC bulk worker、ZIP 持久化 volume 與每日同步仍應部署在支援長時間背景工作的主機，不放入 Vercel Functions。

## 本機開發

後端：

```powershell
cd apps/api
uv sync --extra dev
uv run company-facts init-db
uv run uvicorn company_facts.main:app --reload
```

單一公司同步可先驗證資料流程，不需下載 bulk archives：

```powershell
uv run company-facts sync --kind company --cik 320193
```

前端：

```powershell
pnpm install
pnpm dev
```

從正在執行的 OpenAPI schema 重新產生 TypeScript 型別：

```powershell
pnpm generate:api
```

## 資料流程

1. `company_tickers_exchange.json` 建立目前掛牌證券主檔，並以 mutual-fund 清單排除基金。
2. `companyfacts.zip` 只處理掛牌 CIK；必須存在 `us-gaap` namespace 才匯入完整標準 facts。
3. PostgreSQL 使用 temporary staging table 與 `COPY` 批次寫入，`facts` 依 company hash 分成 16 partitions。
4. Versioned mapping registry 產生 canonical values；同優先序的衝突值標為 `ambiguous`，不進入預設圖表。
5. 最新畫面值依 filed date 與 accession 選擇，舊版本與 lineage 永久保留。
6. Submissions 資料補齊 SIC、fiscal year end、ticker、exchange 與 filing metadata。

下載使用 `.partial` 檔與原子 rename；成功來源的 ETag、Last-Modified 與時間保存在 data volume 的 `source_manifest.json`。中斷後再次同步會續傳，未變更的 archives 不重複下載。

## API

主要介面位於 `/api/v1`：

- `GET /companies/search?q=`
- `GET /companies/{cik}`
- `GET /companies/{cik}/metrics`
- `GET /companies/{cik}/statements/{statement}`
- `GET /companies/{cik}/facts`
- `GET /companies/{cik}/metrics/{metric}/revisions`
- `GET /compare?cik=...`
- `GET|POST /sync-runs`

所有財務值以 decimal string 回傳，日期為 ISO 8601。缺值為 unavailable／空陣列，絕不當作零。不同貨幣不換匯、不跨幣別合計。

## 測試

```powershell
cd apps/api
uv run ruff check src tests alembic
uv run pytest

cd ../..
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
pnpm --filter web test:e2e
```

後端 fixtures 包含一般公司、金融業缺項與 IFRS unsupported 情境；整合測試覆蓋重複匯入、canonical rebuild、來源 contract 與公司比較限制。

## 邊界與資料品質

- 首版只正規化 Company Facts 已提供的 standard/entity-wide `us-gaap` facts，不解析公司 custom extensions。
- 金融業仍在 universe 中，但 Gross Profit、Current Assets 等不適用欄位會顯示 unavailable。
- CapEx 正規化為正數支出，`FCF = OCF - CapEx`；EPS 不計算 TTM。
- 不包含市場行情、估值、外匯換算、歷史下市 universe、AI 問答、帳號或正式 SaaS 營運設施。
- 資料僅供研究，不構成投資建議。自動化存取需遵循 [SEC Fair Access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。
