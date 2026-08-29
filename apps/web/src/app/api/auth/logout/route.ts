import { NextRequest, NextResponse } from "next/server";

import { PRIVATE_SESSION_COOKIE } from "@/lib/private-auth";

export async function POST(request: NextRequest) {
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.set(PRIVATE_SESSION_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return response;
}
