// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createHash } from "node:crypto";
import { GET, POST } from "@/app/api/v1/[...path]/route";

const CAP = 1024;
const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) });

function streamOf(chunks: Uint8Array[], onRead?: (index: number) => void): ReadableStream<Uint8Array> {
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index >= chunks.length) {
        controller.close();
        return;
      }
      onRead?.(index);
      controller.enqueue(chunks[index++]);
    },
  });
}

function voiceRequest(body: ReadableStream<Uint8Array> | Uint8Array, opts: { query?: string; headers?: Record<string, string> } = {}) {
  return new NextRequest(`http://localhost/api/v1/voice-captures${opts.query ?? ""}`, {
    method: "POST",
    body: body as BodyInit,
    headers: { "content-type": "audio/webm", "idempotency-key": "key-1", ...opts.headers },
    duplex: "half", // Node's fetch requires this for stream bodies
  });
}

const upstream = vi.fn();

beforeEach(() => {
  process.env.TRACEBACK_API_BASE_URL = "http://backend.test";
  process.env.TRACEBACK_API_TOKEN = "secret-token";
  process.env.TRACEBACK_VOICE_MAX_UPLOAD_BYTES = String(CAP);
  upstream.mockReset();
  upstream.mockResolvedValue(new Response(JSON.stringify({ id: "cap-1" }), { status: 201, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", upstream);
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.TRACEBACK_VOICE_MAX_UPLOAD_BYTES;
});

describe("voice ingest proxy: bounded buffering", () => {
  it("rejects a declared Content-Length above the cap with 413 before reading the body or calling upstream", async () => {
    const request = voiceRequest(streamOf([new Uint8Array(10)]), { headers: { "content-length": String(CAP + 1) }, query: `?size=${CAP + 1}` });
    const response = await POST(request, ctx(["voice-captures"]));
    expect(response.status).toBe(413);
    expect((await response.json()).error.code).toBe("upload_too_large");
    expect(request.bodyUsed).toBe(false); // the body was never read or locked
    expect(upstream).not.toHaveBeenCalled();
  });

  it("aborts at the cap when a lying or absent Content-Length hides an oversize stream, reading at most cap + one chunk", async () => {
    const chunk = new Uint8Array(400);
    let reads = 0;
    const chunks = Array.from({ length: 50 }, () => chunk);
    const request = voiceRequest(streamOf(chunks, () => reads++), { headers: { "content-length": "10" }, query: "?size=10" });
    const response = await POST(request, ctx(["voice-captures"]));
    expect(response.status).toBe(413);
    // The route stops at cap + one chunk; the stream's own read-ahead may add a couple of chunks, never all 50.
    expect(reads * chunk.byteLength).toBeLessThanOrEqual(CAP + 3 * chunk.byteLength);
    expect(reads).toBeLessThan(50);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("accepts a body of exactly the cap", async () => {
    const bytes = new Uint8Array(CAP).fill(7);
    const response = await POST(voiceRequest(bytes, { query: `?size=${CAP}` }), ctx(["voice-captures"]));
    expect(response.status).toBe(201);
    expect(upstream).toHaveBeenCalledTimes(1);
  });

  it("returns 400 when the counted bytes differ from the size query value, without calling upstream", async () => {
    const response = await POST(voiceRequest(new Uint8Array(100), { query: "?size=99" }), ctx(["voice-captures"]));
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe("size_mismatch");
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards bytes exactly, plus query string, Idempotency-Key, content type, and the server-side token", async () => {
    const bytes = Uint8Array.from({ length: 700 }, (_, index) => (index * 31) % 256);
    const query = `?size=700&sha256=${createHash("sha256").update(bytes).digest("hex")}&entry_point=tasks&allowed_intent=create_task`;
    await POST(voiceRequest(streamOf([bytes.slice(0, 300), bytes.slice(300)]), { query }), ctx(["voice-captures"]));
    const [url, init] = upstream.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`http://backend.test/api/v1/voice-captures${query}`);
    const headers = init.headers as Headers;
    expect(headers.get("idempotency-key")).toBe("key-1");
    expect(headers.get("content-type")).toBe("audio/webm");
    expect(headers.get("authorization")).toBe("Bearer secret-token");
    expect(headers.get("x-traceback-client")).toBe("web");
    const sent = new Uint8Array(init.body as ArrayBuffer);
    expect(createHash("sha256").update(sent).digest("hex")).toBe(createHash("sha256").update(bytes).digest("hex"));
  });

  it("passes backend 507, 415 and 409 responses through unchanged", async () => {
    for (const [status, code] of [[507, "insufficient_storage"], [415, "unsupported_media"], [409, "duplicate_recording"]] as const) {
      upstream.mockResolvedValueOnce(new Response(JSON.stringify({ error: { code, message: "m", details: {} } }), { status, headers: { "content-type": "application/json" } }));
      const response = await POST(voiceRequest(new Uint8Array(10), { query: "?size=10" }), ctx(["voice-captures"]));
      expect(response.status).toBe(status);
      expect((await response.json()).error.code).toBe(code);
    }
  });

  it("uses the default 10 MB cap and never reads a NEXT_PUBLIC value", () => {
    delete process.env.TRACEBACK_VOICE_MAX_UPLOAD_BYTES;
    process.env.NEXT_PUBLIC_TRACEBACK_VOICE_MAX_UPLOAD_BYTES = "1";
    const request = voiceRequest(new Uint8Array(2048), { query: "?size=2048" });
    return POST(request, ctx(["voice-captures"])).then((response) => {
      expect(response.status).toBe(201); // 2 KB is under the 10 MB default; the NEXT_PUBLIC value was ignored
      delete process.env.NEXT_PUBLIC_TRACEBACK_VOICE_MAX_UPLOAD_BYTES;
    });
  });
});

describe("non-voice routes are unchanged", () => {
  it("still buffers POST /assets whole, even above the voice cap", async () => {
    const big = new Uint8Array(CAP * 5).fill(1);
    const request = new NextRequest("http://localhost/api/v1/assets?filename=a.bin", { method: "POST", body: big, headers: { "content-type": "application/octet-stream" } });
    const response = await POST(request, ctx(["assets"]));
    expect(response.status).toBe(201);
    const init = upstream.mock.calls[0][1] as RequestInit;
    expect((init.body as ArrayBuffer).byteLength).toBe(big.byteLength);
  });

  it("forwards GET without a body", async () => {
    upstream.mockResolvedValueOnce(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    const response = await GET(new NextRequest("http://localhost/api/v1/capabilities"), ctx(["capabilities"]));
    expect(response.status).toBe(200);
    expect((upstream.mock.calls[0][1] as RequestInit).body).toBeUndefined();
  });

  it("reports an unreachable backend as 503", async () => {
    upstream.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const response = await POST(voiceRequest(new Uint8Array(10), { query: "?size=10" }), ctx(["voice-captures"]));
    expect(response.status).toBe(503);
  });
});
