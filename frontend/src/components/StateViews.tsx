"use client";

import { Loader2, AlertTriangle } from "lucide-react";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-[13px] text-ink-muted" role="status">
      <Loader2 size={14} className="animate-spin" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-2 py-10 text-[13px]" role="alert">
      <div className="flex items-center gap-2 text-danger">
        <AlertTriangle size={15} />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded border border-hairline px-3 py-1 text-ink-muted hover:text-ink"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-start gap-1 py-10">
      <div className="text-[13.5px] text-ink-muted">{title}</div>
      {hint && <div className="text-[12.5px] text-ink-faint">{hint}</div>}
    </div>
  );
}
