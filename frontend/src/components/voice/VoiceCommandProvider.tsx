"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Mic } from "lucide-react";
import { ApiError, Capture, VoiceCapabilities } from "@/lib/types";
import {
  LaunchOptions,
  NON_RETRYABLE_CODES,
  UploadAttempt,
  VOICE_MIN_MS,
  extensionFor,
  getCapabilities,
  newAttemptKey,
  pickRecorderMime,
  sha256Hex,
  uploadVoiceCapture,
} from "@/lib/voice";
import { createCapture, getCapture } from "@/lib/traceback";
import { useToast } from "../Toast";
import { CommandReviewCard } from "./CommandReviewCard";
import { ENTRY_LABEL } from "./voiceLabels";
import { RecorderState, VoiceContext, VoiceContextValue } from "./voiceContext";
import { PaletteView, VoicePalette } from "./VoicePalette";

export const SHORTCUT_LABEL = "⌥ Option + Space"; // matches the mockup and the native helper's default binding
const QUERY_POLL_MS = 500;
const QUERY_POLL_TIMEOUT_MS = 20_000;
const CONFIRM_DISMISS_MS = 2600;
const CANCELLED_DISMISS_MS = 1500;

/** Specific progress copy per the design system ("Finding tasks…," never "AI is thinking") —
 * a display-only guess from the transcript; the backend's own classification is authoritative
 * and may resolve differently once it responds. */
function progressLabelFor(transcript: string): string {
  const text = transcript.toLowerCase();
  if (text.includes("inbox")) return "Checking your inbox…";
  if (text.includes("overdue") || text.includes("task")) return "Finding tasks…";
  if (/^(open|go to|navigate to|take me to|switch to)\b/.test(text.trim())) return "Opening…";
  return "Finding matches…";
}

export { useVoice } from "./voiceContext";
export type { RecorderState } from "./voiceContext";

export const LOCK_NAME = "traceback-voice-recorder";

/** Hold the cross-tab recording lock until the returned release() is called; null if another tab holds it. */
function acquireLock(): Promise<(() => void) | null> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks) return Promise.resolve(() => undefined); // no Web Locks: the in-tab state machine is the only mutex
  return new Promise((resolve) => {
    locks
      .request(LOCK_NAME, { ifAvailable: true }, (lock) => {
        if (!lock) {
          resolve(null);
          return undefined;
        }
        return new Promise<void>((release) => resolve(() => release()));
      })
      .catch(() => resolve(null));
  });
}

/**
 * Owns the one recorder for the whole app: capability state, the recording state machine, the
 * retained blob + idempotency key for retries, and the tray of in-flight voice captures. Launch
 * buttons anywhere only call `start()`; they contain no recording, upload, or polling logic.
 */
export function VoiceCommandProvider({ children }: { children: React.ReactNode }) {
  const toast = useToast();
  const [capabilities, setCapabilities] = useState<VoiceCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState(false);
  const [state, setStateValue] = useState<RecorderState>("idle");
  const [active, setActive] = useState<LaunchOptions | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [unsentError, setUnsentError] = useState<{ message: string; retryable: boolean } | null>(null);
  const [tray, setTray] = useState<string[]>([]);
  const [overlay, setOverlayValue] = useState<PaletteView | null>(null);
  const [typing, setTyping] = useState(false);
  const router = useRouter();
  const overlayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTokenRef = useRef(0);
  const followupContextRef = useRef<string | null>(null);

  // The ref is the synchronous mutex (two clicks in one tick see the same value); state drives rendering.
  const stateRef = useRef<RecorderState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);
  const releaseLockRef = useRef<(() => void) | null>(null);
  const attemptRef = useRef<UploadAttempt | null>(null);
  const typedAttemptRef = useRef<{ text: string; key: string; capturedAt: string; sourceTimezone: string } | null>(null);
  const capsRef = useRef<VoiceCapabilities | null>(null);
  const activeRef = useRef<LaunchOptions | null>(null);

  const setState = useCallback((next: RecorderState) => {
    stateRef.current = next;
    setStateValue(next);
  }, []);

  const setOverlay = useCallback((next: PaletteView | null, autoDismissMs?: number) => {
    if (overlayTimerRef.current) {
      clearTimeout(overlayTimerRef.current);
      overlayTimerRef.current = null;
    }
    setOverlayValue(next);
    if (next && autoDismissMs) {
      overlayTimerRef.current = setTimeout(() => setOverlayValue(null), autoDismissMs);
    }
  }, []);

  const refreshCapabilities = useCallback(async () => {
    try {
      const value = (await getCapabilities()).voice_commands;
      capsRef.current = value;
      setCapabilities(value);
      setCapabilityError(false);
      return value;
    } catch {
      capsRef.current = null;
      setCapabilities(null);
      setCapabilityError(true);
      return null;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    getCapabilities()
      .then((value) => {
        if (!alive) return;
        capsRef.current = value.voice_commands;
        setCapabilities(value.voice_commands);
        setCapabilityError(false);
      })
      .catch(() => {
        if (!alive) return;
        capsRef.current = null;
        setCapabilityError(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const releaseLock = useCallback(() => {
    releaseLockRef.current?.();
    releaseLockRef.current = null;
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const finishIdle = useCallback(() => {
    stopTimer();
    stopStream();
    recorderRef.current = null;
    chunksRef.current = [];
    activeRef.current = null;
    setActive(null);
    setElapsedMs(0);
    setUnsentError(null);
    releaseLock();
    setState("idle");
  }, [releaseLock, setState, stopStream, stopTimer]);

  const trackCapture = useCallback((id: string) => {
    setTray((previous) => (previous.includes(id) ? previous : [id, ...previous]));
  }, []);

  const applyResolvedCapture = useCallback(
    (capture: Capture) => {
      const processing = capture.processing;
      if (processing.state === "awaiting_review") {
        // Write-command flow (create note/task): unchanged, handled entirely by the existing review tray.
        followupContextRef.current = null;
        setOverlay(null);
        trackCapture(capture.id);
        return;
      }
      if (processing.state === "resolved" && processing.query_result) {
        const result = processing.query_result;
        if (result.kind === "confirm" && result.confirm) {
          followupContextRef.current = null;
          router.push(result.confirm.route);
          setOverlay({ kind: "confirm", match: result.confirm }, CONFIRM_DISMISS_MS);
        } else if (result.kind === "ambiguous") {
          followupContextRef.current = capture.id;
          setOverlay({
            kind: "ambiguous",
            queryText: result.query_text ?? null,
            label: result.label ?? null,
            matches: result.matches ?? [],
            note: result.note ?? null,
          });
        } else if (result.kind === "no_results") {
          followupContextRef.current = null;
          setOverlay({ kind: "no_results", queryText: result.query_text ?? null, note: result.note ?? null });
        } else {
          followupContextRef.current = result.numbered ? capture.id : null;
          setOverlay({
            kind: "result",
            label: result.label ?? null,
            matches: result.matches ?? [],
            note: result.note ?? null,
            numbered: result.numbered,
            footerAction: result.footer_action ?? null,
          });
        }
        return;
      }
      if (processing.state === "failed") {
        followupContextRef.current = null;
        if (processing.error_code === "no_speech") {
          setOverlay({ kind: "no_results", queryText: null, note: "No speech was detected. Try again." }, 4000);
        } else {
          setOverlay({ kind: "unavailable", message: processing.error_message || "Something went wrong while processing your recording." });
        }
        return;
      }
      // Still pending/processing with no transcript yet: keep the spinner up, no query text.
      setOverlay({
        kind: "processing",
        queryText: processing.transcript ?? null,
        progressLabel: processing.transcript ? progressLabelFor(processing.transcript) : undefined,
      });
    },
    [router, setOverlay, trackCapture],
  );

  const pollCaptureForQuery = useCallback(
    (id: string) => {
      const token = ++pollTokenRef.current;
      const startedAt = Date.now();
      setOverlay({ kind: "processing", queryText: null });
      const tick = async () => {
        if (pollTokenRef.current !== token) return;
        let capture: Capture;
        try {
          capture = await getCapture(id);
        } catch {
          if (pollTokenRef.current !== token) return;
          setOverlay({ kind: "unavailable", message: "Could not reach the server to check on this command." });
          return;
        }
        if (pollTokenRef.current !== token) return;
        const { state } = capture.processing;
        if (state === "pending" || state === "processing") {
          if (capture.processing.transcript) {
            setOverlay({ kind: "processing", queryText: capture.processing.transcript, progressLabel: progressLabelFor(capture.processing.transcript) });
          }
          if (Date.now() - startedAt > QUERY_POLL_TIMEOUT_MS) {
            setOverlay({ kind: "unavailable", message: "Taking longer than expected. The background processor may not be running." });
            return;
          }
          setTimeout(() => void tick(), QUERY_POLL_MS);
          return;
        }
        applyResolvedCapture(capture);
      };
      void tick();
    },
    [applyResolvedCapture, setOverlay],
  );

  const submitTyped = useCallback(async (text: string) => {
    const attempt = typedAttemptRef.current?.text === text
      ? typedAttemptRef.current
      : {
          text,
          key: newAttemptKey(),
          capturedAt: new Date().toISOString(),
          sourceTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
    typedAttemptRef.current = attempt;
    const capture = await createCapture(
      {
        source_type: "typed",
        raw_text: text,
        captured_at: attempt.capturedAt,
        source_timezone: attempt.sourceTimezone,
        timestamp_origin: "client_supplied",
        metadata: { processing_profile: "voice_command", entry_point: "global" },
      },
      attempt.key,
    );
    typedAttemptRef.current = null;
    setTyping(false);
    pollCaptureForQuery(capture.id);
  }, [pollCaptureForQuery]);

  const upload = useCallback(
    async (attempt: UploadAttempt) => {
      setState("uploading");
      setUnsentError(null);
      try {
        const capture = await uploadVoiceCapture(attempt);
        attemptRef.current = null;
        finishIdle();
        pollCaptureForQuery(capture.id);
      } catch (err) {
        if (err instanceof ApiError && err.code === "duplicate_recording" && typeof err.details?.capture_id === "string") {
          // The server already has this exact recording; follow the existing capture instead of failing.
          attemptRef.current = null;
          const existing = err.details.capture_id;
          finishIdle();
          pollCaptureForQuery(existing);
          return;
        }
        const retryable = !(err instanceof ApiError && (NON_RETRYABLE_CODES.has(err.code) || (err.status >= 400 && err.status < 500 && ![401, 408, 409, 429].includes(err.status))));
        setUnsentError({
          message: err instanceof ApiError ? err.message : "Could not reach the server. Your recording is still here.",
          retryable,
        });
        setState("failed_unsent");
      }
    },
    [finishIdle, pollCaptureForQuery, setState],
  );

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (stateRef.current !== "recording" || !recorder) return;
    setState("stopping");
    stopTimer();
    recorder.onstop = () => {
      void (async () => {
        stopStream();
        const durationMs = Date.now() - startedAtRef.current;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (durationMs < VOICE_MIN_MS || blob.size === 0) {
          toast.push("Too short. Nothing was saved.", "info");
          finishIdle();
          return;
        }
        const options = activeRef.current ?? { entryPoint: "global" as const };
        const attempt: UploadAttempt = {
          ...options,
          blob,
          filename: `voice-${Date.now()}.${extensionFor(blob.type)}`,
          idempotencyKey: newAttemptKey(),
          sha256: await sha256Hex(blob),
          capturedAt: new Date(startedAtRef.current).toISOString(),
          sourceTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          durationMs,
        };
        attemptRef.current = attempt;
        await upload(attempt);
      })();
    };
    recorder.stop();
  }, [finishIdle, setState, stopStream, stopTimer, toast, upload]);

  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    if (stateRef.current !== "recording" || !recorder) return;
    recorder.onstop = null; // pre-upload cancel: nothing was sent, nothing is kept
    try {
      recorder.stop();
    } catch {
      // already stopped
    }
    finishIdle();
    setOverlay({ kind: "cancelled" }, CANCELLED_DISMISS_MS);
  }, [finishIdle, setOverlay]);

  const start = useCallback(
    async (options: LaunchOptions) => {
      if (stateRef.current !== "idle") {
        const current = activeRef.current ?? attemptRef.current;
        if (stateRef.current === "failed_unsent") {
          toast.push("Retry, save, or discard the unsent recording first.", "info");
        } else {
          toast.push(`Already recording (started from ${ENTRY_LABEL[current?.entryPoint ?? "global"] ?? "another surface"})`, "info");
        }
        document.getElementById("voice-recorder-dock")?.focus();
        return;
      }
      setOverlay(null);
      setTyping(false);
      setState("requesting_permission");
      const caps = await refreshCapabilities();
      if (!caps || !caps.enabled || !caps.accepts_audio) {
        setOverlay({
          kind: "unavailable",
          message: caps
            ? "Voice commands are turned off on this server."
            : "The local processor isn't running. Start Traceback's background service, or type your search instead.",
        });
        setState("idle");
        return;
      }
      if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
        setOverlay({ kind: "unavailable", message: "This browser can't record audio." });
        setState("idle");
        return;
      }
      const mime = pickRecorderMime(caps.accepted_mime_types, (candidate) => MediaRecorder.isTypeSupported(candidate));
      if (!mime) {
        setOverlay({ kind: "unavailable", message: "This browser records in a format the server doesn't accept." });
        setState("idle");
        return;
      }
      const release = await acquireLock();
      if (!release) {
        toast.push("Recording is active in another window.", "info");
        setState("idle");
        return;
      }
      releaseLockRef.current = release;
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setOverlay({ kind: "permission", message: "Grant microphone access in System Settings → Privacy & Security." });
        releaseLock();
        setState("idle");
        return;
      }
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, { mimeType: mime });
      chunksRef.current = [];
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorderRef.current = recorder;
      // A recording started while a numbered result/ambiguity list is still showing is a
      // follow-up ("the first one") to it, unless the caller already named an explicit context.
      const withFollowup: LaunchOptions = { ...options, contextualCaptureId: options.contextualCaptureId ?? followupContextRef.current ?? undefined };
      activeRef.current = withFollowup;
      setActive(withFollowup);
      stream.getAudioTracks().forEach((track) => track.addEventListener("ended", () => stop()));
      startedAtRef.current = Date.now();
      recorder.start();
      setElapsedMs(0);
      setState("recording");
      timerRef.current = setInterval(() => {
        const elapsed = Date.now() - startedAtRef.current;
        setElapsedMs(elapsed);
        if (elapsed >= (capsRef.current?.max_seconds ?? 60) * 1000) stop();
      }, 250);
    },
    [refreshCapabilities, releaseLock, setOverlay, setState, stop, toast],
  );

  const retry = useCallback(async () => {
    const attempt = attemptRef.current;
    if (attempt && stateRef.current === "failed_unsent") await upload(attempt); // identical key, bytes, and anchor
  }, [upload]);

  const saveToFile = useCallback(() => {
    const attempt = attemptRef.current;
    if (!attempt) return;
    const url = URL.createObjectURL(attempt.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = attempt.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, []);

  const discardUnsent = useCallback(() => {
    attemptRef.current = null;
    finishIdle();
  }, [finishIdle]);

  // Leaving while recording/uploading/unsent would lose audio; once the server acknowledged it, it is safe.
  useEffect(() => {
    if (state !== "recording" && state !== "uploading" && state !== "failed_unsent") return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [state]);

  useEffect(
    () => () => {
      // Provider unmount (not a route change: it lives in the root layout): release the mic and the lock.
      if (timerRef.current) clearInterval(timerRef.current);
      if (overlayTimerRef.current) clearTimeout(overlayTimerRef.current);
      pollTokenRef.current += 1; // stop any in-flight query poll from touching state after unmount
      streamRef.current?.getTracks().forEach((track) => track.stop());
      releaseLockRef.current?.();
    },
    [],
  );

  // In-app fallback for the configurable shortcut (default Option+Space): push-to-talk while the
  // Traceback tab itself is focused. The native macOS helper (see native/) covers system-wide
  // capture when Traceback isn't the focused app; both call the same loopback recording pipeline.
  useEffect(() => {
    function isTypingTarget(target: EventTarget | null): boolean {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.repeat) return;
      if (event.altKey && event.code === "Space" && !isTypingTarget(event.target)) {
        event.preventDefault();
        if (stateRef.current === "idle") void start({ entryPoint: "global" });
      } else if (event.key === "Escape" && stateRef.current === "recording") {
        cancel();
      }
    }
    function onKeyUp(event: KeyboardEvent) {
      if (event.code === "Space" && stateRef.current === "recording") stop();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [cancel, start, stop]);

  const disabledReason = useMemo(() => {
    if (capabilityError) return "Voice commands are unavailable (the server can't be reached)";
    if (capabilities && !capabilities.enabled) return "Voice commands are turned off on this server";
    if (capabilities && capabilities.low_disk) return null;
    return null;
  }, [capabilities, capabilityError]);

  const value = useMemo<VoiceContextValue>(
    () => ({ capabilities, disabledReason, state, activeEntry: active, start, stop, cancel, retry, saveToFile, discardUnsent, trackCapture, refreshCapabilities }),
    [capabilities, disabledReason, state, active, start, stop, cancel, retry, saveToFile, discardUnsent, trackCapture, refreshCapabilities],
  );

  let paletteView: PaletteView | null = overlay;
  if (!paletteView) {
    if (typing) {
      paletteView = { kind: "typing" };
    } else if (state === "recording") {
      paletteView = { kind: "recording", elapsedMs, maxMs: (capabilities?.max_seconds ?? 60) * 1000, shortcutLabel: SHORTCUT_LABEL };
    } else if (state === "idle" && capabilities?.enabled && !capabilityError) {
      paletteView = { kind: "idle", shortcutLabel: SHORTCUT_LABEL };
    }
  }

  return (
    <VoiceContext.Provider value={value}>
      {children}
      {paletteView && (
        <VoicePalette
          view={paletteView}
          onDismiss={() => setOverlay(null)}
          onSelect={(match) => {
            followupContextRef.current = null;
            setOverlay(null);
            router.push(match.route);
          }}
          onFooterAction={(action) => {
            setOverlay(null);
            router.push(action.route);
          }}
          onOpenSettings={() => {
            window.location.href = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone";
          }}
          onStartRecording={() => void start({ entryPoint: "global" })}
          onStartTyping={() => { setOverlay(null); setTyping(true); }}
          onCancelTyping={() => { typedAttemptRef.current = null; setTyping(false); }}
          onSubmitTyped={submitTyped}
          onStopRecording={stop}
          onCancelRecording={cancel}
        />
      )}
      {(state === "requesting_permission" || state === "failed_unsent") && (
        <div
          className="pointer-events-none fixed bottom-8 z-50"
          style={{ left: "calc(280px + max(0px, 50vw - 500px))", width: "min(680px, calc(100vw - 320px))" }}
        >
          <div
            id="voice-recorder-dock"
            role="region"
            aria-label="Voice recorder"
            tabIndex={-1}
            className="pointer-events-auto flex w-full items-center gap-3 rounded-lg border border-hairline bg-paper-soft px-4 py-2.5 text-[13px] shadow-sm"
          >
            {state === "requesting_permission" && (
              <>
                <Loader2 size={14} className="animate-spin" /> <span>Waiting for the microphone…</span>
              </>
            )}
            {state === "failed_unsent" && (
              <div className="flex flex-1 flex-col gap-1.5" role="alert">
                <span className="text-danger">{unsentError?.message ?? "The recording wasn't saved."} Your recording is still here.</span>
                <div className="flex gap-3 text-[12px]">
                  <button type="button" onClick={() => void retry()} disabled={!unsentError?.retryable} className="underline disabled:opacity-40">
                    Retry
                  </button>
                  <button type="button" onClick={saveToFile} className="underline">
                    Save recording to a file
                  </button>
                  <button type="button" onClick={discardUnsent} className="text-ink-faint underline">
                    Discard
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {tray.length > 0 && (
        <div className="fixed right-6 top-6 z-40 flex max-h-[80vh] w-[400px] flex-col gap-2 overflow-y-auto" aria-label="Voice captures">
          {tray.map((id) => (
            <TrayCard key={id} id={id} onDismiss={() => setTray((previous) => previous.filter((entry) => entry !== id))} />
          ))}
        </div>
      )}
    </VoiceContext.Provider>
  );
}

function TrayCard({ id, onDismiss }: { id: string; onDismiss: () => void }) {
  const [capture, setCapture] = useState<import("@/lib/types").Capture | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getCapture(id)
      .then((value) => !cancelled && setCapture(value))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id]);
  if (!capture) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-hairline bg-paper-soft p-3 text-[12.5px] text-ink-muted">
        <Mic size={13} /> <Loader2 size={12} className="animate-spin" /> Saved • transcribing
      </div>
    );
  }
  return <CommandReviewCard capture={capture} variant="tray" onChanged={() => undefined} onDismiss={onDismiss} />;
}
