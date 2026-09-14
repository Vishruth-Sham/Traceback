"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { createItem, interpretCaptureManually, listItems } from "@/lib/traceback";
import { useCategories } from "@/lib/useCategories";
import { ApiError } from "@/lib/types";
import { useToast } from "@/components/Toast";

const EXAMPLES = ["Buy soil for the tomatoes this weekend", "Finish ch.5 reading before book club Thu"];

function AddTaskPageInner() {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const { categories } = useCategories();
  const { data: containers } = useSWR("task-create-containers", async () => {
    const [projects, folders] = await Promise.all([
      listItems({ item_type: "project", limit: 100 }),
      listItems({ item_type: "folder", limit: 100 }),
    ]);
    return { projects: projects.items, folders: folders.items };
  });

  const captureId = params.get("captureId");
  const captureVersion = params.get("captureVersion");
  const captureGeneration = params.get("captureGeneration");
  const prefill = params.get("raw") ?? "";

  const [step, setStep] = useState<1 | 2>(prefill ? 2 : 1);
  const [raw, setRaw] = useState(prefill);
  const [title, setTitle] = useState(prefill);
  const [destination, setDestination] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("");
  const [busy, setBusy] = useState(false);

  function goToPreview() {
    const value = raw.trim();
    if (!value) return;
    setTitle(value);
    setStep(2);
  }

  async function save() {
    const value = title.trim();
    if (!value) return;
    setBusy(true);
    try {
      const due_date = dueDate || null;
      const due_time = dueDate && dueTime ? `${dueTime}:00` : null;
      const due_timezone = dueDate && dueTime ? Intl.DateTimeFormat().resolvedOptions().timeZone : null;
      const [destinationType, destinationId] = destination.split(":", 2);
      const container =
        destinationType === "project"
          ? containers?.projects.find((item) => item.id === destinationId)
          : destinationType === "folder"
            ? containers?.folders.find((item) => item.id === destinationId)
            : undefined;
      const placement =
        destinationType === "project" && container
          ? { project_id: container.id, project_expected_version: container.version }
          : destinationType === "folder" && container
            ? { folder_id: container.id, folder_expected_version: container.version }
            : { category_id: destinationType === "category" ? destinationId : null };

      if (captureId && captureVersion && captureGeneration) {
        // Resolving a saved-but-unparsed (or failed) capture: apply this as one
        // atomic manual interpretation, so the original capture is linked as
        // provenance and its processing is marked resolved — not a second,
        // disconnected item creation.
        await interpretCaptureManually(captureId, {
          expected_version: Number(captureVersion),
          expected_generation: Number(captureGeneration),
          items: [
            {
              kind: "create",
              item: {
                item_type: "task",
                title: value,
                category_id: "category_id" in placement ? placement.category_id : null,
                due_date,
                due_time,
                due_timezone,
              },
              ...(destinationType === "project" && container
                ? { project_id: container.id, project_expected_version: container.version }
                : destinationType === "folder" && container
                  ? { folder_id: container.id, folder_expected_version: container.version }
                  : {}),
            },
          ],
        });
      } else {
        await createItem({
          item_type: "task",
          title: value,
          ...placement,
          due_date,
          due_time,
          due_timezone,
        });
      }
      toast.push("Task added.", "success");
      router.push("/tasks");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not add the task.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <button
        onClick={() => (step === 2 ? setStep(1) : router.push("/tasks"))}
        className="mb-4 flex items-center gap-1.5 text-[12px] text-ink-faint hover:text-ink"
      >
        <ArrowLeft size={13} /> Tasks
      </button>
      <h1 className="mb-1 font-serif text-[24px] font-semibold text-ink">Add task</h1>
      {captureId && (
        <p className="mb-4 text-[12.5px] text-ink-faint">
          Resolving your saved input manually. The original text stays preserved either way.
        </p>
      )}

      {step === 1 && (
        <>
          <p className="mb-4 text-[13px] text-ink-muted">
            Write it however you&apos;d say it. You&apos;ll confirm the details before it&apos;s saved.
          </p>
          <textarea
            autoFocus
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) goToPreview();
            }}
            rows={3}
            placeholder="What do you need to do?"
            className="mb-3 w-full resize-none rounded border border-hairline bg-paper-soft px-4 py-3 text-[14px] text-ink placeholder:text-ink-faint focus:border-accent-navy focus:outline-none"
          />
          <div className="mb-6 flex flex-wrap items-center gap-2 text-[12px] text-ink-faint">
            <span>try:</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setRaw(ex)}
                className="rounded-full border border-hairline px-2.5 py-1 hover:border-accent-navy hover:text-accent-navy"
              >
                &quot;{ex}&quot;
              </button>
            ))}
          </div>
          <div className="flex justify-end">
            <button
              onClick={goToPreview}
              disabled={!raw.trim()}
              className="flex items-center gap-2 rounded bg-accent-navy px-4 py-2 text-[13px] font-medium text-paper disabled:opacity-40"
            >
              Add task <ArrowRight size={14} />
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <p className="mb-4 text-[13px] text-ink-muted">Check the details, then save.</p>
          <div className="mb-4 border-l-2 border-hairline pl-3 text-[13px] italic text-ink-muted">
            &quot;{raw}&quot;
          </div>

          <div className="mb-6 flex flex-col overflow-hidden rounded border border-hairline">
            <div className="border-b border-hairline px-4 py-3">
              <label className="text-[11px] uppercase tracking-wide text-ink-faint">Title</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-label="Title"
                className="mt-1 block w-full border-none bg-transparent text-[14.5px] font-medium text-ink focus:outline-none"
              />
            </div>
            <div className="border-b border-hairline px-4 py-3">
              <label className="text-[11px] uppercase tracking-wide text-ink-faint">Destination</label>
              <select
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                aria-label="Destination"
                className="mt-1 block w-full border-none bg-transparent text-[14px] text-ink focus:outline-none"
              >
                <option value="">Inbox (unclassified)</option>
                {categories.map((c) => (
                  <option key={c.id} value={`category:${c.id}`}>
                    {c.name}
                  </option>
                ))}
                {(containers?.projects.length ?? 0) > 0 && <optgroup label="Projects">
                  {containers?.projects.map((item) => <option key={item.id} value={`project:${item.id}`}>{item.title}</option>)}
                </optgroup>}
                {(containers?.folders.length ?? 0) > 0 && <optgroup label="Folders">
                  {containers?.folders.map((item) => <option key={item.id} value={`folder:${item.id}`}>{item.title}</option>)}
                </optgroup>}
              </select>
            </div>
            <div className="px-4 py-3">
              <label className="text-[11px] uppercase tracking-wide text-ink-faint">Due date</label>
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  className="rounded border border-hairline bg-paper px-2 py-1 text-[13px] text-ink"
                />
                <input
                  type="time"
                  value={dueTime}
                  disabled={!dueDate}
                  onChange={(e) => setDueTime(e.target.value)}
                  className="rounded border border-hairline bg-paper px-2 py-1 text-[13px] text-ink disabled:opacity-40"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Link
              href="/tasks"
              className="rounded border border-hairline px-4 py-2 text-[13px] text-ink-muted hover:text-ink"
            >
              Discard
            </Link>
            <button
              onClick={save}
              disabled={busy || !title.trim()}
              className="flex items-center gap-2 rounded bg-accent-navy px-4 py-2 text-[13px] font-medium text-paper disabled:opacity-40"
            >
              {busy && <Loader2 size={13} className="animate-spin" />} Add task
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function AddTaskPage() {
  return (
    <Suspense>
      <AddTaskPageInner />
    </Suspense>
  );
}
