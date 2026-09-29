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

// Voice ingest is the one route whose body is bounded here. This is bounded
// buffering, not streaming: the whole recording is still held in memory before
// it is forwarded, but never more than the cap (+ one chunk), whatever the
// client claims. Every other route keeps its existing behaviour.
const VOICE_INGEST_PATH = "voice-captures";
const DEFAULT_VOICE_MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

function voiceMaxUploadBytes(): number {
  const raw = process.env.TRACEBACK_VOICE_MAX_UPLOAD_BYTES;
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_VOICE_MAX_UPLOAD_BYTES;
}

function errorResponse(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
  return NextResponse.json({ error: { code, message, details } }, { status });
}

/** Read the request body, giving up (null) the moment it exceeds `cap` bytes. */
async function readBounded(req: NextRequest, cap: number): Promise<Uint8Array | null> {
  if (!req.body) return new Uint8Array(0);
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > cap) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function readRequestBody(req: NextRequest, path: string): Promise<BodyInit | undefined | NextResponse> {
  if (["GET", "HEAD"].includes(req.method)) return undefined;
  if (req.method !== "POST" || path !== VOICE_INGEST_PATH) return await req.arrayBuffer();

  const cap = voiceMaxUploadBytes();
  const tooLarge = () =>
    errorResponse(413, "upload_too_large", "Recording exceeds the voice upload limit", { max_upload_bytes: cap });
  const declared = Number.parseInt(req.headers.get("content-length") ?? "", 10);
  if (Number.isFinite(declared) && declared > cap) return tooLarge(); // before the body is read at all
  const bytes = await readBounded(req, cap);
  if (bytes === null) return tooLarge();
  const declaredSize = req.nextUrl.searchParams.get("size");
  if (declaredSize !== null && Number.parseInt(declaredSize, 10) !== bytes.byteLength) {
    return errorResponse(400, "size_mismatch", "The recording size does not match the declared size");
  }
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
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

  const body = await readRequestBody(req, path);
  if (body instanceof NextResponse) return body;
  const init: RequestInit = { method: req.method, headers, body, cache: "no-store" };

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
