import { describe, expect, it } from "vitest";
import { NON_RETRYABLE_CODES, UploadAttempt, extensionFor, pickRecorderMime, voiceIngestPath } from "../voice";

const ACCEPTED = ["video/webm", "audio/ogg", "audio/mp4", "audio/x-wav"];

describe("pickRecorderMime", () => {
  it("prefers WebM/Opus when supported and treats the server's video/webm label as WebM", () => {
    expect(pickRecorderMime(ACCEPTED, () => true)).toBe("audio/webm;codecs=opus");
  });
  it("falls back to MP4 for Safari-style recorders", () => {
    expect(pickRecorderMime(ACCEPTED, (mime) => mime === "audio/mp4")).toBe("audio/mp4");
  });
  it("returns null when the browser records nothing the server accepts", () => {
    expect(pickRecorderMime(["audio/wav"], () => true)).toBeNull();
    expect(pickRecorderMime(ACCEPTED, () => false)).toBeNull();
  });
});

describe("voiceIngestPath", () => {
  it("carries size, digest, anchor, entry point, context hint, and allowed intents as query parameters", () => {
    const attempt: UploadAttempt = {
      blob: new Blob([new Uint8Array(5)], { type: "audio/webm" }),
      filename: "voice.webm",
      idempotencyKey: "k",
      sha256: "a".repeat(64),
      capturedAt: "2026-09-26T04:44:00.000Z",
      sourceTimezone: "Asia/Kolkata",
      durationMs: 2500,
      entryPoint: "tasks",
      contextualItemId: "11111111-1111-1111-1111-111111111111",
      allowedIntents: ["create_task"],
    };
    const url = new URL("http://x" + voiceIngestPath(attempt));
    expect(url.pathname).toBe("/voice-captures");
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ size: "5", sha256: "a".repeat(64), entry_point: "tasks", source_timezone: "Asia/Kolkata", duration_ms: "2500", contextual_item_id: attempt.contextualItemId, allowed_intent: "create_task" });
    expect(url.searchParams.get("captured_at")).toBe(attempt.capturedAt);
  });
});

describe("misc", () => {
  it("maps recorder MIME types to file extensions", () => {
    expect([extensionFor("audio/webm;codecs=opus"), extensionFor("audio/mp4"), extensionFor("audio/ogg")]).toEqual(["webm", "m4a", "ogg"]);
  });
  it("never offers retry for policy or validation refusals", () => {
    for (const code of ["capability_disabled", "upload_too_large", "unsupported_media", "duration_too_long"]) expect(NON_RETRYABLE_CODES.has(code)).toBe(true);
    expect(NON_RETRYABLE_CODES.has("insufficient_storage")).toBe(false); // retry is right once space is freed
  });
});
