import { NextRequest, NextResponse } from "next/server";

import { PRIVATE_SESSION_COOKIE, verifyPrivateSession } from "@/lib/private-auth";

const publicPaths = new Set(["/login", "/api/auth/login", "/api/auth/logout"]);

export async function proxy(request: NextRequest) {
  const password = process.env.PRIVATE_SITE_PASSWORD;
  const secret = process.env.PRIVATE_SITE_SESSION_SECRET;
  if (!password || !secret) return NextResponse.next();

  const path = request.nextUrl.pathname;
  if (publicPaths.has(path)) return NextResponse.next();

  const internalRequest = request.headers.get("x-private-internal-auth") === secret;
  const authenticated = internalRequest || await verifyPrivateSession(
      request.cookies.get(PRIVATE_SESSION_COOKIE)?.value,
      secret,
    );
  if (!authenticated) {
    if (path.startsWith("/api/")) {
      return NextResponse.json(
        { detail: { code: "private_auth_required", message: "請先登入私人研究站" } },
        { status: 401 },
      );
    }
    const login = new URL("/login", request.url);
    login.searchParams.set("next", `${path}${request.nextUrl.search}`);
    return NextResponse.redirect(login);
  }

  const response = NextResponse.next();
  response.headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
