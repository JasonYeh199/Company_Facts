import type {
  Company,
  CompareData,
  FactsPage,
  MetricPoint,
  MetricSeries,
  PriceAnalysis,
  PriceSeries,
  SetupStatus,
  Statement,
  SyncRun,
} from "./types";

function baseUrl(): string {
  if (typeof window === "undefined") {
    const vercelHost =
      process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL;
    return (
      process.env.API_INTERNAL_BASE_URL ??
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      (vercelHost ? `https://${vercelHost}/api/v1` : undefined) ??
      "http://localhost:8000/api/v1"
    );
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const internalAuth =
    typeof window === "undefined" ? process.env.PRIVATE_SITE_SESSION_SECRET : undefined;
  const response = await fetch(`${baseUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(internalAuth ? { "x-private-internal-auth": internalAuth } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `API error ${response.status}`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as {
        detail?: string | { code?: string; message?: string };
      };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message) message = body.detail.message;
      if (typeof body.detail === "object") code = body.detail?.code;
    } catch {
      // Keep the status-based message when an upstream proxy returns non-JSON.
    }
    throw new ApiError(response.status, message, code);
  }
  return response.json() as Promise<T>;
}

export const api = {
  setup: () => request<SetupStatus>("/setup"),
  search: (query: string) =>
    request<Company[]>(`/companies/search?q=${encodeURIComponent(query)}`),
  company: (cik: string) => request<Company>(`/companies/${cik}`),
  prices: (cik: string, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const query = params.size ? `?${params}` : "";
    return request<PriceSeries>(`/companies/${cik}/prices${query}`);
  },
  priceAnalysis: (cik: string, asOf?: string) =>
    request<PriceAnalysis>(
      `/companies/${cik}/price-analysis${asOf ? `?as_of=${asOf}` : ""}`,
    ),
  metrics: (cik: string, frequency: string, metrics?: string[]) => {
    const params = new URLSearchParams({ frequency });
    metrics?.forEach((metric) => params.append("metric", metric));
    return request<MetricSeries>(`/companies/${cik}/metrics?${params}`);
  },
  statement: (cik: string, statement: string, frequency: string) =>
    request<Statement>(
      `/companies/${cik}/statements/${statement}?frequency=${frequency}`,
    ),
  revisions: (cik: string, metric: string, frequency: string, periodEnd: string) =>
    request<MetricPoint[]>(
      `/companies/${cik}/metrics/${metric}/revisions?frequency=${frequency}&period_end=${periodEnd}`,
    ),
  facts: (cik: string, filters: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    return request<FactsPage>(`/companies/${cik}/facts?${params}`);
  },
  compare: (ciks: string[], frequency: string, metrics: string[]) => {
    const params = new URLSearchParams({ frequency });
    ciks.forEach((cik) => params.append("cik", cik));
    metrics.forEach((metric) => params.append("metric", metric));
    return request<CompareData>(`/compare?${params}`);
  },
  syncRuns: () => request<SyncRun[]>("/sync-runs"),
  createSync: (
    kind: "bulk" | "top100" | "company" | "prices" | "price_company",
    cik?: string,
  ) =>
    request<SyncRun>("/sync-runs", {
      method: "POST",
      body: JSON.stringify({ kind, cik: cik || null }),
    }),
};
