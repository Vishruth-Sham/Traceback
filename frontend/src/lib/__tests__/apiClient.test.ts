import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../apiClient";
import { ApiError } from "../types";

const originalFetch = global.fetch;

describe("apiClient", () => {
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns parsed JSON on success", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await api.get<{ items: unknown[] }>("/tasks");
    expect(result.items).toEqual([]);
  });

  it("returns undefined for a 204 No Content response", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    const result = await api.del("/items/abc?expected_version=1&confirm=true");
    expect(result).toBeUndefined();
  });

  it("throws an ApiError carrying the status and code on a version conflict", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "version_conflict", message: "stale version" } }),
        { status: 409, headers: { "content-type": "application/json" } },
      ),
    );
    await expect(api.patch("/items/abc", { expected_version: 1 })).rejects.toMatchObject({
      status: 409,
      code: "version_conflict",
    });
  });

  it("exposes isVersionConflict as true only for 409 responses", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "version_conflict", message: "stale" } }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );
    try {
      await api.patch("/items/abc", { expected_version: 1 });
      expect.unreachable("expected a rejection");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).isVersionConflict).toBe(true);
    }
  });

  it("falls back to a generic error body when the response is not JSON", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response("Internal Server Error", { status: 500 }));
    await expect(api.get("/items")).rejects.toMatchObject({ status: 500 });
  });
});
