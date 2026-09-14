"use client";

import { useEffect, useRef, useState } from "react";
import { Item } from "@/lib/types";
import { formatDeadline } from "@/lib/taskGrouping";
import { CategoryTag } from "./CategoryTag";
import { useCategories } from "@/lib/useCategories";
import { categoryName } from "@/lib/useCategories";

export function TaskRow({
  item,
  onOpen,
  onToggle,
  toggling,
}: {
  item: Item;
  onOpen: () => void;
  onToggle: () => void;
  toggling: boolean;
}) {
  const { categories } = useCategories();
  const deadline = formatDeadline(item);
  const label = categoryName(categories, item.category_id);
  const completed = item.status === "completed";

  // Completing a task plays a short "strike it out, then it's gone" sequence
  // before the real request fires, instead of the row just vanishing the
  // instant the list refetches.
  const [phase, setPhase] = useState<"idle" | "striking" | "fading">("idle");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach(clearTimeout);
    };
  }, []);

  function handleCheckboxClick(e: React.MouseEvent) {
    e.stopPropagation();
    if (completed) {
      onToggle();
      return;
    }
    setPhase("striking");
    timers.current.push(
      setTimeout(() => setPhase("fading"), 220),
      setTimeout(() => onToggle(), 440),
    );
  }

  return (
    <div
      className={
        "flex items-center gap-3 border-b border-hairline px-2 py-2.5 -mx-2 rounded transition-all duration-150 hover:bg-paper-strong " +
        (phase === "fading" ? "opacity-0" : "opacity-100")
      }
    >
      <button
        onClick={handleCheckboxClick}
        disabled={toggling}
        aria-label={completed ? "Reopen task" : "Complete task"}
        className={
          "flex h-3.5 w-3.5 flex-none items-center justify-center rounded-[2px] border transition-colors duration-150 " +
          (completed || phase !== "idle" ? "border-accent-navy bg-accent-navy" : "border-ink-faint")
        }
      />
      <button onClick={onOpen} className="relative flex-1 truncate text-left font-serif text-[14.5px]">
        <span className={completed ? "text-ink-faint line-through" : phase !== "idle" ? "text-ink-faint" : "text-ink"}>
          {item.title}
        </span>
        {!completed && (
          <span
            className="absolute left-0 top-1/2 h-px bg-ink-faint transition-all duration-200 ease-out"
            style={{ width: phase !== "idle" ? "100%" : "0%" }}
          />
        )}
      </button>
      {deadline && (
        <span className={"flex-none text-[11.5px] " + (item.overdue ? "font-semibold text-danger" : "text-ink-muted")}>
          {item.overdue ? `Overdue · ${deadline}` : deadline}
        </span>
      )}
      {label && <CategoryTag label={label} />}
    </div>
  );
}
