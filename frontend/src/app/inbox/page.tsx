"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import { Archive as ArchiveIcon } from "lucide-react";
import { archiveItem, getInbox } from "@/lib/traceback";
import { ApiError, Item } from "@/lib/types";
import { ItemRow } from "@/components/ItemRow";
import { MoveToSelect } from "@/components/MoveToSelect";
import { CaptureCard } from "@/components/CaptureCard";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";

function ArchiveItemButton({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function handleArchive() {
    setBusy(true);
    try {
      await archiveItem(item.id, item.version);
      onChanged();
      toast.push("Archived.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not archive.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={handleArchive}
      disabled={busy}
      aria-label={`Archive ${item.title}`}
      className="flex items-center gap-1 rounded border border-hairline px-2 py-1 text-[11.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy disabled:opacity-50"
    >
      <ArchiveIcon size={12} /> archive
    </button>
  );
}

function InboxPageInner() {
  const { data, error, isLoading, mutate } = useSWR("inbox", () => getInbox());
  const { openId, open, close } = useDetailPanel();

  const items = data?.items ?? [];
  const captures = data?.captures ?? [];
  const isEmpty = !isLoading && !error && items.length === 0 && captures.length === 0;

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="anything we're not sure where to file"
        title="Inbox"
        description="Confirm a suggestion, pick another folder, or start a note."
      />
      {isLoading && <LoadingState label="Loading Inbox…" />}
      {error && <ErrorState message="Could not load Inbox." onRetry={() => mutate()} />}
      {isEmpty && <EmptyState title="Nothing awaiting attention." />}

      {captures.length > 0 && (
        <div className="mb-6">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-faint">unsorted captures</div>
          {captures.map((c) => (
            <CaptureCard key={c.id} capture={c} onChanged={() => mutate()} />
          ))}
        </div>
      )}

      {items.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-faint">unclassified items</div>
          {items.map((item) => (
            <div key={item.id} className="flex items-center gap-2">
              <div className="flex-1">
                <ItemRow item={item} onOpenTask={open} />
              </div>
              <MoveToSelect item={item} onMoved={() => mutate()} />
              <ArchiveItemButton item={item} onChanged={() => mutate()} />
            </div>
          ))}
        </div>
      )}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense>
      <InboxPageInner />
    </Suspense>
  );
}
