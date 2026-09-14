"use client";

import useSWR from "swr";
import { getHistory } from "@/lib/traceback";
import { Revision } from "@/lib/types";

export function HistoryList({ itemId }: { itemId: string }) {
  const { data, isLoading } = useSWR<{ items: Revision[] }>(`history:${itemId}`, () => getHistory(itemId));
  if (isLoading) return <div className="text-[12px] text-ink-faint">Loading history…</div>;
  if (!data || data.items.length === 0) return <div className="text-[12px] text-ink-faint">No revisions yet.</div>;
  return (
    <ul className="flex flex-col gap-1.5">
      {data.items.map((rev) => (
        <li key={rev.id} className="rounded border border-hairline px-2.5 py-1.5 text-[12px] text-ink-muted">
          v{rev.resulting_version} · {new Date(rev.created_at).toLocaleString()}
        </li>
      ))}
    </ul>
  );
}
