"use client";

import { Suspense, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { createItem, getItem, interpretCaptureManually, linkNoteImage, uploadAsset } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError, Item } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { imageMarkdown, insertAtSelection, validNoteImage } from "@/lib/noteImages";

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
  const [images, setImages] = useState<{ id: string; file: File }[]>([]);
  const editor = useRef<HTMLTextAreaElement>(null);
  const [busy, setBusy] = useState(false);
  const dirty = title.trim().length > 0 || body.trim().length > 0;

  async function save() {
    setBusy(true);
    let created: Item | null = null;
    try {
      let finalBody = body;
      const uploadedImages: { id: string; assetId: string }[] = [];
      for (const image of images.filter(({ id }) => body.includes(`traceback-pending:${id}`))) {
        const uploaded = await uploadAsset(image.file);
        uploadedImages.push({ id: image.id, assetId: uploaded.id });
        finalBody = finalBody.replace(`traceback-pending:${image.id}`, `/api/v1/assets/${uploaded.id}/content`);
      }
      const folder = folderId ? await getItem(folderId) : null;
      const destination = folder
        ? { folder_id: folder.id, folder_expected_version: folder.version }
        : projectId && projectVersion
          ? { project_id: projectId, project_expected_version: Number(projectVersion) }
          : { category_id: categoryId || null };
      if (captureId && captureVersion && captureGeneration) {
        const result = await interpretCaptureManually(captureId, {
          expected_version: Number(captureVersion),
          expected_generation: Number(captureGeneration),
          items: [
            {
              kind: "create",
              item: {
                item_type: "note",
                title: title.trim() || "Untitled note",
                content_md: finalBody,
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
        created = result.items[0] ?? null;
      } else {
        created = await createItem({
          item_type: "note",
          title: title.trim() || "Untitled note",
          content_md: finalBody,
          ...destination,
        });
      }

      if (created) {
        let version = created.version;
        for (const image of uploadedImages) {
          const linked = await linkNoteImage(created.id, image.assetId, version);
          version = linked.version;
        }
      }

      toast.push("Note saved.", "success");
      router.push(images.length && created ? `/notes/${created.id}` : returnTo);
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not save the note or its images.", "error");
      if (created) router.push(`/notes/${created.id}`);
    } finally {
      setBusy(false);
    }
  }

  function discard() {
    router.push(returnTo);
  }

  function addImages(files: FileList | null) {
    const selected = Array.from(files ?? []);
    if (!selected.length) return;
    if (selected.some((file) => !validNoteImage(file))) {
      toast.push("Choose PNG, JPEG, GIF, WebP, or AVIF images up to 20 MB each.", "error");
      return;
    }
    const pending = selected.map((file) => ({ id: crypto.randomUUID(), file }));
    const markup = pending.map(({ id, file }) => imageMarkdown(id, file.name).replace(`/api/v1/assets/${id}/content`, `traceback-pending:${id}`)).join("\n\n");
    const start = editor.current?.selectionStart ?? body.length;
    const end = editor.current?.selectionEnd ?? start;
    const inserted = insertAtSelection(body, markup, start, end);
    setBody(inserted.content);
    setImages((current) => [...current, ...pending]);
    requestAnimationFrame(() => editor.current?.setSelectionRange(inserted.cursor, inserted.cursor));
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
          ref={editor}
          autoFocus
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={16}
          placeholder="Start writing in Markdown. Use ```mermaid for diagrams."
          className="w-full resize-none border-none bg-transparent text-[13.5px] text-ink placeholder:text-ink-faint focus:outline-none"
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <label className="cursor-pointer rounded border border-hairline px-3 py-1.5 text-[12px] text-ink-muted hover:text-ink">
          Insert image
          <input
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
            multiple
            className="sr-only"
            onChange={(event) => {
              addImages(event.target.files);
              event.target.value = "";
            }}
          />
        </label>
        {images.length > 0 && <span className="text-[12px] text-ink-muted">{images.length} image{images.length === 1 ? "" : "s"} inserted in draft</span>}
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
