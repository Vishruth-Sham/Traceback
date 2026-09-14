"use client";

import { moveItem } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "./Toast";

export function MoveToSelect({ item, onMoved }: { item: Item; onMoved: () => void }) {
  const { categories } = useCategories();
  const toast = useToast();

  async function handleChange(categoryId: string) {
    try {
      await moveItem(item.id, { expected_version: item.version, category_id: categoryId });
      onMoved();
      toast.push("Moved.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Move failed.", "error");
    }
  }

  return (
    <select
      defaultValue=""
      onChange={(e) => e.target.value && handleChange(e.target.value)}
      aria-label={`Move ${item.title}`}
      className="flex-none rounded border border-hairline bg-paper px-2 py-1 text-[11.5px] text-ink-muted"
    >
      <option value="" disabled>
        Move to…
      </option>
      {categories.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}
