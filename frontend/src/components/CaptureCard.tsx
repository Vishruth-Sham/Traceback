"use client";

import Link from "next/link";
import { Archive as ArchiveIcon, RotateCcw } from "lucide-react";
import { Capture, ApiError } from "@/lib/types";
import { archiveCapture, retryCapture } from "@/lib/traceback";
import { useToast } from "./Toast";
import { CommandReviewCard } from "./voice/CommandReviewCard";

const sourceLabel: Record<string, string> = {
  typed: "typed",
  audio: "voice memo",
  file: "file",
  url: "link",
  import: "import",
};

const stateLabel: Record<string, string> = {
  pending: "saved — awaiting processing",
  processing: "organizing…",
  awaiting_review: "needs review",
  failed: "processing failed — original is safe",
  resolved: "organized",
};

export function CaptureCard({ capture, onChanged }: { capture: Capture; onChanged: () => void }) {
  const toast = useToast();
  const preview = capture.raw_text || capture.original_description || capture.original_url || "(audio/file capture)";
  if (capture.metadata?.processing_profile === "voice_command") {
    // Voice commands share one review surface with the global tray; nothing is applied until the user acts.
    return (
      <div className="border-b border-hairline py-3">
        <CommandReviewCard capture={capture} variant="inbox" onChanged={onChanged} />
      </div>
    );
  }

  async function retry() {
    try {
      await retryCapture(capture.id, capture.version, capture.processing.generation);
      toast.push("Retrying processing.", "success");
      onChanged();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Retry failed.", "error");
    }
  }

  async function archive() {
    try {
      await archiveCapture(capture.id, capture.version);
      toast.push("Archived.", "success");
      onChanged();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not archive.", "error");
    }
  }

  const newNoteHref =
    `/notes/new?prefill=${encodeURIComponent(preview)}` +
    `&captureId=${capture.id}&captureVersion=${capture.version}&captureGeneration=${capture.processing.generation}` +
    `&returnTo=${encodeURIComponent("/inbox")}`;

  return (
    <div className="flex flex-col gap-2 border-b border-hairline py-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-ink-faint">
        <span>{sourceLabel[capture.source_type] ?? capture.source_type}</span>
        <span>·</span>
        <span>{new Date(capture.created_at).toLocaleString()}</span>
        <span>·</span>
        <span className={capture.processing.state === "failed" ? "font-semibold text-danger" : ""}>
          {stateLabel[capture.processing.state] ?? capture.processing.state}
        </span>
      </div>
      <div className="text-[13.5px] text-ink">&quot;{preview}&quot;</div>
      {capture.processing.state === "failed" && capture.processing.error_message && (
        <div className="text-[12px] text-danger">{capture.processing.error_message}</div>
      )}
      <div className="flex gap-2">
        <Link
          href={newNoteHref}
          className="rounded border border-hairline px-2.5 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy"
        >
          + new note
        </Link>
        {capture.processing.state === "failed" && (
          <button
            onClick={retry}
            className="flex items-center gap-1 rounded border border-hairline px-2.5 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy"
          >
            <RotateCcw size={11} /> retry
          </button>
        )}
        <button
          onClick={archive}
          className="flex items-center gap-1 rounded border border-hairline px-2.5 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy"
        >
          <ArchiveIcon size={11} /> archive
        </button>
      </div>
    </div>
  );
}
