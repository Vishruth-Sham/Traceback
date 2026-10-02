"use client";

import { Suspense } from "react";
import useSWR from "swr";
import { Search as SearchIcon } from "lucide-react";
import { listItems } from "@/lib/traceback";
import { ItemRow } from "@/components/ItemRow";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import { useUrlParameter } from "@/lib/useUrlParameter";

function SearchPageInner() {
  const [query, setQuery] = useUrlParameter("q");
  const { openId, open, close } = useDetailPanel();
  const { data, error, isLoading } = useSWR(
    query.trim().length > 1 ? `search:${query}` : null,
    () => listItems({ q: query, limit: 50 }),
  );

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader eyebrow="across everything" title="Search" />

      <div className="mb-4 flex items-center gap-2 rounded border border-hairline px-3 py-2">
        <SearchIcon size={14} className="text-ink-faint" />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search titles and notes across everything…"
          className="flex-1 border-none bg-transparent text-[14px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
      </div>

      {query.trim().length <= 1 && <EmptyState title="Type at least two characters to search." />}
      {isLoading && <LoadingState label="Searching…" />}
      {error && <ErrorState message="Search failed." />}
      {!isLoading && !error && data && data.items.length === 0 && query.trim().length > 1 && (
        <EmptyState title={`No matches for "${query}".`} />
      )}

      {data?.items.map((item) => (
        <ItemRow key={item.id} item={item} onOpenTask={open} />
      ))}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchPageInner />
    </Suspense>
  );
}
