"use client";

import {
  AlertTriangle,
  CalendarDays,
  CandlestickChart,
  Database,
  LockKeyhole,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import type { Company, PriceAnalysis as Analysis, PricePoint, PriceSeries } from "@/lib/types";

type RangeKey = "1m" | "3m" | "6m" | "ytd" | "1y" | "3y" | "5y" | "10y" | "custom";
type PriceMode = "adjusted" | "raw";
type ChartMode = "trend" | "candlestick";
type LayerOptions = { volume: boolean; sma: boolean; bollinger: boolean };

const ranges: [RangeKey, string][] = [
  ["1m", "1M"], ["3m", "3M"], ["6m", "6M"], ["ytd", "YTD"],
  ["1y", "1Y"], ["3y", "3Y"], ["5y", "5Y"], ["10y", "10Y"], ["custom", "自訂"],
];

const returnLabels: Record<string, string> = {
  return_1d: "1 日", return_1w: "1 週", return_1m: "1 個月", return_3m: "3 個月",
  return_6m: "6 個月", return_ytd: "今年至今", return_1y: "1 年",
  return_3y_annualized: "3 年年化", return_5y_annualized: "5 年年化",
  return_10y_annualized: "10 年年化",
};

const riskLabels: Record<string, string> = {
  volatility_20d: "20 日波動", volatility_60d: "60 日波動", volatility_252d: "252 日波動",
  downside_deviation_252d: "下行波動", current_drawdown: "目前回撤",
  max_drawdown_1y: "1 年最大回撤", max_drawdown_3y: "3 年最大回撤",
  max_drawdown_10y: "10 年最大回撤", var_95_1d: "95% VaR",
  cvar_95_1d: "95% CVaR", high_52w: "52 週高點", low_52w: "52 週低點",
  distance_from_52w_high: "距 52 週高點", distance_from_52w_low: "距 52 週低點",
  worst_day_1y: "一年最差單日",
};

const rankLabels: Record<string, string> = {
  return_1m: "1M 報酬", return_3m: "3M 報酬", return_6m: "6M 報酬",
  return_1y: "12M 報酬", volatility_252d: "低波動", max_drawdown_1y: "低回撤",
};

function percent(value: string | null | undefined, digits = 1) {
  if (value == null) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function price(value: string | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value));
}

function compact(value: string | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("zh-TW", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}

function rangeStart(range: RangeKey, end: string) {
  const value = new Date(`${end}T00:00:00Z`);
  if (range === "ytd") return `${value.getUTCFullYear()}-01-01`;
  const months: Partial<Record<RangeKey, number>> = { "1m": 1, "3m": 3, "6m": 6, "1y": 12, "3y": 36, "5y": 60, "10y": 120 };
  value.setUTCMonth(value.getUTCMonth() - (months[range] ?? 12));
  return value.toISOString().slice(0, 10);
}

function CandlestickView({ points, mode, layers }: { points: PricePoint[]; mode: PriceMode; layers: LayerOptions }) {
  const sampled = useMemo(() => {
    const step = Math.max(1, Math.ceil(points.length / 180));
    return points.filter((_, index) => index % step === 0 || index === points.length - 1);
  }, [points]);
  if (!sampled.length) return null;
  const highKey = mode === "adjusted" ? "adj_high" : "high";
  const lowKey = mode === "adjusted" ? "adj_low" : "low";
  const openKey = mode === "adjusted" ? "adj_open" : "open";
  const closeKey = mode === "adjusted" ? "adj_close" : "close";
  const highs = sampled.map((item) => Number(item[highKey]));
  const lows = sampled.map((item) => Number(item[lowKey]));
  const ceiling = Math.max(...highs);
  const floor = Math.min(...lows);
  const spread = Math.max(ceiling - floor, 0.01);
  const x = (index: number) => 36 + (index / Math.max(1, sampled.length - 1)) * 928;
  const y = (value: number) => 16 + ((ceiling - value) / spread) * 268;
  const candleWidth = Math.max(1.5, Math.min(6, 860 / sampled.length));
  const maxVolume = Math.max(...sampled.map((item) => Number(mode === "adjusted" ? item.adj_volume : item.volume)), 1);
  const overlayPoints = (key: "sma_20" | "sma_50" | "sma_200" | "bollinger_upper" | "bollinger_lower") =>
    sampled
      .map((item, index) => item.indicators[key] == null ? null : `${x(index)},${y(Number(item.indicators[key]))}`)
      .filter(Boolean)
      .join(" ");
  return (
    <div className="candlestick-wrap" aria-label="日 K 線與成交量">
      <svg viewBox="0 0 1000 360" role="img">
        {[0, 1, 2, 3, 4].map((line) => <line key={line} x1="36" x2="964" y1={16 + line * 67} y2={16 + line * 67} className="candle-grid" />)}
        {mode === "adjusted" && layers.sma ? <>
          <polyline className="candle-sma20" points={overlayPoints("sma_20")} />
          <polyline className="candle-sma50" points={overlayPoints("sma_50")} />
          <polyline className="candle-sma200" points={overlayPoints("sma_200")} />
        </> : null}
        {mode === "adjusted" && layers.bollinger ? <>
          <polyline className="candle-bollinger" points={overlayPoints("bollinger_upper")} />
          <polyline className="candle-bollinger" points={overlayPoints("bollinger_lower")} />
        </> : null}
        {sampled.map((item, index) => {
          const open = Number(item[openKey]);
          const close = Number(item[closeKey]);
          const rising = close >= open;
          const volume = Number(mode === "adjusted" ? item.adj_volume : item.volume);
          const center = x(index);
          return (
            <g key={item.date} className={rising ? "candle-up" : "candle-down"}>
              <title>{`${item.date} O ${price(String(open))} H ${price(item[highKey])} L ${price(item[lowKey])} C ${price(String(close))}`}</title>
              <line x1={center} x2={center} y1={y(Number(item[highKey]))} y2={y(Number(item[lowKey]))} />
              <rect x={center - candleWidth / 2} y={Math.min(y(open), y(close))} width={candleWidth} height={Math.max(1, Math.abs(y(open) - y(close)))} />
              {layers.volume ? <rect className="candle-volume" x={center - candleWidth / 2} y={350 - (volume / maxVolume) * 48} width={candleWidth} height={(volume / maxVolume) * 48} /> : null}
            </g>
          );
        })}
        <text x="4" y="20">{price(String(ceiling))}</text>
        <text x="4" y="284">{price(String(floor))}</text>
        <text x="36" y="359">{sampled[0].date}</text>
        <text x="964" y="359" textAnchor="end">{sampled.at(-1)?.date}</text>
      </svg>
    </div>
  );
}

function PriceEventTimeline({ series }: { series: PriceSeries }) {
  if (!series.events.length) return null;
  const first = Date.parse(`${series.start_date}T00:00:00Z`);
  const last = Date.parse(`${series.end_date}T00:00:00Z`);
  const span = Math.max(1, last - first);
  return (
    <div className="price-event-timeline" aria-label="股利、拆股與 SEC 申報事件時間軸">
      <div className="event-track">
        {series.events.map((event, index) => {
          const position = Math.max(0, Math.min(100, ((Date.parse(`${event.date}T00:00:00Z`) - first) / span) * 100));
          const collision = series.events.slice(0, index).filter((item) => item.date === event.date).length;
          const detail = `${event.date} · ${event.label}${event.value ? ` · ${event.value}` : ""}`;
          const markerProps = {
            className: `price-event-marker ${event.type}`,
            style: { left: `${position}%`, top: `${8 + collision * 13}px` },
            "data-tooltip": detail,
            "aria-label": detail,
          };
          return event.url
            ? <a key={`${event.date}-${event.type}-${index}`} {...markerProps} href={event.url} target="_blank" rel="noreferrer" />
            : <span key={`${event.date}-${event.type}-${index}`} {...markerProps} tabIndex={0} />;
        })}
      </div>
      <div className="event-legend"><span className="dividend">股利</span><span className="split">拆併股</span><span className="filing">SEC 申報</span><small>聚焦或停留標記查看事件</small></div>
    </div>
  );
}

function PriceCharts({ series, mode, chartMode, layers }: { series: PriceSeries; mode: PriceMode; chartMode: ChartMode; layers: LayerOptions }) {
  const data = useMemo(() => series.points.map((item) => ({
    ...item,
    plotted: Number(mode === "adjusted" ? item.adj_close : item.close),
    volumePlotted: Number(mode === "adjusted" ? item.adj_volume : item.volume),
    sma20: item.indicators.sma_20 == null ? null : Number(item.indicators.sma_20),
    sma50: item.indicators.sma_50 == null ? null : Number(item.indicators.sma_50),
    sma200: item.indicators.sma_200 == null ? null : Number(item.indicators.sma_200),
    upper: item.indicators.bollinger_upper == null ? null : Number(item.indicators.bollinger_upper),
    lower: item.indicators.bollinger_lower == null ? null : Number(item.indicators.bollinger_lower),
    rsi: item.indicators.rsi_14 == null ? null : Number(item.indicators.rsi_14),
    macd: item.indicators.macd == null ? null : Number(item.indicators.macd),
    signal: item.indicators.macd_signal == null ? null : Number(item.indicators.macd_signal),
    histogram: item.indicators.macd_histogram == null ? null : Number(item.indicators.macd_histogram),
    drawdown: item.indicators.drawdown == null ? null : Number(item.indicators.drawdown) * 100,
  })), [series, mode]);

  return (
    <>
      <section className="panel price-chart-panel">
        {chartMode === "candlestick" ? <CandlestickView points={series.points} mode={mode} layers={layers} /> : (
          <div className="price-chart-wrap">
            <ResponsiveContainer width="100%" height={410}>
              <ComposedChart data={data} margin={{ top: 20, right: 18, left: 10, bottom: 8 }}>
                <CartesianGrid stroke="#e4e9e7" vertical={false} strokeDasharray="4 4" />
                <XAxis dataKey="date" minTickGap={50} tick={{ fontSize: 10 }} />
                <YAxis yAxisId="price" domain={["auto", "auto"]} width={68} tickFormatter={(value) => price(String(value))} tick={{ fontSize: 10 }} />
                <YAxis yAxisId="volume" orientation="right" width={54} tickFormatter={(value) => compact(String(value))} tick={{ fontSize: 9 }} />
                <Tooltip labelFormatter={(label) => String(label)} formatter={(value, name) => [name === "volumePlotted" ? compact(String(value)) : price(String(value)), String(name)]} />
                {layers.volume ? <Bar yAxisId="volume" dataKey="volumePlotted" fill="#d8e4e0" opacity={0.65} /> : null}
                <Area yAxisId="price" type="monotone" dataKey="plotted" stroke="#0f7779" fill="#d9efeb" strokeWidth={2.2} dot={false} name={mode === "adjusted" ? "Adjusted close" : "Raw close"} />
                {mode === "adjusted" && layers.sma ? <>
                  <Line yAxisId="price" dataKey="sma20" stroke="#e0a12f" dot={false} strokeWidth={1.2} name="SMA 20" />
                  <Line yAxisId="price" dataKey="sma50" stroke="#6a7dd8" dot={false} strokeWidth={1.2} name="SMA 50" />
                  <Line yAxisId="price" dataKey="sma200" stroke="#8f5baa" dot={false} strokeWidth={1.2} name="SMA 200" />
                </> : null}
                {mode === "adjusted" && layers.bollinger ? <>
                  <Line yAxisId="price" dataKey="upper" stroke="#9ba8a4" strokeDasharray="3 3" dot={false} name="Bollinger upper" />
                  <Line yAxisId="price" dataKey="lower" stroke="#9ba8a4" strokeDasharray="3 3" dot={false} name="Bollinger lower" />
                </> : null}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
        <PriceEventTimeline series={series} />
      </section>

      <section className="price-subcharts">
        <article className="panel">
          <div className="mini-chart-title"><strong>RSI 14</strong><span>Wilder · 70 / 30</span></div>
          <ResponsiveContainer width="100%" height={170}>
            <AreaChart data={data}><XAxis dataKey="date" hide /><YAxis domain={[0, 100]} width={32} tick={{ fontSize: 9 }} />
              <ReferenceLine y={70} stroke="#bc625c" strokeDasharray="3 3" /><ReferenceLine y={30} stroke="#0f7779" strokeDasharray="3 3" />
              <Area type="monotone" dataKey="rsi" stroke="#0f7779" fill="#d9efeb" dot={false} /></AreaChart>
          </ResponsiveContainer>
        </article>
        <article className="panel">
          <div className="mini-chart-title"><strong>MACD 12 / 26 / 9</strong><span>Adjusted close</span></div>
          <ResponsiveContainer width="100%" height={170}>
            <ComposedChart data={data}><XAxis dataKey="date" hide /><YAxis width={42} tick={{ fontSize: 9 }} />
              <ReferenceLine y={0} stroke="#aeb9b5" /><Bar dataKey="histogram" fill="#b9d7d2" />
              <Line dataKey="macd" stroke="#0f7779" dot={false} /><Line dataKey="signal" stroke="#d18d2d" dot={false} /></ComposedChart>
          </ResponsiveContainer>
        </article>
        <article className="panel">
          <div className="mini-chart-title"><strong>Drawdown</strong><span>Adjusted close</span></div>
          <ResponsiveContainer width="100%" height={170}>
            <AreaChart data={data}><XAxis dataKey="date" hide /><YAxis width={42} unit="%" tick={{ fontSize: 9 }} />
              <Area type="monotone" dataKey="drawdown" stroke="#b6524e" fill="#f4ddda" dot={false} /></AreaChart>
          </ResponsiveContainer>
        </article>
      </section>
    </>
  );
}

function LockedPriceState({ company }: { company: Company }) {
  const coverage = company.price_coverage;
  const locked = coverage?.status === "locked";
  return (
    <section className="panel price-lock-panel">
      <div className="price-lock-icon">{locked ? <LockKeyhole /> : <AlertTriangle />}</div>
      <span className="section-kicker">TIINGO DAILY EOD</span>
      <h2>{locked ? "股價分析限定內部環境" : "股價資料尚未就緒"}</h2>
      <p>{coverage?.reason ?? "請先在 .env 設定 TIINGO_API_TOKEN，並到資料同步頁啟動股價匯入。"}</p>
      <a className="button secondary" href="/setup"><Database size={16} />前往資料同步</a>
    </section>
  );
}

export function PriceAnalysis({ company }: { company: Company }) {
  const coverage = company.price_coverage;
  const [range, setRange] = useState<RangeKey>("1y");
  const [mode, setMode] = useState<PriceMode>("adjusted");
  const [chartMode, setChartMode] = useState<ChartMode>("trend");
  const [layers, setLayers] = useState<LayerOptions>({ volume: true, sma: true, bollinger: true });
  const [series, setSeries] = useState<PriceSeries | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [customStart, setCustomStart] = useState(coverage?.start_date ?? "");
  const [customEnd, setCustomEnd] = useState(coverage?.end_date ?? "");

  useEffect(() => {
    if (coverage?.status !== "available" || !coverage.end_date) return;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const start = range === "custom" ? customStart : rangeStart(range, coverage.end_date!);
        const end = range === "custom" ? customEnd : coverage.end_date!;
        const [nextSeries, nextAnalysis] = await Promise.all([
          api.prices(company.cik, start || undefined, end || undefined),
          api.priceAnalysis(company.cik),
        ]);
        setSeries(nextSeries);
        setAnalysis(nextAnalysis);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "無法讀取股價資料");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [company.cik, coverage?.end_date, coverage?.status, customEnd, customStart, range]);

  if (coverage?.status !== "available") return <LockedPriceState company={company} />;

  const latest = analysis?.latest;
  return (
    <div className="price-analysis">
      <div className="toolbar panel price-toolbar">
        <div className="segmented range-segmented">
          {ranges.map(([value, label]) => <button key={value} className={range === value ? "active" : ""} onClick={() => setRange(value)}>{label}</button>)}
        </div>
        <div className="price-toolbar-actions">
          <div className="segmented"><button className={mode === "adjusted" ? "active" : ""} onClick={() => setMode("adjusted")}>Adjusted</button><button className={mode === "raw" ? "active" : ""} onClick={() => setMode("raw")}>Raw</button></div>
          <div className="segmented"><button className={chartMode === "trend" ? "active" : ""} onClick={() => setChartMode("trend")}><TrendingUp size={13} />走勢</button><button className={chartMode === "candlestick" ? "active" : ""} onClick={() => setChartMode("candlestick")}><CandlestickChart size={13} />K 線</button></div>
        </div>
        <div className="price-layer-controls"><span>圖層</span>{(["volume", "sma", "bollinger"] as const).map((layer) => <button key={layer} type="button" aria-pressed={layers[layer]} disabled={mode === "raw" && layer !== "volume"} onClick={() => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}>{layer === "volume" ? "成交量" : layer === "sma" ? "SMA" : "Bollinger"}</button>)}</div>
      </div>
      {range === "custom" ? <div className="custom-range panel"><label>開始<input type="date" min={coverage.start_date ?? undefined} max={customEnd || (coverage.end_date ?? undefined)} value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label><label>結束<input type="date" min={customStart || (coverage.start_date ?? undefined)} max={coverage.end_date ?? undefined} value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label></div> : null}
      {loading ? <div className="loading-row"><RefreshCw className="spin" size={15} />讀取 Tiingo EOD 與分析指標…</div> : null}
      {error ? <p className="error-text">{error}</p> : null}

      {analysis && latest ? <>
        <section className="price-kpi-grid">
          <article className="kpi-card"><div><span>最新收盤</span><small>{mode === "adjusted" ? "ADJUSTED CLOSE" : "RAW CLOSE"}</small></div><strong>US$ {price(mode === "adjusted" ? latest.adj_close : latest.close)}</strong><footer><span>{latest.date}</span><span className={Number(latest.change_1d ?? 0) >= 0 ? "positive" : "negative"}>{percent(latest.change_1d)}</span></footer></article>
          <article className="kpi-card"><div><span>1 個月總報酬</span><small>ADJUSTED TOTAL RETURN</small></div><strong>{percent(analysis.returns.return_1m)}</strong><footer><span>含股利拆股</span></footer></article>
          <article className="kpi-card"><div><span>今年至今</span><small>YTD TOTAL RETURN</small></div><strong>{percent(analysis.returns.return_ytd)}</strong><footer><span>{analysis.as_of}</span></footer></article>
          <article className="kpi-card"><div><span>252 日波動</span><small>ANNUALIZED</small></div><strong>{percent(analysis.risk.volatility_252d)}</strong><footer><span>log return · √252</span></footer></article>
          <article className="kpi-card"><div><span>目前回撤</span><small>CURRENT DRAWDOWN</small></div><strong>{percent(analysis.risk.current_drawdown)}</strong><footer><span>Adjusted peak</span></footer></article>
          <article className="kpi-card"><div><span>距 52 週高點</span><small>RAW PRICE</small></div><strong>{percent(analysis.risk.distance_from_52w_high)}</strong><footer><span>High {price(analysis.risk.high_52w)}</span></footer></article>
        </section>

        <div className="data-caption"><CalendarDays size={14} />Daily EOD，非即時行情 · Tiingo · 最後交易日 {analysis.as_of} · 最後同步 {coverage.last_synced_at?.slice(0, 16).replace("T", " ") ?? "—"} · 報酬與排名固定採 adjusted total return</div>
      </> : null}

      {series ? <PriceCharts series={series} mode={mode} chartMode={chartMode} layers={layers} /> : null}

      {analysis ? <section className="price-matrix-grid">
        <article className="panel metric-matrix"><div className="panel-title"><h2>區間總報酬</h2><span>Adjusted</span></div><div className="matrix-body">{Object.entries(analysis.returns).map(([key, value]) => <div key={key}><span>{returnLabels[key] ?? key}</span><strong className={Number(value ?? 0) >= 0 ? "positive" : "negative"}>{percent(value)}</strong></div>)}</div></article>
        <article className="panel metric-matrix"><div className="panel-title"><h2>風險與回撤</h2><span>截至 {analysis.as_of}</span></div><div className="matrix-body">{Object.entries(analysis.risk).map(([key, value]) => <div key={key}><span>{riskLabels[key] ?? key}</span><strong>{key.includes("high_52w") || key.includes("low_52w") ? price(value) : percent(value)}</strong></div>)}</div></article>
      </section> : null}

      {analysis?.rankings.length ? <section className="panel ranking-panel"><div className="panel-title"><div><span className="section-kicker">TOP 100 CROSS-SECTION</span><h2>相對強弱與風險排名</h2></div><span>共同基準日 {analysis.rankings[0].as_of}</span></div><div className="ranking-grid">{analysis.rankings.map((rank) => <article key={rank.metric}><span>{rankLabels[rank.metric] ?? rank.metric}</span><strong>#{rank.rank}<small> / {rank.universe_size}</small></strong><div className="percentile-track"><i style={{ width: `${Number(rank.percentile) * 100}%` }} /></div><small>{percent(rank.percentile, 0)} percentile</small><details><summary>鄰近名次</summary>{rank.neighbors?.map((peer) => <div key={`${rank.metric}-${peer.ticker}`}><b>#{peer.rank} {peer.ticker}</b><span>{rank.metric === "volatility_252d" || rank.metric.includes("return") || rank.metric.includes("drawdown") ? percent(peer.value) : peer.value}</span></div>)}</details></article>)}</div></section> : null}

      {series?.events.length ? <section className="panel filing-reaction-panel"><div className="panel-title"><div><span className="section-kicker">PRICE TIMELINE</span><h2>股利、拆併股與 SEC 事件</h2></div><span>{series.start_date} — {series.end_date}</span></div><div className="table-scroll"><table><thead><tr><th>日期</th><th>事件</th><th>數值</th><th>來源</th></tr></thead><tbody>{series.events.slice().reverse().map((event, index) => <tr key={`${event.date}-${event.type}-${index}`}><th>{event.date}</th><td>{event.label}</td><td>{event.value ?? "—"}</td><td>{event.url ? <a href={event.url} target="_blank" rel="noreferrer">SEC filing</a> : "Tiingo"}</td></tr>)}</tbody></table></div></section> : null}

      {analysis?.filing_reactions.length ? <section className="panel filing-reaction-panel"><div className="panel-title"><div><span className="section-kicker">SEC EVENT STUDY</span><h2>財報申報後股價反應</h2></div><span>前一交易日收盤為基準</span></div><div className="table-scroll"><table><thead><tr><th>申報日</th><th>Form</th><th>+1 交易日</th><th>+5 交易日</th><th>+20 交易日</th></tr></thead><tbody>{analysis.filing_reactions.map((event) => <tr key={event.accession}><th><a href={event.url ?? "#"} target="_blank" rel="noreferrer">{event.filed}</a></th><td>{event.form}</td><td>{percent(event.return_1d)}</td><td>{percent(event.return_5d)}</td><td>{percent(event.return_20d)}</td></tr>)}</tbody></table></div></section> : null}

      {series ? <section className="panel price-data-panel"><div className="panel-title"><h2>等價資料表</h2><span>顯示最近 120 筆 · 完整資料透過 API 取得</span></div><div className="table-scroll"><table><thead><tr><th>日期</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Adj Close</th><th>Volume</th><th>RSI 14</th><th>Drawdown</th><th>事件</th></tr></thead><tbody>{series.points.slice(-120).reverse().map((point) => { const eventLabels = series.events.filter((event) => event.date === point.date).map((event) => event.label).join(" / "); return <tr key={point.date}><th>{point.date}</th><td>{price(point.open)}</td><td>{price(point.high)}</td><td>{price(point.low)}</td><td>{price(point.close)}</td><td>{price(point.adj_close)}</td><td>{compact(point.volume)}</td><td>{point.indicators.rsi_14 ? Number(point.indicators.rsi_14).toFixed(1) : "—"}</td><td>{percent(point.indicators.drawdown)}</td><td>{eventLabels || "—"}</td></tr>; })}</tbody></table></div></section> : null}
    </div>
  );
}
