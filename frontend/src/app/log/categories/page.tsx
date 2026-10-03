"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { X } from "lucide-react";
import {
  classifyLog,
  createLogCategory,
  deleteLogCategory,
  listLogCategories,
  listLogDays,
  updateLogCategory,
} from "@/lib/traceback";
import { ApiError, LogCategory } from "@/lib/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";

function CategoryRow({ category, onChanged }: { category: LogCategory; onChanged: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description);

  async function save() {
    const patch: { name?: string; description?: string } = {};
    if (name.trim().toLowerCase() !== category.name) patch.name = name;
    if (description.trim() !== category.description) patch.description = description;
    if (!Object.keys(patch).length) return;
    try {
      await updateLogCategory(category.id, patch);
      onChanged();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not save the category.", "error");
      setName(category.name);
      setDescription(category.description);
    }
  }

  async function remove() {
    try {
      await deleteLogCategory(category.id);
      onChanged();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not remove the category.", "error");
    }
  }

  return (
    <li className="flex items-center gap-3 border-t border-hairline py-2.5">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={save}
        maxLength={40}
        aria-label={`Name of ${category.name}`}
        className="w-[140px] flex-none border border-hairline bg-transparent px-2 py-1 text-[13px] text-ink focus:border-accent-navy focus:outline-none"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onBlur={save}
        maxLength={200}
        aria-label={`Description of ${category.name}`}
        className="min-w-0 flex-1 border border-hairline bg-transparent px-2 py-1 font-serif text-[15px] text-ink focus:border-accent-navy focus:outline-none"
      />
      <button
        onClick={remove}
        aria-label={`Remove ${category.name}`}
        className="border border-hairline p-1 text-ink-muted hover:text-danger"
      >
        <X size={13} />
      </button>
    </li>
  );
}

export default function LogCategoriesPage() {
  const toast = useToast();
  const { data, error, isLoading, mutate } = useSWR("log-categories", () => listLogCategories());
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [running, setRunning] = useState<"today" | "all" | null>(null);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await createLogCategory(name, description);
      setName("");
      setDescription("");
      await mutate();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not add the category.", "error");
    }
  }

  async function rerun(scope: "today" | "all") {
    setRunning(scope);
    try {
      const result =
        scope === "all" ? await classifyLog({ all_days: true }) : await classifyLog({ date: (await listLogDays(undefined, 1)).today });
      const failed = result.failed_days.length;
      toast.push(
        failed ? `Re-ran ${result.classified_days.length} day(s); ${failed} failed.` : `Re-ran ${result.classified_days.length} day(s).`,
        failed ? "error" : "success",
      );
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not re-run the classifier.", "error");
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <Link href="/log" className="text-[12px] text-accent-navy hover:underline">
        ← Daily log
      </Link>
      <div className="mt-4">
        <PageHeader
          eyebrow="log / settings"
          title="Categories"
          description="Names and one-line descriptions. The description is what the local model sees."
        />
      </div>

      {isLoading && <LoadingState />}
      {error && <ErrorState message="Could not load categories." onRetry={() => mutate()} />}
      {data && data.length === 0 && <EmptyState title="No categories." hint="Entries will be summarised but not tagged." />}
      <ul className="border-b border-hairline">
        {data?.map((category) => (
          <CategoryRow key={`${category.id}:${category.name}:${category.description}`} category={category} onChanged={() => mutate()} />
        ))}
      </ul>

      <form onSubmit={add} className="mt-4 flex items-center gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={40}
          aria-label="New category name"
          placeholder="name"
          className="w-[140px] flex-none border border-hairline bg-transparent px-2 py-1 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent-navy focus:outline-none"
        />
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={200}
          aria-label="New category description"
          placeholder="one-line description for the model"
          className="min-w-0 flex-1 border border-hairline bg-transparent px-2 py-1 font-serif text-[15px] text-ink placeholder:text-ink-faint focus:border-accent-navy focus:outline-none"
        />
        <button type="submit" disabled={!name.trim()} className="border border-hairline px-3 py-1 text-[12px] text-ink-muted hover:text-ink disabled:opacity-40">
          + Add category
        </button>
      </form>

      <div className="mt-10 border border-hairline bg-paper-soft p-4">
        <div className="font-serif text-[18px] text-ink">Re-run the classifier</div>
        <p className="mt-1 text-[12.5px] text-ink-muted">
          Rebuilds tags and summaries from the original text. Your entries are never changed, so this is always safe. A new
          category needs no migration: add it, then re-run.
        </p>
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => rerun("today")}
            disabled={running !== null}
            className="border border-ink bg-ink px-3.5 py-2 text-[12px] text-paper hover:opacity-90 disabled:opacity-50"
          >
            {running === "today" ? "Running…" : "Re-run today"}
          </button>
          <button
            onClick={() => rerun("all")}
            disabled={running !== null}
            className="border border-hairline px-3.5 py-2 text-[12px] text-ink hover:border-ink disabled:opacity-50"
          >
            {running === "all" ? "Running…" : "Re-run all days"}
          </button>
        </div>
      </div>
    </div>
  );
}
