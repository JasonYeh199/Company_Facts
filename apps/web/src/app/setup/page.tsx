import type { Metadata } from "next";

import { SyncPanel } from "@/components/sync-panel";
import { api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";

export const metadata: Metadata = { title: "資料同步" };

async function load(): Promise<SetupStatus | null> {
  try { return await api.setup(); } catch { return null; }
}

export default async function SetupPage() {
  return <SyncPanel initial={await load()} />;
}
