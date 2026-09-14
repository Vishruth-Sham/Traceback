import { NextRequest, NextResponse } from "next/server";

// Server-only proxy to the local FastAPI backend. Keeps TRACEBACK_API_TOKEN
// out of browser JS: the browser calls same-origin /api/v1/*, and this route
// attaches the bearer token before forwarding to TRACEBACK_API_BASE_URL.

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding"]);

function backendBase(): string {
  const base = process.env.TRACEBACK_API_BASE_URL;
  if (!base) throw new Error("TRACEBACK_API_BASE_URL is not configured");
  return base.replace(/\/+$/, "");
}

function apiToken(): string {
  const token = process.env.TRACEBACK_API_TOKEN;
  if (!token) throw new Error("TRACEBACK_API_TOKEN is not configured");
  return token;
}

async function forward(req: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");
  const search = req.nextUrl.search;
  const url = `${backendBase()}/api/v1/${path}${search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const idempotencyKey = req.headers.get("idempotency-key");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  headers.set("X-Traceback-Client", "web");
  headers.set("Authorization", `Bearer ${apiToken()}`);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const init: RequestInit = {
    method: req.method,
    headers,
    body: hasBody ? await req.arrayBuffer() : undefined,
    cache: "no-store",
  };

  let upstream: Response;
  try {
    upstream = await fetch(url, init);
  } catch {
    return NextResponse.json(
      { error: { code: "backend_unreachable", message: "The local Traceback API is not reachable." } },
      { status: 503 },
    );
  }

  const outHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) outHeaders.set(key, value);
  });

  const buf = await upstream.arrayBuffer();
  return new NextResponse(buf, { status: upstream.status, headers: outHeaders });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return forward(req, path);
}
