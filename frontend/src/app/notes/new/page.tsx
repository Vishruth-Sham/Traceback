"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { createItem, getItem, interpretCaptureManually } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError } from "@/lib/types";
import { useToast } from "@/components/Toast";

function AddNotePageInner() {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const { categories } = useCategories();

  const initialCategoryId = params.get("categoryId") ?? "";
  const projectId = params.get("projectId");
  const projectVersion = params.get("projectVersion");
  const folderId = params.get("folderId");
  const captureId = params.get("captureId");
  const captureVersion = params.get("captureVersion");
  const captureGeneration = params.get("captureGeneration");
  const returnTo = params.get("returnTo") ?? "/inbox";

  const [categoryId, setCategoryId] = useState(initialCategoryId);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState(params.get("prefill") ?? "");
  const [busy, setBusy] = useState(false);
  const dirty = title.trim().length > 0 || body.trim().length > 0;

  async function save() {
    setBusy(true);
    try {
      const folder = folderId ? await getItem(folderId) : null;
      const destination = folder
        ? { folder_id: folder.id, folder_expected_version: folder.version }
        : projectId && projectVersion
          ? { project_id: projectId, project_expected_version: Number(projectVersion) }
          : { category_id: categoryId || null };
      if (captureId && captureVersion && captureGeneration) {
        await interpretCaptureManually(captureId, {
          expected_version: Number(captureVersion),
          expected_generation: Number(captureGeneration),
          items: [
            {
              kind: "create",
              item: {
                item_type: "note",
                title: title.trim() || "Untitled note",
                content_md: body,
                category_id: "category_id" in destination ? destination.category_id : null,
              },
              ...(folder
                ? { folder_id: folder.id, folder_expected_version: folder.version }
                : projectId && projectVersion
                  ? { project_id: projectId, project_expected_version: Number(projectVersion) }
                  : {}),
            },
          ],
        });
      } else {
        await createItem({
          item_type: "note",
          title: title.trim() || "Untitled note",
          content_md: body,
          ...destination,
        });
      }

      toast.push("Note saved.", "success");
      router.push(returnTo);
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not save the note.", "error");
    } finally {
      setBusy(false);
    }
  }

  function discard() {
    router.push(returnTo);
  }

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <div className="mb-3 flex items-center justify-between">
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          aria-label="Folder"
          className="rounded border border-hairline bg-paper px-2.5 py-1 text-[12.5px] text-ink-muted"
        >
          <option value="">choose folder…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <span className="text-[11px] uppercase tracking-wide text-ink-faint">new note</span>
      </div>

      <div className="rounded border border-hairline bg-paper-soft px-6 py-5">
        <div className="mb-3 flex items-center justify-end text-[11px] text-ink-faint">
          {dirty ? "draft · not saved" : "draft"}
        </div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Untitled note"
          aria-label="Title"
          className="mb-3 w-full border-b border-hairline bg-transparent pb-2 font-serif text-[22px] font-semibold text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <textarea
          autoFocus
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={16}
          placeholder="Start writing. Markdown, no other formatting."
          className="w-full resize-none border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <button onClick={discard} className="rounded border border-hairline px-4 py-2 text-[13px] text-ink-muted hover:text-ink">
          Discard
        </button>
        <button
          onClick={save}
          disabled={busy}
          className="flex items-center gap-2 rounded bg-accent-navy px-4 py-2 text-[13px] font-medium text-paper disabled:opacity-40"
        >
          {busy && <Loader2 size={13} className="animate-spin" />} Save note
        </button>
      </div>
    </div>
  );
}

export default function AddNotePage() {
  return (
    <Suspense>
      <AddNotePageInner />
    </Suspense>
  );
}
