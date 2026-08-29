import { Database, GitCompareArrows, Settings2 } from "lucide-react";
import Link from "next/link";

export function Header() {
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
      </nav>
    </header>
  );
}

