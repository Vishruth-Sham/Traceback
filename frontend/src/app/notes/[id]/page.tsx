"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { ArrowLeft, Archive as ArchiveIcon, ArchiveRestore, Trash2, History, ImagePlus } from "lucide-react";
import { archiveItem, deleteItemPermanently, getItem, linkNoteImage, moveItem, patchItem, restoreItem, uploadAsset } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { RelationsSection } from "@/components/RelationsSection";
import { HistoryList } from "@/components/HistoryList";
import { NoteMarkdown } from "@/components/NoteMarkdown";
import { NoteImages } from "@/components/NoteImages";
import { LoadingState, ErrorState } from "@/components/StateViews";
import { imageMarkdown, insertAtSelection, validNoteImage } from "@/lib/noteImages";

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
  const editor = useRef<HTMLTextAreaElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const pendingSave = useRef<Promise<void> | null>(null);

  if (item && loadedId !== item.id) {
    setTitle(item.title);
    setContent(item.content_md);
    setLoadedId(item.id);
  }

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

  async function insertImages(files: FileList | null) {
    if (!item || !files?.length) return;
    const selected = Array.from(files);
    if (selected.some((file) => !validNoteImage(file))) {
      toast.push("Choose PNG, JPEG, GIF, WebP, or AVIF images up to 20 MB each.", "error");
      return;
    }
    const draft = content;
    const start = editor.current?.selectionStart ?? draft.length;
    const end = editor.current?.selectionEnd ?? start;
    setBusy(true);
    try {
      await pendingSave.current;
      const fresh = await getItem(item.id);
      if (fresh.content_md !== draft) {
        setConflict(true);
        toast.push("This note changed elsewhere. Reload before inserting an image.", "error");
        return;
      }
      let version = fresh.version;
      const markup: string[] = [];
      for (const file of selected) {
        const uploaded = await uploadAsset(file);
        const linked = await linkNoteImage(item.id, uploaded.id, version);
        version = linked.version;
        markup.push(imageMarkdown(uploaded.id, file.name));
      }
      const inserted = insertAtSelection(draft, markup.join("\n\n"), start, end);
      const updated = await patchItem(item.id, { expected_version: version, content_md: inserted.content });
      setContent(inserted.content);
      await mutate(updated);
      refreshLists();
      requestAnimationFrame(() => editor.current?.setSelectionRange(inserted.cursor, inserted.cursor));
      toast.push(selected.length === 1 ? "Image inserted." : "Images inserted.", "success");
    } catch (err) {
      if (err instanceof ApiError && err.isVersionConflict) setConflict(true);
      toast.push(err instanceof ApiError ? err.message : "Could not insert the image.", "error");
      await mutate();
    } finally {
      setBusy(false);
    }
  }

  async function placeExistingImage(assetId: string, filename: string) {
    if (!item) return;
    setBusy(true);
    try {
      await pendingSave.current;
      const fresh = await getItem(item.id);
      if (fresh.content_md !== content) {
        setConflict(true);
        toast.push("This note changed elsewhere. Reload before placing the image.", "error");
        return;
      }
      const start = editor.current?.selectionStart ?? content.length;
      const end = editor.current?.selectionEnd ?? start;
      const inserted = insertAtSelection(content, imageMarkdown(assetId, filename), start, end);
      const updated = await patchItem(item.id, { expected_version: fresh.version, content_md: inserted.content });
      setContent(inserted.content);
      await mutate(updated);
      refreshLists();
      toast.push("Image placed in note.", "success");
    } catch (err) {
      if (err instanceof ApiError && err.isVersionConflict) setConflict(true);
      toast.push(err instanceof ApiError ? err.message : "Could not place the image.", "error");
    } finally {
      setBusy(false);
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
              ref={editor}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onBlur={() => { if (content !== item.content_md) pendingSave.current = saveField({ content_md: content }); }}
              rows={16}
              aria-label="Content"
              placeholder="Start writing in Markdown. Use ```mermaid for diagrams."
              className="w-full resize-none border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
            />
            <button type="button" disabled={busy || saving} onClick={() => imageInput.current?.click()} className="mt-3 flex items-center gap-1.5 rounded border border-hairline px-3 py-1.5 text-[12px] text-ink-muted hover:text-ink disabled:opacity-50">
              <ImagePlus size={14} /> Insert image
            </button>
            <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/gif,image/webp,image/avif" multiple className="sr-only" aria-label="Choose images to insert" onChange={(event) => { void insertImages(event.target.files); event.target.value = ""; }} />
          </>
        ) : (
          <>
            <h1 className="mb-3 border-b border-hairline pb-2 font-serif text-[22px] font-semibold text-ink">{item.title}</h1>
            <NoteMarkdown content={item.content_md} />
          </>
        )}
      </div>

      <div className="mt-6 flex flex-col gap-5">
        <NoteImages item={item} onChanged={async () => { await mutate(); refreshLists(); }} onInsert={placeExistingImage} />
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
