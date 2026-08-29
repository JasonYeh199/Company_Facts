import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty-page">
      <span className="section-kicker">404</span>
      <h1>找不到這家公司</h1>
      <p>請確認 CIK，或回首頁用 ticker／公司名稱重新搜尋。</p>
      <Link className="button primary" href="/">返回首頁</Link>
    </div>
  );
}
