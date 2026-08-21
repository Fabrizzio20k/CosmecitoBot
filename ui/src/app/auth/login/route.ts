import { NextResponse } from "next/server";

import { createSession, credentialsAreValid, SESSION_COOKIE, sessionCookieOptions } from "@/server-auth";

export async function POST(request: Request) {
  let body: { username?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Solicitud inválida." }, { status: 400 });
  }

  if (typeof body.username !== "string" || typeof body.password !== "string") {
    return NextResponse.json({ detail: "Solicitud inválida." }, { status: 400 });
  }

  if (!credentialsAreValid(body.username, body.password)) {
    return NextResponse.json({ detail: "Usuario o contraseña inválidos." }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, createSession(), sessionCookieOptions);
  return response;
}
