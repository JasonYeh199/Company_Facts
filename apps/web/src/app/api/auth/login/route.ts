import { timingSafeEqual } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import { createPrivateSession, PRIVATE_SESSION_COOKIE } from "@/lib/private-auth";

export const runtime = "nodejs";

function equal(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function safeNext(value: FormDataEntryValue | null): string {
  const next = typeof value === "string" ? value : "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export async function POST(request: NextRequest) {
  const expectedUser = process.env.PRIVATE_SITE_USERNAME ?? "research";
  const expectedPassword = process.env.PRIVATE_SITE_PASSWORD;
  const secret = process.env.PRIVATE_SITE_SESSION_SECRET;
  if (!expectedPassword || !secret) {
    return NextResponse.json({ detail: "私人站登入尚未設定" }, { status: 503 });
  }

  const form = await request.formData();
  const username = String(form.get("username") ?? "");
  const password = String(form.get("password") ?? "");
  const next = safeNext(form.get("next"));
  if (!equal(username, expectedUser) || !equal(password, expectedPassword)) {
    const target = new URL("/login", request.url);
    target.searchParams.set("error", "1");
    target.searchParams.set("next", next);
    return NextResponse.redirect(target, 303);
  }

  const response = NextResponse.redirect(new URL(next, request.url), 303);
  response.cookies.set(PRIVATE_SESSION_COOKIE, await createPrivateSession(secret), {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 12 * 60 * 60,
  });
  return response;
}
