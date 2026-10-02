"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import { Loader2, Plus, Search } from "lucide-react";
import { createItem, listItems } from "@/lib/traceback";
import { useCategories, categoryBySlug } from "@/lib/useCategories";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import Link from "next/link";
import { useUrlParameter } from "@/lib/useUrlParameter";

const SWATCHES = ["#c1962f", "#2f3e68", "#3f5a3c", "#7a4a63", "#9a5a26"];

function swatchFor(id: string): string {
  let hash = 0;
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return SWATCHES[hash % SWATCHES.length];
}

function ProjectsPageInner() {
  const { categories } = useCategories();
  const projectsCategory = categoryBySlug(categories, "projects");
  const [query, setQuery] = useUrlParameter("q");
  const [adding, setAdding] = useState(false);
  const { data, error, isLoading, mutate } = useSWR(
    projectsCategory ? `projects:${projectsCategory.id}:${query}` : null,
    projectsCategory
      ? () => listItems({ item_type: "project", category_id: projectsCategory.id, q: query || undefined, limit: 100 })
      : null,
  );
  const { openId, open, close } = useDetailPanel();
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function createProject() {
    const value = title.trim();
    if (!value || !projectsCategory) return;
    setBusy(true);
    try {
      await createItem({ item_type: "project", title: value, category_id: projectsCategory.id });
      setTitle("");
      setAdding(false);
      mutate();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not create the project.", "error");
    } finally {
      setBusy(false);
    }
  }

  const count = data?.items.length ?? 0;

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="organized the way they live on disk"
        title="Projects"
        description="Group tasks and notes toward something you're building."
      />

      <div className="mb-4 flex divide-x divide-hairline rounded border border-hairline">
        <div className="flex-1 px-4 py-3">
          <div className="font-serif text-[20px] font-semibold text-ink">{count}</div>
          <div className="text-[11px] text-ink-faint">projects</div>
        </div>
      </div>

      <div className="mb-5 flex items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded border border-hairline px-3 py-1.5">
          <Search size={13} className="text-ink-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search…"
            className="flex-1 border-none bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
          />
        </div>
        <button
          onClick={() => setAdding((v) => !v)}
          className="flex items-center gap-1 rounded border border-hairline px-3 py-1.5 text-[12.5px] text-ink-muted hover:border-accent-navy hover:text-accent-navy"
        >
          <Plus size={13} /> New
        </button>
      </div>

      {adding && (
        <div className="mb-5 flex items-center gap-2.5 border-b border-hairline py-2.5">
          <span className="flex-none text-[13px] text-ink-faint">›</span>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createProject()}
            placeholder="New project name…"
            disabled={busy}
            aria-label="New project name"
            className="flex-1 border-none bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
          />
          {busy && <Loader2 size={13} className="animate-spin text-ink-faint" />}
        </div>
      )}

      {isLoading && <LoadingState />}
      {error && <ErrorState message="Could not load projects." onRetry={() => mutate()} />}
      {!isLoading && !error && data && data.items.length === 0 && (
        <EmptyState title="No projects yet." hint="Use + New above to create one." />
      )}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-hairline bg-hairline">
        {data?.items.map((item: Item) => (
          <div key={item.id} className="flex flex-col gap-2 bg-paper-soft px-4 py-3">
            <span className="h-3 w-3 rounded-[2px]" style={{ background: swatchFor(item.id) }} />
            <Link href={`/projects/${item.id}`} className="font-serif text-[15px] text-ink hover:underline">
              {item.title}
            </Link>
            <button
              onClick={() => open(item.id)}
              className="self-start text-[11px] text-ink-faint hover:text-accent-navy"
            >
              quick view
            </button>
          </div>
        ))}
      </div>

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsPageInner />
    </Suspense>
  );
}
