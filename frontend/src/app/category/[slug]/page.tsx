"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Search } from "lucide-react";
import { listItems } from "@/lib/traceback";
import { useCategories, categoryBySlug } from "@/lib/useCategories";
import { CATEGORY_LABELS, CategorySlug } from "@/lib/traceback";
import { ItemRow } from "@/components/ItemRow";
import { FolderTree } from "@/components/FolderTree";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { PageHeader } from "@/components/PageHeader";
import { useUrlParameter } from "@/lib/useUrlParameter";

function CategoryPageInner() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug as CategorySlug;
  const { categories, isLoading: categoriesLoading } = useCategories();
  const category = categoryBySlug(categories, slug);
  const [query, setQuery] = useUrlParameter("q");
  const { openId, open, close } = useDetailPanel();

  const { data, error, isLoading } = useSWR(
    category && query ? `category-search:${category.id}:${query}` : null,
    category ? () => listItems({ category_id: category.id, q: query, limit: 100 }) : null,
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
        category && <FolderTree categoryId={category.id} parentId={null} />
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
