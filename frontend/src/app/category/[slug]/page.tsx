"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { listItems } from "@/lib/traceback";
import { useCategories, categoryBySlug } from "@/lib/useCategories";
import { CATEGORY_LABELS, CategorySlug } from "@/lib/traceback";
import { ItemRow } from "@/components/ItemRow";
import { DEFAULT_SORT, FolderTree, SortSpec } from "@/components/FolderTree";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import { useUrlParameter } from "@/lib/useUrlParameter";

const SORT_OPTIONS: { value: SortSpec["sort"]; label: string }[] = [
  { value: "created_at", label: "Date created" },
  { value: "updated_at", label: "Date modified" },
  { value: "title", label: "Title" },
];

function CategoryPageInner() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug as CategorySlug;
  const { categories, isLoading: categoriesLoading } = useCategories();
  const category = categoryBySlug(categories, slug);
  const [query, setQuery] = useUrlParameter("q");
  const [sortParam, setSortParam] = useUrlParameter("sort", DEFAULT_SORT.sort);
  const [orderParam, setOrderParam] = useUrlParameter("order", DEFAULT_SORT.order);
  const sortSpec: SortSpec = {
    sort: SORT_OPTIONS.some((o) => o.value === sortParam) ? (sortParam as SortSpec["sort"]) : DEFAULT_SORT.sort,
    order: orderParam === "desc" ? "desc" : "asc",
  };
  const { openId, open, close } = useDetailPanel();

  const { data, error, isLoading } = useSWR(
    category && query ? `category-search:${category.id}:${query}:${sortSpec.sort}:${sortSpec.order}` : null,
    category ? () => listItems({ category_id: category.id, q: query, ...sortSpec, limit: 100 }) : null,
  );

  const label = CATEGORY_LABELS[slug] ?? "Category";
  const searching = query.trim().length > 0;

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="filed here"
        title={label}
        description="Folders and files, organized however you'd like."
      />

      <div className="mb-4 flex items-center gap-2 rounded border border-hairline px-3 py-1.5">
        <Search size={13} className="text-ink-faint" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search…"
          className="flex-1 border-none bg-transparent text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
      </div>

      <div className="mb-4 flex items-center gap-2 text-[12px] text-ink-muted">
        <label htmlFor="sort-by">Sort by</label>
        <select
          id="sort-by"
          value={sortSpec.sort}
          onChange={(e) => setSortParam(e.target.value)}
          className="rounded border border-hairline bg-transparent px-2 py-1 text-[12px] text-ink"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setOrderParam(sortSpec.order === "asc" ? "desc" : "asc")}
          aria-label={sortSpec.order === "asc" ? "Ascending, switch to descending" : "Descending, switch to ascending"}
          title={sortSpec.order === "asc" ? "Ascending" : "Descending"}
          className="flex items-center gap-1 rounded border border-hairline px-2 py-1 hover:border-accent-navy hover:text-accent-navy"
        >
          {sortSpec.order === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />}
          {sortSpec.order === "asc" ? "asc" : "desc"}
        </button>
      </div>

      {categoriesLoading && <LoadingState />}

      {searching ? (
        <>
          {isLoading && <LoadingState />}
          {error && <ErrorState message="Search failed." />}
          {!isLoading && !error && data && data.items.length === 0 && (
            <EmptyState title={`No matches for "${query}".`} />
          )}
          {data?.items.map((item) => (
            <ItemRow key={item.id} item={item} onOpenTask={open} />
          ))}
        </>
      ) : (
        category && <FolderTree categoryId={category.id} parentId={null} sortSpec={sortSpec} />
      )}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

export default function CategoryPage() {
  return (
    <Suspense>
      <CategoryPageInner />
    </Suspense>
  );
}
