"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Loader2, RotateCcw, Undo2 } from "lucide-react";
import { createCapture, getCapture, getItem, retryCapture, undoCaptureFiling } from "@/lib/traceback";
import { newIdempotencyKey } from "@/lib/apiClient";
import { ApiError, Capture } from "@/lib/types";
import { useToast } from "./Toast";

type EntryState = "saving" | "pending" | "processing" | "filed" | "failed" | "undone" | "submit_error";

interface Entry {
  key: string;
  rawText: string;
  state: EntryState;
  capture?: Capture;
  filed?: { type: string; title: string }[];
  errorMessage?: string;
  idempotencyKey: string;
  capturedAt: string;
  sourceTimezone: string;
}

const POLL_INTERVAL_MS = 1500;

const STATE_LABEL: Record<EntryState, string> = {
  saving: "saving…",
  pending: "saved — waiting to be filed",
  processing: "filing…",
  filed: "filed",
  failed: "could not file this — original text is safe",
  undone: "filing undone — it is in Inbox below",
  submit_error: "could not save — original text is safe",
};

/**
 * Add anything: the exact text becomes a general capture, the processor
 * works out what it is and files it, and this box shows a receipt of what
 * happened with one Undo for the whole filing. It never talks to a model.
 */
export function CaptureBox({ onChanged }: { onChanged?: () => void }) {
  const [text, setText] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const toast = useToast();
  const entriesRef = useRef(entries);
  useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  function update(key: string, patch: Partial<Entry>) {
    setEntries((prev) => prev.map((entry) => (entry.key === key ? { ...entry, ...patch } : entry)));
  }

  useEffect(() => {
    const inFlight = entries.some((entry) => (entry.state === "pending" || entry.state === "processing") && entry.capture);
    if (!inFlight) return;
    const interval = setInterval(async () => {
      for (const entry of entriesRef.current) {
        if (!(entry.state === "pending" || entry.state === "processing") || !entry.capture) continue;
        try {
          const capture = await getCapture(entry.capture.id);
          const state = capture.processing.state;
          if (state === "resolved") {
            const items = await Promise.all(capture.resulting_item_ids.map((id) => getItem(id).catch(() => null)));
            const filed = items.filter((item) => item !== null).map((item) => ({ type: item.item_type, title: item.title }));
            update(entry.key, { state: "filed", capture, filed });
            onChanged?.();
          } else {
            update(entry.key, {
              capture,
              state: state === "processing" ? "processing" : state === "pending" ? "pending" : "failed",
              errorMessage: capture.processing.error_message ?? undefined,
            });
            if (state === "failed" || state === "awaiting_review") onChanged?.();
          }
        } catch {
          // Transient poll failure: try again next tick.
        }
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [entries, onChanged]);

  async function submit(rawTextOverride?: string, existingKey?: string) {
    const value = (rawTextOverride ?? text).trim();
    if (!value) return;
    const key = existingKey ?? `${Date.now()}-${Math.random()}`;
    const existing = existingKey ? entriesRef.current.find((entry) => entry.key === key) : undefined;
    const idempotencyKey = existing?.idempotencyKey ?? newIdempotencyKey();
    const capturedAt = existing?.capturedAt ?? new Date().toISOString();
    const sourceTimezone = existing?.sourceTimezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!existingKey) {
      setEntries((prev) => [{ key, rawText: value, state: "saving", idempotencyKey, capturedAt, sourceTimezone }, ...prev]);
      setText("");
    } else {
      update(key, { state: "saving", errorMessage: undefined });
    }
    try {
      const capture = await createCapture(
        {
          source_type: "typed",
          raw_text: value,
          captured_at: capturedAt,
          source_timezone: sourceTimezone,
          timestamp_origin: "client_supplied",
        },
        idempotencyKey,
      );
      update(key, { state: "pending", capture });
    } catch (err) {
      update(key, { state: "submit_error", errorMessage: err instanceof ApiError ? err.message : "Could not reach the server." });
    }
  }

  async function undo(entry: Entry) {
    if (!entry.capture) return;
    try {
      const result = await undoCaptureFiling(entry.capture.id, entry.capture.version);
      update(entry.key, { state: "undone", capture: result.capture });
      toast.push("Filing undone.", "success");
      onChanged?.();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not undo.", "error");
    }
  }

  async function retry(entry: Entry) {
    if (entry.state === "submit_error" || !entry.capture) {
      await submit(entry.rawText, entry.key);
      return;
    }
    try {
      const capture = await retryCapture(entry.capture.id, entry.capture.version, entry.capture.processing.generation);
      update(entry.key, { state: "pending", capture, errorMessage: undefined });
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Retry failed.", "error");
    }
  }

  function dismiss(key: string) {
    setEntries((prev) => prev.filter((entry) => entry.key !== key));
  }

  return (
    <div className="mb-6">
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
          placeholder="Add anything… it gets filed for you"
          aria-label="Add anything"
          className="min-w-0 flex-1 border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <button
          type="submit"
          disabled={!text.trim()}
          className="flex-none rounded border border-hairline px-2.5 py-1 text-[12px] text-ink-muted hover:border-accent-navy hover:text-accent-navy disabled:opacity-30"
        >
          Add
        </button>
      </form>

      {entries.map((entry) => {
        const bad = entry.state === "failed" || entry.state === "submit_error";
        return (
          <div key={entry.key} className="mb-2 rounded border border-hairline bg-paper px-3.5 py-2 text-[12.5px]">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-ink">&quot;{entry.rawText}&quot;</div>
                <div className={`mt-0.5 flex items-center gap-1.5 ${bad ? "text-danger" : "text-ink-faint"}`}>
                  {(entry.state === "saving" || entry.state === "processing") && <Loader2 size={11} className="animate-spin" />}
                  <span>{STATE_LABEL[entry.state]}</span>
                  {bad && entry.errorMessage && <span>· {entry.errorMessage}</span>}
                </div>
              </div>
              <div className="flex flex-none items-center gap-2">
                {entry.state === "filed" && (
                  <button
                    onClick={() => undo(entry)}
                    className="flex items-center gap-1 rounded border border-hairline px-2 py-1 text-ink-muted hover:border-accent-navy hover:text-accent-navy"
                  >
                    <Undo2 size={11} /> undo
                  </button>
                )}
                {bad && (
                  <button
                    onClick={() => retry(entry)}
                    className="flex items-center gap-1 rounded border border-hairline px-2 py-1 text-ink-muted hover:border-accent-navy hover:text-accent-navy"
                  >
                    <RotateCcw size={11} /> retry
                  </button>
                )}
                {(entry.state === "filed" || entry.state === "undone" || bad) && (
                  <button onClick={() => dismiss(entry.key)} aria-label="Dismiss" className="p-1 text-ink-faint hover:text-ink">
                    <Check size={12} />
                  </button>
                )}
              </div>
            </div>
            {entry.state === "filed" && entry.filed && entry.filed.length > 0 && (
              <ul className="mt-1.5 flex flex-col gap-0.5 text-ink-muted">
                {entry.filed.map((item, index) => (
                  <li key={index}>
                    <span className="text-ink-faint">{item.type}</span> · {item.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
