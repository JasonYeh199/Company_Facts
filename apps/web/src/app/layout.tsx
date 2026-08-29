import type { Metadata } from "next";
import { Inter, Noto_Sans_TC } from "next/font/google";
import type { ReactNode } from "react";

import { Header } from "@/components/header";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const noto = Noto_Sans_TC({ subsets: ["latin"], variable: "--font-noto" });

export const metadata: Metadata = {
  title: { default: "Fundamental Lens", template: "%s · Fundamental Lens" },
  description: "可追溯至 SEC EDGAR 的美股基本面研究資料庫",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const isReadOnlySnapshot = Boolean(process.env.VERCEL);
  return (
    <html lang="zh-Hant" className={`${inter.variable} ${noto.variable}`}>
      <body>
        <Header />
        <main>{children}</main>
        <footer className="site-footer">
          <span>資料來源 SEC EDGAR</span>
          {isReadOnlySnapshot ? <span>Vercel 唯讀快照 · Annual 2019+ · Quarterly/TTM 2023+</span> : null}
          <span>僅供研究，不構成投資建議</span>
        </footer>
      </body>
    </html>
  );
}
