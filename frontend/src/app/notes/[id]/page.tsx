"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { marked } from "marked";
import { ArrowLeft, Archive as ArchiveIcon, ArchiveRestore, Trash2, History } from "lucide-react";
import { archiveItem, deleteItemPermanently, getItem, moveItem, patchItem, restoreItem } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { RelationsSection } from "@/components/RelationsSection";
import { HistoryList } from "@/components/HistoryList";
import { LoadingState, ErrorState } from "@/components/StateViews";

function parentIdOf(item: Item): string | undefined {
  return item.relations.find((relation) => relation.relation === "part_of" && relation.from_item_id === item.id)?.to_item_id;
}

async function loadAncestors(item: Item): Promise<Item[]> {
  const ancestors: Item[] = [];
  const seen = new Set([item.id]);
  let parentId = parentIdOf(item);
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = await getItem(parentId);
    ancestors.unshift(parent);
    parentId = parentIdOf(parent);
  }
  return ancestors;
}

function itemLocation(item: Item): string {
  return item.item_type === "project" ? `/projects/${item.id}` : `/folders/${item.id}`;
}

export default function NoteDetailPage() {
  const params = useParams<{ id: string }>();
  const noteId = params.id;
  const router = useRouter();
  const toast = useToast();
  const { categories, isLoading: categoriesLoading } = useCategories();
  const { mutate: globalMutate } = useSWRConfig();

  const { data: item, error, isLoading, mutate } = useSWR<Item>(`item:${noteId}`, () => getItem(noteId));
  const { data: ancestors, error: pathError, isLoading: pathLoading, mutate: retryPath } = useSWR(
    item ? `note-ancestors:${item.id}:${item.version}` : null,
    () => loadAncestors(item!),
  );

  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadedId, setLoadedId] = useState<string | null>(null);

  if (item && loadedId !== item.id) {
    setTitle(item.title);
    setContent(item.content_md);
    setLoadedId(item.id);
  }

  const html = useMemo(
    () => (item ? marked.parse(item.content_md || "*Nothing here yet — switch to Edit to start writing.*") : ""),
    [item],
  );

  function refreshLists() {
    globalMutate(() => true, undefined, { revalidate: true });
  }

  async function saveField(patch: Record<string, unknown>) {
    if (!item) return;
    setSaving(true);
    try {
      const updated = await patchItem(item.id, { expected_version: item.version, ...patch });
      await mutate(updated);
      refreshLists();
      setConflict(false);
    } catch (err) {
      if (err instanceof ApiError && err.isVersionConflict) {
        setConflict(true);
        toast.push("This note changed elsewhere. Reload before saving again.", "error");
      } else {
        toast.push(err instanceof ApiError ? err.message : "Save failed.", "error");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleMove(categoryId: string) {
    if (!item) return;
    setBusy(true);
    try {
      const updated = categoryId
        ? await moveItem(item.id, { expected_version: item.version, category_id: categoryId })
        : await moveItem(item.id, { expected_version: item.version, inbox: true });
      await mutate(updated);
      refreshLists();
      toast.push("Moved.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Move failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    if (!item) return;
    setBusy(true);
    try {
      const updated = item.archived_at ? await restoreItem(item.id, item.version) : await archiveItem(item.id, item.version);
      await mutate(updated);
      refreshLists();
      toast.push(item.archived_at ? "Restored." : "Archived. Linked items remain available.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Action failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeletePermanently() {
    if (!item) return;
    if (!confirm(`Permanently delete "${item.title}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteItemPermanently(item.id, item.version);
      refreshLists();
      toast.push("Deleted permanently.", "success");
      router.push("/inbox");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not delete.", "error");
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return <div className="mx-auto max-w-[760px] px-10 py-10"><LoadingState label="Loading note…" /></div>;
  if (error || !item) return <div className="mx-auto max-w-[760px] px-10 py-10"><ErrorState message="Could not load this note." onRetry={() => mutate()} /></div>;

  const category = categories.find((entry) => entry.id === item.category_id);
  const locations = [
    { label: category?.name ?? "Inbox", href: category ? `/category/${category.slug}` : "/inbox" },
    ...(ancestors ?? []).map((ancestor) => ({ label: ancestor.title, href: itemLocation(ancestor) })),
  ];
  const parentLocation = locations[locations.length - 1];
  const locationLoading = pathLoading || (Boolean(item.category_id) && categoriesLoading);

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <div className="mb-3 flex items-start justify-between gap-3">
        <nav aria-label="Note location" className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[12.5px] text-ink-faint">
          {!locationLoading && !pathError && (
            <>
              <Link href={parentLocation.href} aria-label={`Back to ${parentLocation.label}`} className="mr-1 hover:text-ink">
                <ArrowLeft size={13} />
              </Link>
              {locations.map((location) => (
                <span key={location.href} className="inline-flex items-center gap-1.5">
                  <Link href={location.href} className="hover:text-ink">{location.label}</Link>
                  <span aria-hidden="true">/</span>
                </span>
              ))}
              <span aria-current="page" className="text-ink">{item.title}</span>
            </>
          )}
          {locationLoading && <span>Loading location…</span>}
          {pathError && !locationLoading && (
            <button onClick={() => void retryPath()} className="hover:text-ink">Could not load location. Retry</button>
          )}
        </nav>
        <div className="flex gap-1">
          <button
            onClick={() => setMode("preview")}
            className={"rounded border px-3 py-1 text-[12px] " + (mode === "preview" ? "border-accent-navy text-accent-navy" : "border-hairline text-ink-muted")}
          >
            Preview
          </button>
          <button
            onClick={() => setMode("edit")}
            className={"rounded border px-3 py-1 text-[12px] " + (mode === "edit" ? "border-accent-navy text-accent-navy" : "border-hairline text-ink-muted")}
          >
            Edit
          </button>
        </div>
      </div>

      {conflict && (
        <div className="mb-4 rounded border border-accent-gold bg-accent-navy-soft px-3 py-2 text-[12.5px] text-ink">
          Someone (or something) else changed this note. Reload to see the latest before editing again.
          <button className="ml-2 font-medium text-accent-navy underline" onClick={() => mutate()}>
            Reload
          </button>
        </div>
      )}

      <div className="rounded border border-hairline bg-paper-soft px-6 py-5">
        <div className="mb-3 flex items-center justify-end text-[11px] text-ink-faint">
          {saving ? "saving…" : `updated ${new Date(item.updated_at).toLocaleString()}`}
        </div>

        {mode === "edit" ? (
          <>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title !== item.title && saveField({ title })}
              aria-label="Title"
              className="mb-3 w-full border-b border-hairline bg-transparent pb-2 font-serif text-[22px] font-semibold text-ink focus:outline-none"
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onBlur={() => content !== item.content_md && saveField({ content_md: content })}
              rows={16}
              aria-label="Content"
              placeholder="Start writing. Markdown, no other formatting."
              className="w-full resize-none border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
            />
          </>
        ) : (
          <>
            <h1 className="mb-3 border-b border-hairline pb-2 font-serif text-[22px] font-semibold text-ink">{item.title}</h1>
            <div
              className="note-markdown text-[13.5px] text-ink [&_a]:text-accent-navy [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:font-serif [&_h1]:text-[17px] [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:font-serif [&_h2]:text-[15.5px] [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-3 [&_h3]:font-serif [&_h3]:text-[14.5px] [&_h3]:font-semibold [&_li]:mb-1 [&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-3 [&_strong]:font-semibold [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-5"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </>
        )}
      </div>

      <div className="mt-6 flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] uppercase tracking-wide text-ink-faint">Category</label>
          <select
            value={item.category_id ?? ""}
            onChange={(e) => handleMove(e.target.value)}
            disabled={busy}
            className="w-full rounded border border-hairline bg-paper px-3 py-1.5 text-[13px] text-ink"
          >
            <option value="">Inbox (unclassified)</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>

        <RelationsSection item={item} onChanged={() => { mutate(); refreshLists(); }} />

        <div>
          <button
            onClick={() => setShowHistory((v) => !v)}
            className="flex items-center gap-2 text-[12px] text-ink-muted hover:text-ink"
          >
            <History size={13} /> {showHistory ? "hide history" : "show history"}
          </button>
          {showHistory && <div className="mt-2"><HistoryList itemId={item.id} /></div>}
        </div>

        <div className="flex flex-wrap gap-2 border-t border-hairline pt-4">
          <button
            onClick={handleArchive}
            disabled={busy}
            className="flex items-center gap-1.5 rounded border border-hairline px-3 py-1.5 text-[12px] text-ink-muted hover:text-ink disabled:opacity-50"
          >
            {item.archived_at ? <ArchiveRestore size={13} /> : <ArchiveIcon size={13} />}
            {item.archived_at ? "Restore" : "Archive"}
          </button>
          {item.archived_at && (
            <button
              onClick={handleDeletePermanently}
              disabled={busy}
              className="flex items-center gap-1.5 rounded border border-danger px-3 py-1.5 text-[12px] text-danger disabled:opacity-50"
            >
              <Trash2 size={13} /> Delete permanently
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
