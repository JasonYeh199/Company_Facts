import type { Metadata } from "next";

import { CompareWorkspace } from "@/components/compare-workspace";

export const metadata: Metadata = { title: "公司比較" };

export default function ComparePage() {
  return <CompareWorkspace />;
}

