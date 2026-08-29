import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CompanyDashboard } from "@/components/company-dashboard";
import { ApiError, api } from "@/lib/api";

type Props = { params: Promise<{ cik: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const company = await api.company((await params).cik);
    return { title: company.tickers[0]?.ticker ?? company.name };
  } catch {
    return { title: "公司研究" };
  }
}

export default async function CompanyPage({ params }: Props) {
  const { cik } = await params;
  let company;
  let metrics;
  try {
    company = await api.company(cik);
    metrics = company.supported ? await api.metrics(cik, "annual") : null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
  if (!company.supported || !metrics) {
    return (
      <div className="empty-page">
        <span className="section-kicker">UNSUPPORTED TAXONOMY</span>
        <h1>{company.name}</h1>
        <p>{company.coverage_reason ?? "此公司目前沒有可正規化的 US-GAAP Company Facts。"}</p>
      </div>
    );
  }
  return <CompanyDashboard company={company} initial={metrics} />;
}
