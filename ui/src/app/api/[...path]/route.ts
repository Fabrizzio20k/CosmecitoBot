import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const apiBaseUrl = process.env.API_INTERNAL_URL ?? "http://api:8000";
const adminToken = process.env.API_ADMIN_TOKEN;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!adminToken) {
    return Response.json({ detail: "Falta configurar API_ADMIN_TOKEN en la UI." }, { status: 500 });
  }
  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.set("X-Admin-Token", adminToken);

  const response = await fetch(`${apiBaseUrl}/${path.join("/")}${incomingUrl.search}`, {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: response.headers,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
