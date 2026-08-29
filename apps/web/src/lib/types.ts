import type { components } from "./generated";

type Schemas = components["schemas"];

export type Security = Schemas["SecurityOut"];
export type Company = Schemas["CompanySummary"] &
  Partial<Omit<Schemas["CompanyDetail"], keyof Schemas["CompanySummary"]>>;
export type Source = Omit<Schemas["SourceOut"], "lineage"> & {
  lineage: Record<string, unknown>[];
};
export type MetricPoint = Omit<Schemas["MetricPointOut"], "source"> & {
  source: Source;
};
export type MetricSeries = Omit<
  Schemas["MetricSeriesOut"],
  "company" | "metrics" | "unavailable"
> & {
  company: Company;
  metrics: Record<string, MetricPoint[]>;
  unavailable: string[];
};
export type Statement = Omit<Schemas["StatementOut"], "company" | "metrics"> & {
  company: Company;
  metrics: {
    code: string;
    name_en: string;
    name_zh: string;
    points: MetricPoint[];
  }[];
};
export type Fact = Schemas["FactOut"];
export type FactsPage = Schemas["FactsPage"];
export type SyncRun = Schemas["SyncRunOut"];
export type SetupStatus = Schemas["SetupStatus"];
export type CompareData = Omit<Schemas["CompareOut"], "companies" | "series"> & {
  companies: Company[];
  series: Record<string, Record<string, MetricPoint[]>>;
};
export type PriceCoverage = Schemas["PriceCoverageOut"];
export type PricePoint = Schemas["PricePointOut"];
export type PriceEvent = Schemas["PriceEventOut"];
export type PriceSeries = Omit<Schemas["PriceSeriesOut"], "company"> & {
  company: Company;
};
export type PriceAnalysis = Omit<Schemas["PriceAnalysisOut"], "company"> & {
  company: Company;
};
