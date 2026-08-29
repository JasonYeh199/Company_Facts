import { NextRequest, NextResponse } from "next/server";
import { gunzipSync } from "node:zlib";

import type {
  Company,
  Fact,
  MetricPoint,
  PriceAnalysis,
  PriceCoverage,
  PriceSeries,
  SyncRun,
} from "@/lib/types";

type MetricDefinition = {
  code: string;
  name_en: string;
  name_zh: string;
  statement: string;
};

type SnapshotIndex = {
  snapshot: {
    generated_at: string;
    annual_from: string;
    interim_from: string;
    facts_per_company: number;
    read_only: boolean;
  };
  companies: Company[];
  definitions: MetricDefinition[];
  sync_runs: SyncRun[];
};

type PrivatePriceIndex = {
  included: boolean;
  generated_at: string;
  company_count: number;
  point_count: number;
  latest_date: string | null;
  latest_sync: SyncRun | null;
};

type CompanySnapshot = {
  company: Company;
  metrics: Record<string, Record<string, MetricPoint[]>>;
  facts: Fact[];
};

type PrivatePriceSnapshot = {
  coverage: PriceCoverage;
  series: PriceSeries;
  analysis: PriceAnalysis;
};

type RouteContext = { params: Promise<{ path: string[] }> };

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function error(detail: string | Record<string, string>, status: number) {
  return NextResponse.json({ detail }, { status });
}

function lockedCompany(company: Company): Company {
  return {
    ...company,
    price_coverage: {
      ticker: company.tickers[0]?.ticker ?? null,
      status: "locked",
      start_date: null,
      end_date: null,
      last_synced_at: null,
      reason: "Tiingo 授權限定內部／本機環境使用",
    },
  };
}

function normalizeCik(value: string): string | null {
  const digits = value.replace(/\D/g, "");
  if (!digits || digits.length > 10) return null;
  return digits.padStart(10, "0");
}

async function snapshotJson<T>(request: NextRequest, path: string): Promise<T> {
  const target = new URL(`/snapshot/${path}.gz`, request.url);
  const cookie = request.headers.get("cookie");
  const internalAuth = request.headers.get("x-private-internal-auth");
  const response = await fetch(target, {
    headers: {
      ...(cookie ? { cookie } : {}),
      ...(internalAuth ? { "x-private-internal-auth": internalAuth } : {}),
    },
    next: { revalidate: 3600 },
  });
  if (!response.ok) throw new Error(`Snapshot asset ${path} returned ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const decoded = bytes[0] === 0x1f && bytes[1] === 0x8b ? gunzipSync(bytes) : bytes;
  return JSON.parse(decoded.toString("utf-8")) as T;
}

async function privatePriceSnapshot(request: NextRequest, cik: string) {
  try {
    return await snapshotJson<PrivatePriceSnapshot>(request, `private-prices/${cik}.json`);
  } catch {
    return null;
  }
}

function oneYearBefore(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCFullYear(date.getUTCFullYear() - 1);
  return date.toISOString().slice(0, 10);
}

async function companySnapshot(request: NextRequest, value: string) {
  const cik = normalizeCik(value);
  if (!cik) return null;
  try {
    return await snapshotJson<CompanySnapshot>(request, `companies/${cik}.json`);
  } catch {
    return null;
  }
}

function filteredMetrics(
  snapshot: CompanySnapshot,
  frequency: string,
  requested: string[],
  dateFrom: string | null = null,
  dateTo: string | null = null,
) {
  const source = snapshot.metrics[frequency] ?? {};
  return Object.fromEntries(
    requested.flatMap((code) => {
      const points = (source[code] ?? []).filter(
        (point) =>
          (!dateFrom || point.period_end >= dateFrom) &&
          (!dateTo || point.period_end <= dateTo),
      );
      return points.length ? [[code, points] as const] : [];
    }),
  );
}

function requestedMetrics(request: NextRequest, index: SnapshotIndex) {
  const requested = request.nextUrl.searchParams.getAll("metric");
  return requested.length ? requested : index.definitions.map((item) => item.code);
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  let index: SnapshotIndex;
  try {
    index = await snapshotJson<SnapshotIndex>(request, "index.json");
  } catch {
    return error("Vercel snapshot 尚未建立", 503);
  }
  let privatePriceIndex: PrivatePriceIndex | null = null;
  if (process.env.PRIVATE_PRICE_SNAPSHOT === "enabled") {
    try {
      privatePriceIndex = await snapshotJson<PrivatePriceIndex>(
        request,
        "private-prices/index.json",
      );
    } catch {
      privatePriceIndex = null;
    }
  }

  if (path.length === 1 && path[0] === "setup") {
    const latestSync = index.sync_runs[0] ?? null;
    const privatePrices = privatePriceIndex?.included ? privatePriceIndex : undefined;
    return NextResponse.json({
      sec_configured: true,
      database_connected: true,
      data_dir: privatePrices ? "vercel://private-snapshot" : "vercel://read-only-snapshot",
      free_gib: 0,
      disk_requirement_gib: 0,
      company_count: index.companies.length,
      supported_company_count: index.companies.filter((item) => item.supported).length,
      latest_sync: latestSync,
      tiingo_configured: Boolean(privatePrices),
      price_company_count: privatePrices?.company_count ?? 0,
      latest_price_date: privatePrices?.latest_date ?? null,
      latest_price_sync: privatePrices?.latest_sync ?? null,
    });
  }

  if (path.length === 1 && path[0] === "sync-runs") {
    const priceSync = privatePriceIndex?.included ? privatePriceIndex.latest_sync : null;
    return NextResponse.json(priceSync ? [priceSync, ...index.sync_runs] : index.sync_runs);
  }

  if (path.length === 2 && path[0] === "companies" && path[1] === "search") {
    const query = (request.nextUrl.searchParams.get("q") ?? "").trim().toLowerCase();
    if (!query) return NextResponse.json([]);
    const digits = normalizeCik(query);
    const matches = index.companies
      .filter(
        (company) =>
          company.name.toLowerCase().includes(query) ||
          company.cik === digits ||
          company.tickers.some((security) =>
            security.ticker.toLowerCase().includes(query),
          ),
      )
      .sort((left, right) => {
        const leftExact = left.tickers.some(
          (item) => item.ticker.toLowerCase() === query,
        );
        const rightExact = right.tickers.some(
          (item) => item.ticker.toLowerCase() === query,
        );
        return Number(rightExact) - Number(leftExact) || left.name.localeCompare(right.name);
      })
      .slice(0, 20);
    return NextResponse.json(matches);
  }

  if (path.length === 2 && path[0] === "companies") {
    const snapshot = await companySnapshot(request, path[1]);
    if (!snapshot) return error("找不到公司", 404);
    if (!privatePriceIndex?.included) {
      return NextResponse.json(lockedCompany(snapshot.company));
    }
    const cik = normalizeCik(path[1]);
    const prices = cik ? await privatePriceSnapshot(request, cik) : null;
    return NextResponse.json({
      ...snapshot.company,
      price_coverage: prices?.coverage ?? {
        ticker: snapshot.company.tickers[0]?.ticker ?? null,
        status: "pending",
        start_date: null,
        end_date: null,
        last_synced_at: null,
        reason: "私人價格快照尚未涵蓋此公司",
      },
    });
  }

  if (
    path.length === 3 &&
    path[0] === "companies" &&
    (path[2] === "prices" || path[2] === "price-analysis")
  ) {
    if (!privatePriceIndex?.included) {
      return error(
        {
          code: "tiingo_internal_only",
          message: "Tiingo 股價資料僅限內部／本機環境使用",
        },
        403,
      );
    }
    const cik = normalizeCik(path[1]);
    const priceSnapshot = cik ? await privatePriceSnapshot(request, cik) : null;
    if (!priceSnapshot) {
      return error(
        { code: "price_data_unavailable", message: "私人快照尚未涵蓋此公司" },
        503,
      );
    }
    if (path[2] === "price-analysis") {
      const requestedAsOf = request.nextUrl.searchParams.get("as_of");
      if (requestedAsOf && requestedAsOf !== priceSnapshot.analysis.as_of) {
        return error("私人快照只提供最新分析基準日", 422);
      }
      return NextResponse.json(priceSnapshot.analysis);
    }
    const requestedStart = request.nextUrl.searchParams.get("start_date");
    const requestedEnd = request.nextUrl.searchParams.get("end_date");
    const endDate = requestedEnd ?? priceSnapshot.series.end_date;
    const startDate = requestedStart ?? oneYearBefore(endDate);
    if (startDate > endDate) return error("start_date 不得晚於 end_date", 422);
    if (
      startDate < priceSnapshot.series.start_date ||
      endDate > priceSnapshot.series.end_date
    ) {
      return error("查詢期間超出私人快照涵蓋範圍", 422);
    }
    return NextResponse.json({
      ...priceSnapshot.series,
      start_date: startDate,
      end_date: endDate,
      points: priceSnapshot.series.points.filter(
        (point) => point.date >= startDate && point.date <= endDate,
      ),
      events: priceSnapshot.series.events.filter(
        (event) => event.date >= startDate && event.date <= endDate,
      ),
    });
  }

  if (path.length === 3 && path[0] === "companies" && path[2] === "metrics") {
    const snapshot = await companySnapshot(request, path[1]);
    if (!snapshot) return error("找不到公司", 404);
    const frequency = request.nextUrl.searchParams.get("frequency") ?? "annual";
    const requested = requestedMetrics(request, index);
    const metrics = filteredMetrics(
      snapshot,
      frequency,
      requested,
      request.nextUrl.searchParams.get("date_from"),
      request.nextUrl.searchParams.get("date_to"),
    );
    return NextResponse.json({
      company: snapshot.company,
      frequency,
      metrics,
      unavailable: requested.filter((code) => !metrics[code]),
    });
  }

  if (
    path.length === 4 &&
    path[0] === "companies" &&
    path[2] === "statements"
  ) {
    const snapshot = await companySnapshot(request, path[1]);
    if (!snapshot) return error("找不到公司", 404);
    const statement = path[3] === "cash-flow" ? "cash_flow" : path[3];
    const frequency = request.nextUrl.searchParams.get("frequency") ?? "annual";
    const definitions = index.definitions.filter((item) => item.statement === statement);
    const metrics = filteredMetrics(
      snapshot,
      frequency,
      definitions.map((item) => item.code),
    );
    return NextResponse.json({
      company: snapshot.company,
      statement,
      frequency,
      metrics: definitions.map((item) => ({ ...item, points: metrics[item.code] ?? [] })),
    });
  }

  if (path.length === 3 && path[0] === "companies" && path[2] === "facts") {
    const snapshot = await companySnapshot(request, path[1]);
    if (!snapshot) return error("找不到公司", 404);
    const concept = (request.nextUrl.searchParams.get("concept") ?? "").toLowerCase();
    const form = request.nextUrl.searchParams.get("form");
    const unit = request.nextUrl.searchParams.get("unit");
    const dateFrom = request.nextUrl.searchParams.get("date_from");
    const dateTo = request.nextUrl.searchParams.get("date_to");
    const facts = snapshot.facts.filter(
      (fact) =>
        (!concept || fact.concept.toLowerCase().includes(concept)) &&
        (!form || fact.form === form) &&
        (!unit || fact.unit === unit) &&
        (!dateFrom || fact.period_end >= dateFrom) &&
        (!dateTo || fact.period_end <= dateTo),
    );
    const limit = Math.min(
      200,
      Math.max(1, Number(request.nextUrl.searchParams.get("limit") ?? 50)),
    );
    const offset = Math.max(0, Number(request.nextUrl.searchParams.get("offset") ?? 0));
    return NextResponse.json({
      items: facts.slice(offset, offset + limit),
      total: facts.length,
      limit,
      offset,
    });
  }

  if (
    path.length === 5 &&
    path[0] === "companies" &&
    path[2] === "metrics" &&
    path[4] === "revisions"
  ) {
    const snapshot = await companySnapshot(request, path[1]);
    if (!snapshot) return error("找不到公司", 404);
    const frequency = request.nextUrl.searchParams.get("frequency") ?? "annual";
    const periodEnd = request.nextUrl.searchParams.get("period_end");
    const points = snapshot.metrics[frequency]?.[path[3]] ?? [];
    return NextResponse.json(
      periodEnd ? points.filter((point) => point.period_end === periodEnd) : points,
    );
  }

  if (path.length === 1 && path[0] === "compare") {
    const ciks = [...new Set(request.nextUrl.searchParams.getAll("cik"))];
    if (ciks.length < 2 || ciks.length > 5) {
      return error("比較公司數必須介於 2 到 5 家", 422);
    }
    const snapshots = await Promise.all(ciks.map((cik) => companySnapshot(request, cik)));
    if (snapshots.some((item) => item === null)) return error("找不到公司", 404);
    const frequency = request.nextUrl.searchParams.get("frequency") ?? "annual";
    const requested = request.nextUrl.searchParams.getAll("metric");
    const metricCodes = requested.length
      ? requested
      : ["revenue", "net_income", "eps_diluted", "free_cash_flow", "roe"];
    const available = snapshots as CompanySnapshot[];
    return NextResponse.json({
      frequency,
      companies: available.map((item) => item.company),
      series: Object.fromEntries(
        available.map((item) => [
          item.company.cik,
          filteredMetrics(item, frequency, metricCodes),
        ]),
      ),
    });
  }

  return error("找不到 API endpoint", 404);
}

export async function POST(_request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  if (path.length === 1 && path[0] === "sync-runs") {
    return error("Vercel 部署為唯讀快照；請在本機執行 SEC 同步", 403);
  }
  return error("找不到 API endpoint", 404);
}
