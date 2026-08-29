import { Database, GitCompareArrows, LogOut, Settings2 } from "lucide-react";
import Link from "next/link";
import { cookies } from "next/headers";

import { PRIVATE_SESSION_COOKIE } from "@/lib/private-auth";

export async function Header() {
  const showLogout = Boolean(
    process.env.PRIVATE_SITE_PASSWORD && (await cookies()).get(PRIVATE_SESSION_COOKIE),
  );
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="Fundamental Lens 首頁">
        <span className="brand-mark"><Database size={18} /></span>
        <span>
          <strong>Fundamental Lens</strong>
          <small>SEC COMPANY FACTS</small>
        </span>
      </Link>
      <nav aria-label="主要導覽">
        <Link href="/compare"><GitCompareArrows size={16} />公司比較</Link>
        <Link href="/setup"><Settings2 size={16} />資料同步</Link>
        {showLogout ? <form action="/api/auth/logout" method="post"><button type="submit"><LogOut size={16} />登出</button></form> : null}
      </nav>
    </header>
  );
}
