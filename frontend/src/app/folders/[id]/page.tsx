"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft } from "lucide-react";
import { getItem, listItems } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { FolderTree } from "@/components/FolderTree";
import { ItemRow } from "@/components/ItemRow";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { ErrorState, LoadingState } from "@/components/StateViews";
import { PageHeader } from "@/components/PageHeader";
import { useDetailPanel } from "@/lib/useDetailPanel";

function FolderPageInner() {
  const { id } = useParams<{ id: string }>();
  const { categories } = useCategories();
  const { openId, open, close } = useDetailPanel();
  const { data: folder, error, isLoading, mutate } = useSWR(`folder:${id}`, () => getItem(id));
  const parentId = folder?.relations.find((relation) => relation.relation === "part_of" && relation.from_item_id === id)?.to_item_id;
  const { data: parent } = useSWR(parentId ? `folder-parent:${parentId}` : null, () => getItem(parentId!));
  const { data: tasks, mutate: mutateTasks } = useSWR(
    folder?.item_type === "folder" ? `folder-tasks:${id}` : null,
    () => listItems({ parent_id: id, item_type: "task", limit: 100 }),
  );

  if (isLoading) return <LoadingState label="Loading folder…" />;
  if (error || !folder || folder.item_type !== "folder") {
    return <ErrorState message="Could not load this folder." onRetry={() => void mutate()} />;
  }

  const category = categories.find((entry) => entry.id === folder.category_id);
  const backHref = parent
    ? parent.item_type === "project" ? `/projects/${parent.id}` : `/folders/${parent.id}`
    : category ? `/category/${category.slug}` : "/inbox";
  const backLabel = parent?.title ?? category?.name ?? "Inbox";

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <Link href={backHref} className="mb-4 flex items-center gap-1.5 text-[12px] text-ink-faint hover:text-ink">
        <ArrowLeft size={13} /> {backLabel}
      </Link>
      <PageHeader eyebrow="folder" title={folder.title} description="Folders and files in this location." />
      <FolderTree categoryId={folder.category_id ?? ""} parentId={folder.id} />

      {(tasks?.items.length ?? 0) > 0 && (
        <div className="mt-6 border-t border-hairline pt-4">
          <div className="mb-2 text-[11px] uppercase tracking-wide text-ink-faint">tasks in this folder</div>
          {tasks?.items.map((item) => <ItemRow key={item.id} item={item} onOpenTask={open} />)}
        </div>
      )}
      {openId && <ItemDetailPanel itemId={openId} onClose={() => { close(); void mutateTasks(); }} />}
    </div>
  );
}

export default function FolderPage() {
  return <Suspense><FolderPageInner /></Suspense>;
}
