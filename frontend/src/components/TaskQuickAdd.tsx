"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Loader2, RotateCcw } from "lucide-react";
import { createCapture, getCapture, retryCapture } from "@/lib/traceback";
import { newIdempotencyKey } from "@/lib/apiClient";
import { ApiError, Capture } from "@/lib/types";
import { useToast } from "./Toast";

type PendingState = "saving" | "pending" | "processing" | "failed" | "submit_error";

interface PendingAdd {
  key: string;
  rawText: string;
  state: PendingState;
  captureId?: string;
  captureVersion?: number;
  captureGeneration?: number;
  errorMessage?: string;
  idempotencyKey: string;
  capturedAt: string;
  sourceTimezone: string;
}

const POLL_INTERVAL_MS = 1500;

const STATE_LABEL: Record<PendingState, string> = {
  saving: "saving…",
  pending: "saved — awaiting processing",
  processing: "organizing…",
  failed: "could not understand this — original text is safe",
  submit_error: "could not save — original text is safe",
};

function fromCapture(previous: PendingAdd, capture: Capture): PendingAdd {
  const state: PendingState = capture.processing.state === "processing" ? "processing" : capture.processing.state === "failed" ? "failed" : "pending";
  return {
    ...previous,
    captureVersion: capture.version,
    captureGeneration: capture.processing.generation,
    state,
    errorMessage: capture.processing.error_message ?? undefined,
  };
}

/**
 * The Tasks page's free-text add: the exact submitted text is persisted as an
 * immutable typed capture first, then the existing bounded local Ollama
 * runner (background process, not called from the browser) turns it into a
 * task. This component only submits and polls; it never talks to a model.
 */
export function TaskQuickAdd({ onTaskCreated }: { onTaskCreated: () => void }) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState<PendingAdd[]>([]);
  const toast = useToast();
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  useEffect(() => {
    const hasInFlight = pending.some((p) => p.state === "pending" || p.state === "processing");
    if (!hasInFlight) return;
    const interval = setInterval(async () => {
      const toCheck = pendingRef.current.filter((p) => (p.state === "pending" || p.state === "processing") && p.captureId);
      for (const entry of toCheck) {
        try {
          const capture = await getCapture(entry.captureId!);
          if (capture.processing.state === "resolved") {
            setPending((prev) => prev.filter((p) => p.key !== entry.key));
            onTaskCreated();
            toast.push("Task added.", "success");
          } else {
            setPending((prev) => prev.map((p) => (p.key === entry.key ? fromCapture(p, capture) : p)));
          }
        } catch {
          // Transient poll failure: leave the entry as-is and try again next tick.
        }
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [pending, onTaskCreated, toast]);

  async function submit(rawTextOverride?: string, existingKey?: string) {
    const value = (rawTextOverride ?? text).trim();
    if (!value) return;
    const key = existingKey ?? `${Date.now()}-${Math.random()}`;
    const existing = existingKey ? pendingRef.current.find((candidate) => candidate.key === key) : undefined;
    const idempotencyKey = existing?.idempotencyKey ?? newIdempotencyKey();
    const capturedAt = existing?.capturedAt ?? new Date().toISOString();
    const sourceTimezone = existing?.sourceTimezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!existingKey) {
      setPending((prev) => [{ key, rawText: value, state: "saving", idempotencyKey, capturedAt, sourceTimezone }, ...prev]);
      setText("");
    } else {
      setPending((prev) => prev.map((p) => (p.key === key ? { ...p, state: "saving", errorMessage: undefined } : p)));
    }
    try {
      const capture = await createCapture(
        {
          source_type: "typed",
          raw_text: value,
          captured_at: capturedAt,
          source_timezone: sourceTimezone,
          timestamp_origin: "client_supplied",
          metadata: { processing_profile: "task_quick_add" },
        },
        idempotencyKey,
      );
      setPending((prev) =>
        prev.map((p) =>
          p.key === key
            ? {
                ...p,
                state: "pending",
                captureId: capture.id,
                captureVersion: capture.version,
                captureGeneration: capture.processing.generation,
              }
            : p,
        ),
      );
    } catch (err) {
      setPending((prev) =>
        prev.map((p) =>
          p.key === key
            ? { ...p, state: "submit_error", errorMessage: err instanceof ApiError ? err.message : "Could not reach the server." }
            : p,
        ),
      );
    }
  }

  async function retry(entry: PendingAdd) {
    if (entry.state === "submit_error") {
      await submit(entry.rawText, entry.key);
      return;
    }
    if (!entry.captureId || entry.captureVersion === undefined || entry.captureGeneration === undefined) return;
    try {
      const capture = await retryCapture(entry.captureId, entry.captureVersion, entry.captureGeneration);
      setPending((prev) => prev.map((p) => (p.key === entry.key ? fromCapture(p, capture) : p)));
      toast.push("Retrying.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Retry failed.", "error");
    }
  }

  function dismiss(key: string) {
    setPending((prev) => prev.filter((p) => p.key !== key));
  }

  function manualResolveHref(entry: PendingAdd): string {
    const params = new URLSearchParams({ raw: entry.rawText });
    if (entry.captureId) params.set("captureId", entry.captureId);
    if (entry.captureVersion !== undefined) params.set("captureVersion", String(entry.captureVersion));
    if (entry.captureGeneration !== undefined) params.set("captureGeneration", String(entry.captureGeneration));
    return `/tasks/new?${params.toString()}`;
  }

  return (
    <div className="mb-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="mb-2 flex items-center gap-2 rounded border border-hairline bg-paper-soft px-3.5 py-2.5 focus-within:border-accent-navy"
      >
        <ArrowRight size={14} className="flex-none text-ink-faint" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a task… e.g. &quot;Email Sarah Friday afternoon about the apartment move&quot;"
          aria-label="Add a task"
          className="min-w-0 flex-1 border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className="flex-none rounded border border-hairline px-2.5 py-1 text-[12px] text-ink-muted hover:border-accent-navy hover:text-accent-navy disabled:opacity-30"
        >
          Add
        </button>
        <Link href="/tasks/new" className="flex-none text-[11.5px] text-ink-faint underline-offset-2 hover:text-ink hover:underline">
          add manually
        </Link>
      </form>

      {pending.map((entry) => (
        <div
          key={entry.key}
          className="mb-2 flex items-center justify-between gap-3 rounded border border-hairline bg-paper px-3.5 py-2 text-[12.5px]"
        >
          <div className="min-w-0 flex-1">
            <div className="truncate text-ink">&quot;{entry.rawText}&quot;</div>
            <div className={`mt-0.5 flex items-center gap-1.5 ${entry.state === "failed" || entry.state === "submit_error" ? "text-danger" : "text-ink-faint"}`}>
              {(entry.state === "saving" || entry.state === "processing") && <Loader2 size={11} className="animate-spin" />}
              <span>{STATE_LABEL[entry.state]}</span>
            </div>
          </div>
          {(entry.state === "failed" || entry.state === "submit_error") && (
            <div className="flex flex-none items-center gap-2">
              <button
                onClick={() => retry(entry)}
                className="flex items-center gap-1 rounded border border-hairline px-2 py-1 text-ink-muted hover:border-accent-navy hover:text-accent-navy"
              >
                <RotateCcw size={11} /> retry
              </button>
              <Link
                href={manualResolveHref(entry)}
                className="rounded border border-hairline px-2 py-1 text-ink-muted hover:border-accent-navy hover:text-accent-navy"
              >
                add manually
              </Link>
              <button onClick={() => dismiss(entry.key)} aria-label="Dismiss" className="p-1 text-ink-faint hover:text-ink">
                <Check size={12} />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
