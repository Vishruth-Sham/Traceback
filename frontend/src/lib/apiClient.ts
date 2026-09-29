import { ApiError, ApiErrorBody } from "./types";

const BASE = "/api/v1";

async function request<T>(
  method: string,
  path: string,
  opts: { body?: unknown; idempotencyKey?: string; raw?: BodyInit; contentType?: string; noStore?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.raw !== undefined) {
    body = opts.raw;
    if (opts.contentType) headers["Content-Type"] = opts.contentType;
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  const res = await fetch(`${BASE}${path}`, { method, headers, body, ...(opts.noStore ? { cache: "no-store" as const } : {}) });
  if (res.status === 204) return undefined as T;

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : undefined;

  if (!res.ok) {
    const errBody: ApiErrorBody = data ?? {
      error: { code: "unknown_error", message: `Request failed with status ${res.status}` },
    };
    throw new ApiError(res.status, errBody);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  getFresh: <T>(path: string) => request<T>("GET", path, { noStore: true }),
  postRaw: <T>(path: string, raw: Blob, idempotencyKey: string) =>
    request<T>("POST", path, { raw, contentType: raw.type || "application/octet-stream", idempotencyKey }),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>("POST", path, { body, idempotencyKey }),
  patch: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>("PATCH", path, { body, idempotencyKey }),
  del: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>("DELETE", path, { body, idempotencyKey }),
  uploadAsset: <T>(filename: string, file: Blob, idempotencyKey?: string) =>
    request<T>("POST", `/assets?filename=${encodeURIComponent(filename)}`, {
      raw: file,
      contentType: file.type || "application/octet-stream",
      idempotencyKey,
    }),
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
