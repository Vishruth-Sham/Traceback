"use client";

import { useState } from "react";
import useSWR from "swr";
import { X } from "lucide-react";
import { createRelation, deleteRelation, getItem, listItems } from "@/lib/traceback";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "./Toast";

const RELATION_LABELS: Record<string, string> = {
  part_of: "in",
  about: "about",
  related_to: "related to",
};

function RelationTag({
  relation,
  otherId,
  onUnlink,
}: {
  relation: string;
  otherId: string;
  onUnlink: () => void;
}) {
  const { data: other } = useSWR(`link-item:${otherId}`, () => getItem(otherId));
  const label = other?.title ?? "…";

  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-hairline bg-paper px-2.5 py-1 text-[12px] text-ink">
      <span className="shrink-0 text-ink-faint">{RELATION_LABELS[relation] ?? relation}</span>
      <span className="truncate">{label}</span>
      <button onClick={onUnlink} className="shrink-0 text-ink-faint hover:text-danger" aria-label={`Unlink ${label}`}>
        <X size={11} />
      </button>
    </span>
  );
}

export function RelationsSection({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const [query, setQuery] = useState("");
  const { data: results } = useSWR(query.length > 1 ? `link-search:${query}` : null, () =>
    listItems({ q: query, limit: 8 }),
  );
  const toast = useToast();

  async function link(targetId: string, targetVersion: number, relation: "part_of" | "about" | "related_to") {
    try {
      await createRelation({
        from_item_id: item.id,
        from_expected_version: item.version,
        relation,
        to_item_id: targetId,
        to_expected_version: targetVersion,
      });
      onChanged();
      setQuery("");
      toast.push("Linked.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not link.", "error");
    }
  }

  async function unlink(relationId: string, fromId: string, toId: string) {
    try {
      const otherId = fromId === item.id ? toId : fromId;
      const other = await getItem(otherId);
      await deleteRelation(
        relationId,
        fromId === item.id ? item.version : other.version,
        toId === item.id ? item.version : other.version,
      );
      onChanged();
      toast.push("Unlinked.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not unlink.", "error");
    }
  }

  // An item already linked in either direction can't be linked again (the
  // backend correctly rejects it as `relation_exists`); hide it from the
  // picker instead of letting someone click it and hit that error.
  const relatedIds = new Set(item.relations.map((r) => (r.from_item_id === item.id ? r.to_item_id : r.from_item_id)));

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] uppercase tracking-wide text-ink-faint">Links</label>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Link to another item…"
        className="rounded border border-hairline bg-paper px-2.5 py-1.5 text-[12px] text-ink placeholder:text-ink-faint"
      />
      {results && results.items.length > 0 && (
        <div className="flex flex-col overflow-hidden rounded border border-hairline">
          {results.items
            .filter((r) => r.id !== item.id && !relatedIds.has(r.id))
            .map((r) => (
              <button
                key={r.id}
                onClick={() => link(r.id, r.version, r.item_type === "project" || r.item_type === "folder" ? "part_of" : "related_to")}
                className="flex items-center justify-between border-b border-hairline px-2.5 py-1.5 text-left text-[12px] last:border-b-0 hover:bg-paper"
              >
                <span className="truncate text-ink">{r.title}</span>
                <span className="text-ink-faint">{r.item_type}</span>
              </button>
            ))}
        </div>
      )}
      {item.relations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {item.relations.map((r) => (
            <RelationTag
              key={r.id}
              relation={r.relation}
              otherId={r.from_item_id === item.id ? r.to_item_id : r.from_item_id}
              onUnlink={() => unlink(r.id, r.from_item_id, r.to_item_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
