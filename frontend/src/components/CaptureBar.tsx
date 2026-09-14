"use client";

import { useRef, useState } from "react";
import { CornerDownLeft, Mic, Square, Loader2 } from "lucide-react";
import { createCapture, uploadAsset } from "@/lib/traceback";
import { newIdempotencyKey } from "@/lib/apiClient";
import { ApiError } from "@/lib/types";
import { useToast } from "./Toast";

type Status = "idle" | "saving" | "saved" | "error" | "recording";

export function CaptureBar() {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const typedAttemptRef = useRef<{
    rawText: string;
    idempotencyKey: string;
    capturedAt: string;
    sourceTimezone: string;
  } | null>(null);
  const toast = useToast();

  function captureTiming() {
    return {
      captured_at: new Date().toISOString(),
      source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      timestamp_origin: "client_supplied" as const,
    };
  }

  async function submitTyped() {
    const value = text.trim();
    if (!value) return;
    setStatus("saving");
    setErrorMessage(null);
    try {
      const attempt =
        typedAttemptRef.current?.rawText === value
          ? typedAttemptRef.current
          : {
              rawText: value,
              idempotencyKey: newIdempotencyKey(),
              capturedAt: new Date().toISOString(),
              sourceTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            };
      typedAttemptRef.current = attempt;
      await createCapture(
        {
          source_type: "typed",
          raw_text: value,
          captured_at: attempt.capturedAt,
          source_timezone: attempt.sourceTimezone,
          timestamp_origin: "client_supplied",
        },
        attempt.idempotencyKey,
      );
      typedAttemptRef.current = null;
      setStatus("saved");
      setText("");
      toast.push("Saved — awaiting processing. Find it in Inbox.", "success");
      setTimeout(() => setStatus("idle"), 1800);
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof ApiError ? err.message : "Could not save. Check your connection.");
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (blob.size === 0) {
          setStatus("idle");
          return;
        }
        setStatus("saving");
        try {
          const ext = blob.type.includes("webm") ? "webm" : "ogg";
          const file = new File([blob], `capture-${Date.now()}.${ext}`, { type: blob.type });
          const asset = await uploadAsset(file);
          await createCapture({ source_type: "audio", asset_ids: [asset.id], ...captureTiming() });
          setStatus("saved");
          toast.push("Saved — awaiting processing. Find it in Inbox.", "success");
          setTimeout(() => setStatus("idle"), 1800);
        } catch (err) {
          setStatus("error");
          setErrorMessage(err instanceof ApiError ? err.message : "Could not save the recording.");
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setStatus("recording");
    } catch {
      toast.push("Microphone access was denied or is unavailable.", "error");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  const busy = status === "saving";

  return (
    <div className="pointer-events-none fixed inset-y-auto bottom-0 left-[240px] right-0 z-40 flex justify-center pb-6">
      <div className="pointer-events-auto flex w-full max-w-[760px] flex-col gap-1.5 px-10">
        {status === "error" && errorMessage && (
          <div className="flex items-center justify-between rounded-md border border-danger bg-danger-soft px-3 py-1.5 text-[12.5px] text-danger">
            <span>{errorMessage} Your text was kept.</span>
            <button className="font-medium underline" onClick={submitTyped}>
              Retry
            </button>
          </div>
        )}
        <div className="flex items-center gap-2 rounded-lg border border-hairline bg-paper-soft px-3.5 py-2.5">
          <span className="flex-none text-[13px] text-ink-muted">›</span>
          <input
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              typedAttemptRef.current = null;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitTyped();
              }
            }}
            placeholder={status === "recording" ? "Recording…" : "Talk or type…"}
            disabled={busy || status === "recording"}
            aria-label="Capture text"
            className="min-w-0 flex-1 border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
          />
          {status === "recording" ? (
            <button
              type="button"
              onClick={stopRecording}
              aria-label="Stop recording"
              className="flex h-6 w-6 flex-none items-center justify-center rounded border border-danger text-danger"
            >
              <Square size={11} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={startRecording}
              aria-label="Record audio"
              disabled={busy}
              className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-faint hover:text-ink disabled:opacity-40"
            >
              <Mic size={14} />
            </button>
          )}
          <button
            type="button"
            onClick={submitTyped}
            disabled={busy || !text.trim()}
            aria-label="Save capture"
            className="flex h-6 w-6 flex-none items-center justify-center rounded border border-hairline text-ink-muted disabled:opacity-30"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <CornerDownLeft size={13} />}
          </button>
        </div>
      </div>
    </div>
  );
}
