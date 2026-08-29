import { Database, LockKeyhole } from "lucide-react";

type LoginPageProps = {
  searchParams: Promise<{ error?: string; next?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const next = params.next?.startsWith("/") && !params.next.startsWith("//") ? params.next : "/";
  return (
    <div className="private-login-page">
      <section className="private-login-card">
        <div className="private-login-icon"><LockKeyhole /></div>
        <span className="section-kicker">PRIVATE RESEARCH ENVIRONMENT</span>
        <h1>登入投研資料庫</h1>
        <p>此環境包含僅限內部使用的 Tiingo Daily EOD 資料。</p>
        <form action="/api/auth/login" method="post">
          <input type="hidden" name="next" value={next} />
          <label>使用者名稱<input name="username" autoComplete="username" required autoFocus /></label>
          <label>密碼<input name="password" type="password" autoComplete="current-password" required /></label>
          {params.error ? <span className="private-login-error">帳號或密碼不正確</span> : null}
          <button className="button primary" type="submit"><Database size={16} />登入私人站</button>
        </form>
        <small>未經授權不得存取、分享或再散布資料。</small>
      </section>
    </div>
  );
}
