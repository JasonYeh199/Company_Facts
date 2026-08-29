import { NextRequest, NextResponse } from "next/server";
import { gunzipSync } from "node:zlib";

import type {
  Company,
  Fact,
  MetricPoint,
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

type CompanySnapshot = {
  company: Company;
  metrics: Record<string, Record<string, MetricPoint[]>>;
  facts: Fact[];
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
  const response = await fetch(target, { next: { revalidate: 3600 } });
  if (!response.ok) throw new Error(`Snapshot asset ${path} returned ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const decoded = bytes[0] === 0x1f && bytes[1] === 0x8b ? gunzipSync(bytes) : bytes;
  return JSON.parse(decoded.toString("utf-8")) as T;
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

  if (path.length === 1 && path[0] === "setup") {
    const latestSync = index.sync_runs[0] ?? null;
    return NextResponse.json({
      sec_configured: true,
      database_connected: true,
      data_dir: "vercel://read-only-snapshot",
      free_gib: 0,
      disk_requirement_gib: 0,
      company_count: index.companies.length,
      supported_company_count: index.companies.filter((item) => item.supported).length,
      latest_sync: latestSync,
      tiingo_configured: false,
      price_company_count: 0,
      latest_price_date: null,
      latest_price_sync: null,
    });
  }

  if (path.length === 1 && path[0] === "sync-runs") {
    return NextResponse.json(index.sync_runs);
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
    return snapshot
      ? NextResponse.json(lockedCompany(snapshot.company))
      : error("找不到公司", 404);
  }

  if (
    path.length === 3 &&
    path[0] === "companies" &&
    (path[2] === "prices" || path[2] === "price-analysis")
  ) {
    return error(
      {
        code: "tiingo_internal_only",
        message: "Tiingo 股價資料僅限內部／本機環境使用",
      },
      403,
    );
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
