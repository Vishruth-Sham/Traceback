"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { ArchiveRestore, Trash2 } from "lucide-react";
import {
  deleteCapturePermanently,
  deleteItemPermanently,
  listCaptures,
  listItems,
  restoreCapture,
  restoreItem,
} from "@/lib/traceback";
import { ApiError, Capture, Item } from "@/lib/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { useToast } from "@/components/Toast";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import { Segmented } from "@/components/Segmented";

const typeLabel: Record<string, string> = { note: "note", task: "task", project: "project" };

function ArchivedItemRow({ item, onChanged, onOpenTask }: { item: Item; onChanged: () => void; onOpenTask: (id: string) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function restore() {
    setBusy(true);
    try {
      await restoreItem(item.id, item.version);
      onChanged();
      toast.push("Restored.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Restore failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function del() {
    if (!confirm(`Permanently delete "${item.title}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteItemPermanently(item.id, item.version);
      onChanged();
      toast.push("Deleted permanently.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not delete — unlink related items first.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3 border-b border-hairline py-2.5">
      <span className="w-12 flex-none text-[10.5px] uppercase tracking-wide text-ink-faint">
        {typeLabel[item.item_type]}
      </span>
      {item.item_type === "note" ? (
        <Link href={`/notes/${item.id}`} className="flex-1 truncate text-left font-serif text-[14px] text-ink hover:underline">
          {item.title}
        </Link>
      ) : item.item_type === "project" ? (
        <Link href={`/projects/${item.id}`} className="flex-1 truncate text-left font-serif text-[14px] text-ink hover:underline">
          {item.title}
        </Link>
      ) : (
        <button onClick={() => onOpenTask(item.id)} className="flex-1 truncate text-left font-serif text-[14px] text-ink hover:underline">
          {item.title}
        </button>
      )}
      <button
        onClick={restore}
        disabled={busy}
        className="flex items-center gap-1 rounded border border-hairline px-2.5 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy disabled:opacity-50"
      >
        <ArchiveRestore size={12} /> restore
      </button>
      <button
        onClick={del}
        disabled={busy}
        className="flex items-center gap-1 rounded border border-danger px-2.5 py-1 text-[11.5px] text-danger disabled:opacity-50"
      >
        <Trash2 size={12} /> delete
      </button>
    </div>
  );
}

function ArchivedCaptureRow({ capture, onChanged }: { capture: Capture; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const preview = capture.raw_text || capture.original_description || capture.original_url || "(audio/file capture)";

  async function restore() {
    setBusy(true);
    try {
      await restoreCapture(capture.id, capture.version);
      onChanged();
      toast.push("Restored.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Restore failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function del() {
    if (!confirm("Permanently delete this capture? This cannot be undone.")) return;
    setBusy(true);
    try {
      await deleteCapturePermanently(capture.id, capture.version);
      onChanged();
      toast.push("Deleted permanently.", "success");
    } catch (err) {
      toast.push(
        err instanceof ApiError ? err.message : "Could not delete — a linked item still references this capture.",
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3 border-b border-hairline py-2.5">
      <span className="flex-1 truncate text-[13.5px] text-ink">&quot;{preview}&quot;</span>
      <button
        onClick={restore}
        disabled={busy}
        className="flex items-center gap-1 rounded border border-hairline px-2.5 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy disabled:opacity-50"
      >
        <ArchiveRestore size={12} /> restore
      </button>
      <button
        onClick={del}
        disabled={busy}
        className="flex items-center gap-1 rounded border border-danger px-2.5 py-1 text-[11.5px] text-danger disabled:opacity-50"
      >
        <Trash2 size={12} /> delete
      </button>
    </div>
  );
}

function ArchivePageInner() {
  const [tab, setTab] = useState<"items" | "captures">("items");
  const { openId, open, close } = useDetailPanel();

  const {
    data: itemsData,
    error: itemsError,
    isLoading: itemsLoading,
    mutate: mutateItems,
  } = useSWR("archived-items", () => listItems({ archived: true, limit: 100 }));

  const {
    data: capturesData,
    error: capturesError,
    isLoading: capturesLoading,
    mutate: mutateCaptures,
  } = useSWR("archived-captures", () => listCaptures({ archived: true }));

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="restore, or delete for good"
        title="Archive"
        description="Archiving a project keeps its tasks available elsewhere. Completion is separate from archiving."
      />

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "items", label: "items" },
          { value: "captures", label: "captures" },
        ]}
      />

      {tab === "items" && (
        <>
          {itemsLoading && <LoadingState />}
          {itemsError && <ErrorState message="Could not load archived items." onRetry={() => mutateItems()} />}
          {!itemsLoading && !itemsError && itemsData && itemsData.items.length === 0 && (
            <EmptyState title="Nothing archived." />
          )}
          {itemsData?.items.map((item) => (
            <ArchivedItemRow key={item.id} item={item} onChanged={() => mutateItems()} onOpenTask={open} />
          ))}
        </>
      )}

      {tab === "captures" && (
        <>
          {capturesLoading && <LoadingState />}
          {capturesError && <ErrorState message="Could not load archived captures." onRetry={() => mutateCaptures()} />}
          {!capturesLoading && !capturesError && capturesData && capturesData.items.length === 0 && (
            <EmptyState title="No archived captures." />
          )}
          {capturesData?.items.map((c) => (
            <ArchivedCaptureRow key={c.id} capture={c} onChanged={() => mutateCaptures()} />
          ))}
        </>
      )}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

export default function ArchivePage() {
  return (
    <Suspense>
      <ArchivePageInner />
    </Suspense>
  );
}
