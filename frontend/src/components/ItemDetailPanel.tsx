"use client";

import { useEffect, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { X, Archive as ArchiveIcon, ArchiveRestore, Trash2, History, Loader2 } from "lucide-react";
import {
  archiveItem,
  completeTask,
  deleteItemPermanently,
  getItem,
  moveItem,
  patchItem,
  reopenTask,
  restoreItem,
} from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "./Toast";
import { RelationsSection } from "./RelationsSection";
import { HistoryList } from "./HistoryList";

function useItem(id: string | null) {
  return useSWR<Item>(id ? `item:${id}` : null, id ? () => getItem(id) : null);
}
export function ItemDetailPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: item, error, isLoading, mutate } = useItem(itemId);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-30 flex justify-end" role="dialog" aria-modal="true" aria-label="Item detail">
      <button aria-label="Close panel" className="absolute inset-0 bg-ink/10" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-[440px] flex-none flex-col overflow-y-auto border-l border-hairline bg-paper-soft">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <span className="text-[11px] uppercase tracking-wide text-ink-faint">{item?.item_type ?? "item"}</span>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-muted hover:text-ink">
            <X size={16} />
          </button>
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ink-muted">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        )}
        {error && <div className="px-5 py-8 text-[13px] text-danger">Could not load this item.</div>}

        {item && <ItemDetailBody key={item.id} item={item} mutate={mutate} onClose={onClose} />}
      </div>
    </div>
  );
}

function ItemDetailBody({
  item,
  mutate,
  onClose,
}: {
  item: Item;
  mutate: (data?: Item) => Promise<Item | undefined> | void;
  onClose: () => void;
}) {
  const { categories } = useCategories();
  const { mutate: globalMutate } = useSWRConfig();
  const toast = useToast();

  const [title, setTitle] = useState(item.title);
  const [content, setContent] = useState(item.content_md);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false);

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
        toast.push("This item changed elsewhere. Review the latest version before saving again.", "error");
      } else {
        toast.push(err instanceof ApiError ? err.message : "Save failed.", "error");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleComplete() {
    if (!item) return;
    setBusy(true);
    try {
      const updated =
        item.status === "open"
          ? await completeTask(item.id, item.version)
          : await reopenTask(item.id, item.version);
      await mutate(updated);
      refreshLists();
      toast.push(item.status === "open" ? "Task completed." : "Task reopened.", "success", {
        label: "Undo",
        onClick: async () => {
          const reverted =
            item.status === "open"
              ? await reopenTask(updated.id, updated.version)
              : await completeTask(updated.id, updated.version);
          await mutate(reverted);
          refreshLists();
        },
      });
    } catch (err) {
      if (err instanceof ApiError && err.isVersionConflict) {
        setConflict(true);
      } else {
        toast.push("Could not update the task.", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    if (!item) return;
    setBusy(true);
    try {
      const updated = item.archived_at
        ? await restoreItem(item.id, item.version)
        : await archiveItem(item.id, item.version);
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
      onClose();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not delete.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleMove(categoryId: string) {
    if (!item) return;
    setBusy(true);
    try {
      const updated = await moveItem(item.id, { expected_version: item.version, category_id: categoryId });
      await mutate(updated);
      refreshLists();
      toast.push("Moved.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Move failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleMoveToInbox() {
    if (!item) return;
    setBusy(true);
    try {
      const updated = await moveItem(item.id, { expected_version: item.version, inbox: true });
      await mutate(updated);
      refreshLists();
      toast.push("Moved to Inbox.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Move failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-5 px-5 py-4">
      {conflict && (
        <div className="rounded border border-accent-gold bg-accent-navy-soft px-3 py-2 text-[12.5px] text-ink">
          Someone (or something) else changed this item. Reload to see the latest before editing again.
          <button className="ml-2 font-medium text-accent-navy underline" onClick={() => mutate()}>
            Reload
          </button>
        </div>
      )}

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => title.trim() && title !== item.title && saveField({ title })}
        aria-label="Title"
        className="w-full border-none bg-transparent font-serif text-[19px] font-semibold text-ink focus:outline-none"
      />

      {item.item_type === "task" && (
        <div className="flex items-center gap-2">
          <button
            onClick={handleToggleComplete}
            disabled={busy}
            className={
              "flex items-center gap-2 rounded border px-3 py-1.5 text-[13px] disabled:opacity-50 " +
              (item.status === "completed"
                ? "border-accent-navy text-accent-navy"
                : "border-hairline text-ink-muted hover:text-ink")
            }
          >
            <span
              className={
                "flex h-3 w-3 flex-none items-center justify-center rounded-[2px] border " +
                (item.status === "completed" ? "border-accent-navy bg-accent-navy" : "border-ink-faint")
              }
            />
            {item.status === "completed" ? "Completed — reopen" : "Mark complete"}
          </button>
        </div>
      )}

      {item.item_type === "task" && <DeadlineEditor item={item} onSave={saveField} />}

      <div className="flex flex-col gap-1.5">
        <label className="text-[11px] uppercase tracking-wide text-ink-faint">Notes</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onBlur={() => content !== item.content_md && saveField({ content_md: content })}
          rows={6}
          aria-label="Notes"
          placeholder="Add notes…"
          className="w-full resize-none rounded border border-hairline bg-paper px-3 py-2 text-[13.5px] text-ink placeholder:text-ink-faint focus:border-accent-navy focus:outline-none"
        />
        {saving && <span className="text-[11px] text-ink-faint">saving…</span>}
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-[11px] uppercase tracking-wide text-ink-faint">Category</label>
        <select
          value={item.category_id ?? ""}
          onChange={(e) => (e.target.value ? handleMove(e.target.value) : handleMoveToInbox())}
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

      <RelationsSection
        item={item}
        onChanged={() => {
          mutate();
          refreshLists();
        }}
      />

      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => setShowHistory((v) => !v)}
          className="flex items-center gap-2 self-start text-[12px] text-ink-muted hover:text-ink"
        >
          <History size={13} /> {showHistory ? "hide history" : "show history"}
        </button>
        {showHistory && <HistoryList itemId={item.id} />}
      </div>

      <div className="mt-auto flex flex-wrap gap-2 border-t border-hairline pt-4">
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
      <div className="text-[11px] text-ink-faint">
        updated {new Date(item.updated_at).toLocaleString()} · v{item.version}
      </div>
    </div>
  );
}

function DeadlineEditor({
  item,
  onSave,
}: {
  item: Item;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
}) {
  const [date, setDate] = useState(item.due_date ?? "");
  const [time, setTime] = useState(item.due_time?.slice(0, 5) ?? "");

  function commit(newDate: string, newTime: string) {
    if (!newDate) {
      onSave({ due_date: null, due_time: null, due_timezone: null });
      return;
    }
    if (newTime) {
      onSave({
        due_date: newDate,
        due_time: `${newTime}:00`,
        due_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
    } else {
      onSave({ due_date: newDate, due_time: null, due_timezone: null });
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] uppercase tracking-wide text-ink-faint">Deadline</label>
      <div className="flex items-center gap-2">
        <input
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
            commit(e.target.value, time);
          }}
          className="rounded border border-hairline bg-paper px-2 py-1 text-[13px] text-ink"
        />
        <input
          type="time"
          value={time}
          disabled={!date}
          onChange={(e) => {
            setTime(e.target.value);
            commit(date, e.target.value);
          }}
          className="rounded border border-hairline bg-paper px-2 py-1 text-[13px] text-ink disabled:opacity-40"
        />
        {date && (
          <button
            className="text-[12px] text-ink-muted underline"
            onClick={() => {
              setDate("");
              setTime("");
              commit("", "");
            }}
          >
            Clear
          </button>
        )}
      </div>
      {item.overdue && <span className="text-[12px] font-semibold text-danger">Overdue</span>}
    </div>
  );
}
