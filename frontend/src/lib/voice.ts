import { api, newIdempotencyKey } from "./apiClient";
import type { Capabilities, Capture, Item, VoiceEntryPoint } from "./types";

export const VOICE_MIN_MS = 700;

export interface LaunchOptions {
  entryPoint: VoiceEntryPoint;
  contextualItemId?: string;
  /** Set when this recording is a numbered follow-up ("the first one") to a still-displayed
   * multiple-matches/ambiguity result, so the backend can resolve the selection deterministically. */
  contextualCaptureId?: string;
  allowedIntents?: ("create_note" | "create_task")[];
}

/** Everything needed to replay one upload exactly (same key, same bytes, same anchor). */
export interface UploadAttempt extends LaunchOptions {
  blob: Blob;
  filename: string;
  idempotencyKey: string;
  sha256: string;
  capturedAt: string;
  sourceTimezone: string;
  durationMs: number;
}

export async function getCapabilities(): Promise<Capabilities> {
  return api.getFresh<Capabilities>("/capabilities");
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function extensionFor(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "bin";
}

export function voiceIngestPath(attempt: UploadAttempt): string {
  const params = new URLSearchParams({
    size: String(attempt.blob.size),
    sha256: attempt.sha256,
    filename: attempt.filename,
    captured_at: attempt.capturedAt,
    source_timezone: attempt.sourceTimezone,
    entry_point: attempt.entryPoint,
    duration_ms: String(attempt.durationMs),
  });
  if (attempt.contextualItemId) params.set("contextual_item_id", attempt.contextualItemId);
  if (attempt.contextualCaptureId) params.set("contextual_capture_id", attempt.contextualCaptureId);
  for (const intent of attempt.allowedIntents ?? []) params.append("allowed_intent", intent);
  return `/voice-captures?${params.toString()}`;
}

/** One atomic, idempotent request: bytes + asset + capture are saved together or not at all. */
export async function uploadVoiceCapture(attempt: UploadAttempt): Promise<Capture> {
  return api.postRaw<Capture>(voiceIngestPath(attempt), attempt.blob, attempt.idempotencyKey);
}

export function newAttemptKey(): string {
  return newIdempotencyKey();
}

export interface AcceptOverrides {
  item_type?: "note" | "task";
  title?: string;
  content_md?: string;
  due_date?: string | null;
  due_time?: string | null;
  due_timezone?: string | null;
  destination?: { kind: "category" | "project" | "folder"; id: string; version?: number } | null;
}

export async function acceptProposal(
  capture: Capture,
  input: { overrides?: AcceptOverrides; confirmOverdue?: boolean; idempotencyKey?: string },
): Promise<{ capture: Capture; items: Item[]; action_id: string }> {
  return api.post(
    `/captures/${capture.id}/proposal/accept`,
    {
      expected_version: capture.version,
      expected_generation: capture.processing.generation,
      ...(input.overrides && Object.keys(input.overrides).length ? { overrides: input.overrides } : {}),
      ...(input.confirmOverdue ? { confirm_overdue: true } : {}),
    },
    input.idempotencyKey ?? newIdempotencyKey(),
  );
}

export async function createTypedCommand(text: string, entryPoint: VoiceEntryPoint = "global"): Promise<Capture> {
  return api.post<Capture>(
    "/captures",
    {
      source_type: "typed",
      raw_text: text,
      captured_at: new Date().toISOString(),
      source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      timestamp_origin: "client_supplied",
      metadata: { processing_profile: "voice_command", entry_point: entryPoint },
    },
    newIdempotencyKey(),
  );
}

export async function correctTranscript(capture: Capture, transcript: string): Promise<Capture> {
  return api.post<Capture>(
    `/captures/${capture.id}/corrections`,
    { expected_version: capture.version, transcript_text: transcript },
    newIdempotencyKey(),
  );
}

export function assetContentUrl(assetId: string): string {
  return `/api/v1/assets/${assetId}/content`;
}

const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** First recorder MIME type the browser can produce that the server also accepts (by container). */
export function pickRecorderMime(accepted: string[], isSupported: (mime: string) => boolean): string | null {
  const acceptedSet = new Set(accepted.map((mime) => mime.toLowerCase()));
  for (const mime of PREFERRED_MIME_TYPES) {
    const container = mime.split(";")[0];
    // `file --mime-type` labels WebM/Opus "video/webm", so either label counts as accepted.
    const ok = acceptedSet.has(container) || (container === "audio/webm" && acceptedSet.has("video/webm")) || (container === "audio/mp4" && acceptedSet.has("video/mp4"));
    if (ok && isSupported(mime)) return mime;
  }
  return null;
}

export const NON_RETRYABLE_CODES = new Set([
  "capability_disabled",
  "upload_too_large",
  "duration_too_long",
  "unsupported_media",
  "digest_mismatch",
  "size_mismatch",
  "invalid_input",
]);
