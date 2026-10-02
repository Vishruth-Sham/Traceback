"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { Item } from "@/lib/types";
import { formatDeadline } from "@/lib/taskGrouping";

const typeLabel: Record<string, string> = {
  note: "note",
  task: "task",
  project: "project",
  folder: "folder",
};

// Notes, projects, and folders open as pages; only tasks use the side panel.
export function ItemRow({ item, onOpenTask }: { item: Item; onOpenTask: (id: string) => void }) {
  const deadline = item.item_type === "task" ? formatDeadline(item) : null;

  const content = (
    <>
      <span className="w-12 flex-none text-[10.5px] uppercase tracking-wide text-ink-faint">
        {typeLabel[item.item_type]}
      </span>
      <span className="flex-1 truncate font-serif text-[14px] text-ink">{item.title}</span>
      {item.item_type === "task" && item.status === "completed" && (
        <CheckCircle2 size={13} className="flex-none text-success" />
      )}
      {deadline && (
        <span className={"flex-none text-[11.5px] " + (item.overdue ? "font-semibold text-danger" : "text-ink-muted")}>
          {deadline}
        </span>
      )}
    </>
  );

  const rowClass = "flex w-full items-center gap-3 border-b border-hairline py-2.5 text-left hover:bg-paper-strong";

  if (item.item_type === "note") {
    return (
      <Link href={`/notes/${item.id}`} className={rowClass}>
        {content}
      </Link>
    );
  }
  if (item.item_type === "project") {
    return (
      <Link href={`/projects/${item.id}`} className={rowClass}>
        {content}
      </Link>
    );
  }
  if (item.item_type === "folder") {
    return (
      <Link href={`/folders/${item.id}`} className={rowClass}>
        {content}
      </Link>
    );
  }
  return (
    <button onClick={() => onOpenTask(item.id)} className={rowClass}>
      {content}
    </button>
  );
}
