"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ChevronRight, ChevronDown, Folder, Plus, Loader2, Trash2 } from "lucide-react";
import { archiveItem, createFolder, listItems } from "@/lib/traceback";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "./Toast";

function childrenKey(categoryId: string, parentId: string | null): string {
  return `folder-children:${categoryId}:${parentId ?? "root"}`;
}

function fetchChildren(categoryId: string, parentId: string | null) {
  return parentId
    ? listItems({ parent_id: parentId, limit: 100 })
    : listItems({ category_id: categoryId, top_level: true, limit: 100 });
}

export function FolderTree({
  categoryId,
  parentId,
  depth = 0,
}: {
  categoryId: string;
  parentId: string | null;
  depth?: number;
}) {
  const { data, error, isLoading, mutate } = useSWR(childrenKey(categoryId, parentId), () =>
    fetchChildren(categoryId, parentId),
  );
  const [addingFolder, setAddingFolder] = useState(false);

  const items = (data?.items ?? []).filter((i) => i.item_type !== "task");
  const folders = items.filter((i) => i.item_type === "folder");
  const files = items.filter((i) => i.item_type !== "folder");

  const returnTo = typeof window !== "undefined" ? window.location.pathname : "/";
  const newDocHref = `/notes/new?categoryId=${categoryId}${parentId ? `&folderId=${parentId}` : ""}&returnTo=${encodeURIComponent(returnTo)}`;

  return (
    <div style={{ paddingLeft: depth ? 16 : 0 }}>
      {isLoading && <div className="py-2 text-[12px] text-ink-faint">Loading…</div>}
      {error && <div className="py-2 text-[12px] text-danger">Could not load this folder.</div>}

      {folders.map((folder) => (
        <FolderNode key={folder.id} folder={folder} categoryId={categoryId} depth={depth} onArchived={() => void mutate()} />
      ))}

      {files.map((item) => (
        <FileRow key={item.id} item={item} onArchived={() => void mutate()} />
      ))}

      <div className="flex items-center gap-3 py-1">
        {addingFolder ? (
          <NewFolderInput
            categoryId={categoryId}
            parentId={parentId}
            onDone={() => {
              setAddingFolder(false);
              mutate();
            }}
            onCancel={() => setAddingFolder(false)}
          />
        ) : (
          <>
            <button
              onClick={() => setAddingFolder(true)}
              className="flex items-center gap-1 text-[11.5px] text-ink-faint hover:text-accent-navy"
            >
              <Plus size={11} /> new folder
            </button>
            <Link href={newDocHref} className="flex items-center gap-1 text-[11.5px] text-ink-faint hover:text-accent-navy">
              <Plus size={11} /> new doc
            </Link>
          </>
        )}
      </div>
    </div>
  );
}

function NewFolderInput({
  categoryId,
  parentId,
  onDone,
  onCancel,
}: {
  categoryId: string;
  parentId: string | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const submittedRef = useRef(false);
  const toast = useToast();

  async function submit() {
    if (submittedRef.current) return;
    const value = title.trim();
    if (!value) {
      submittedRef.current = true;
      return onCancel();
    }
    submittedRef.current = true;
    setBusy(true);
    try {
      await createFolder(value, categoryId, parentId ?? undefined);
      onDone();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not create the folder.", "error");
      onCancel();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-[12px] text-ink-faint">›</span>
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") {
            submittedRef.current = true;
            onCancel();
          }
        }}
        onBlur={submit}
        placeholder="Folder name…"
        disabled={busy}
        className="border-none bg-transparent text-[12.5px] text-ink placeholder:text-ink-faint focus:outline-none"
      />
      {busy && <Loader2 size={12} className="animate-spin text-ink-faint" />}
    </div>
  );
}

function FolderNode({
  folder,
  categoryId,
  depth,
  onArchived,
}: {
  folder: Item;
  categoryId: string;
  depth: number;
  onArchived: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const expanded = searchParams.getAll("expanded").includes(folder.id);

  function toggleExpanded() {
    const params = new URLSearchParams(window.location.search);
    const ids = params.getAll("expanded").filter((id) => id !== folder.id);
    if (!expanded) ids.push(folder.id);
    params.delete("expanded");
    ids.forEach((id) => params.append("expanded", id));
    const query = params.toString();
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
  }

  return (
    <div>
      <div className="flex items-center border-b border-hairline hover:bg-paper-strong">
        <button
          onClick={toggleExpanded}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
        >
          {expanded ? <ChevronDown size={13} className="flex-none text-ink-faint" /> : <ChevronRight size={13} className="flex-none text-ink-faint" />}
          <Folder size={13} className="flex-none text-ink-faint" />
          <span className="truncate font-serif text-[14px] text-ink">{folder.title}</span>
        </button>
        <DeleteButton item={folder} onArchived={onArchived} />
      </div>
      {expanded && (
        <FolderTree
          categoryId={categoryId}
          parentId={folder.id}
          depth={depth + 1}
        />
      )}
    </div>
  );
}

function FileRow({ item, onArchived }: { item: Item; onArchived: () => void }) {
  const href = item.item_type === "project" ? `/projects/${item.id}` : `/notes/${item.id}`;
  return (
    <div className="flex items-center border-b border-hairline hover:bg-paper-strong">
      <Link href={href} className="flex min-w-0 flex-1 items-center gap-2 py-2 pl-5">
        <span className="w-10 flex-none text-[10px] uppercase tracking-wide text-ink-faint">{item.item_type}</span>
        <span className="truncate font-serif text-[14px] text-ink">{item.title}</span>
      </Link>
      {item.item_type === "note" && <DeleteButton item={item} onArchived={onArchived} />}
    </div>
  );
}

function DeleteButton({ item, onArchived }: { item: Item; onArchived: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function archive() {
    setBusy(true);
    try {
      await archiveItem(item.id, item.version);
      onArchived();
      toast.push(item.item_type === "folder" ? "Folder moved to Archive. Its contents remain active." : "Note moved to Archive.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not delete this item.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void archive()}
      disabled={busy}
      aria-label={`Delete ${item.item_type} ${item.title}`}
      title="Move to Archive"
      className="flex h-8 w-8 flex-none items-center justify-center rounded text-ink-faint hover:bg-paper-strong hover:text-danger disabled:opacity-50"
    >
      <Trash2 size={14} aria-hidden />
    </button>
  );
}
