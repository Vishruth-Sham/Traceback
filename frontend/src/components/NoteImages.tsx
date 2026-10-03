"use client";

import { useState } from "react";
import useSWR from "swr";
import { CornerDownLeft, X } from "lucide-react";
import { getAsset, unlinkNoteImage } from "@/lib/traceback";
import { ApiError, Asset, Item } from "@/lib/types";
import { useToast } from "@/components/Toast";

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"]);
export function NoteImages({ item, onChanged, onInsert }: { item: Item; onChanged: () => Promise<unknown>; onInsert: (assetId: string, filename: string) => Promise<void> }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const { data: assets, mutate } = useSWR<Asset[]>(
    `note-images:${item.id}:${item.asset_ids.join(",")}`,
    () => Promise.all(item.asset_ids.map(getAsset)),
  );

  async function remove(assetId: string) {
    setBusy(true);
    try {
      await unlinkNoteImage(item.id, assetId, item.version);
      await onChanged();
      toast.push("Image removed from note.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not remove image.", "error");
    } finally {
      setBusy(false);
      void mutate();
    }
  }

  const unplaced = assets?.filter((asset) => !item.content_md.includes(`/api/v1/assets/${asset.id}/content`));
  if (!unplaced?.length) return null;

  return (
    <section aria-label="Unplaced images" className="border-t border-hairline pt-4">
      <h2 className="mb-3 text-[11px] uppercase tracking-wide text-ink-faint">Unplaced images</h2>
      {unplaced.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {unplaced.map((asset) => (
            <div key={asset.id} className="group relative overflow-hidden rounded border border-hairline bg-paper">
              {IMAGE_TYPES.has(asset.detected_mime_type) ? (
                // Authenticated same-origin images are served as original bytes by the API proxy.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`/api/v1/assets/${asset.id}/content`} alt={asset.original_filename} loading="lazy" className="h-36 w-full object-contain" />
              ) : <div className="p-3 text-[12px] text-ink-muted">Preview unavailable</div>}
              <div className="flex items-center justify-between gap-1 border-t border-hairline px-2 py-1.5">
                <span className="truncate text-[11px] text-ink-muted" title={asset.original_filename}>{asset.original_filename}</span>
                <button type="button" disabled={busy} onClick={() => void onInsert(asset.id, asset.original_filename)} aria-label={`Place ${asset.original_filename} in note`} className="text-ink-muted hover:text-accent-navy disabled:opacity-50"><CornerDownLeft size={13} /></button>
                <button type="button" disabled={busy} onClick={() => void remove(asset.id)} aria-label={`Remove ${asset.original_filename}`} className="text-ink-muted hover:text-danger disabled:opacity-50"><X size={13} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
