"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Search as SearchIcon } from "lucide-react";
import { addLogEntry, classifyLog, listLogDays, searchLog } from "@/lib/traceback";
import { groupByDay } from "@/lib/logDays";
import { ApiError, LogDay, LogDaysPage } from "@/lib/types";
import { LogDaySection } from "@/components/LogDaySection";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";

const REFRESH_MS = 15000;

export default function LogPage() {
  const toast = useToast();
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [classifying, setClassifying] = useState<string | null>(null);
  const [older, setOlder] = useState<LogDay[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // Revalidating on focus and on a short interval is how an entry Claude logs over MCP shows up on its own.
  const first = useSWR<LogDaysPage>("log-days", () => listLogDays(), {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: true,
  });
  const trimmed = query.trim();
  const search = useSWR(trimmed ? `log-search:${trimmed}` : null, () => searchLog(trimmed));

  const today = first.data?.today;
  const days = useMemo<LogDay[]>(() => {
    if (!first.data) return [];
    const seen = new Set(first.data.days.map((d) => d.log_date));
    const merged = [...first.data.days, ...older.filter((d) => !seen.has(d.log_date))];
    if (today && !seen.has(today)) merged.unshift({ log_date: today, summary: null, entries: [] });
    return merged;
  }, [first.data, older, today]);
  const hasMore = (nextBefore === undefined ? first.data?.next_before : nextBefore) != null;

  async function refresh() {
    await Promise.all([first.mutate(), search.mutate()]);
    setOlder([]);
    setNextBefore(undefined);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || adding) return;
    setAdding(true);
    try {
      await addLogEntry(value);
      setText("");
      await refresh();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not add the entry.", "error");
    } finally {
      setAdding(false);
      input.current?.focus();
    }
  }

  async function classify(date: string) {
    setClassifying(date);
    try {
      await classifyLog({ date });
      await refresh();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not classify the day.", "error");
    } finally {
      setClassifying(null);
    }
  }

  async function loadOlder() {
    const before = nextBefore === undefined ? first.data?.next_before : nextBefore;
    if (!before) return;
    setLoadingOlder(true);
    try {
      const page = await listLogDays(before);
      setOlder((current) => [...current, ...page.days]);
      setNextBefore(page.next_before);
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not load earlier days.", "error");
    } finally {
      setLoadingOlder(false);
    }
  }

  const searchDays = useMemo(() => groupByDay(search.data?.entries ?? []), [search.data]);

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <div className="flex items-start justify-between gap-4">
        <PageHeader eyebrow="free text, one line at a time" title="Daily log" />
        <Link href="/log/categories" className="mt-2 flex-none text-[12px] text-accent-navy hover:underline">
          Edit categories →
        </Link>
      </div>

      <form onSubmit={submit} className="flex items-center gap-3 border border-hairline bg-paper-soft px-3.5 py-2.5">
        <input
          ref={input}
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          aria-label="Log something"
          placeholder="Log something…"
          className="min-w-0 flex-1 border-none bg-transparent font-serif text-[19px] text-ink placeholder:text-ink-muted focus:outline-none"
        />
        <button
          type="submit"
          disabled={adding || !text.trim()}
          className="border border-hairline px-2 py-1 text-[11px] text-ink-muted hover:text-ink disabled:opacity-40"
        >
          ↵ Add
        </button>
      </form>
      <div className="mb-5 mt-2 text-[11px] text-ink-muted">Or tell Claude: “log: lunch with Priya”.</div>

      <div className="flex items-center gap-2 border border-hairline px-3.5 py-2.5">
        <SearchIcon size={14} className="text-ink-faint" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the log"
          placeholder="Search the log"
          className="min-w-0 flex-1 border-none bg-transparent font-serif text-[17px] text-ink placeholder:text-ink-muted focus:outline-none"
        />
      </div>

      {trimmed ? (
        <>
          {search.isLoading && <LoadingState label="Searching…" />}
          {search.error && <ErrorState message="Search failed." onRetry={() => search.mutate()} />}
          {!search.isLoading && !search.error && searchDays.length === 0 && <EmptyState title={`No entries match “${trimmed}”.`} />}
          {searchDays.map((day) => (
            <LogDaySection
              key={day.log_date}
              day={day}
              isToday={day.log_date === today}
              query={trimmed}
              classifying={false}
              onClassify={classify}
              onChanged={refresh}
            />
          ))}
        </>
      ) : (
        <>
          {first.isLoading && <LoadingState />}
          {first.error && <ErrorState message="Could not load the log." onRetry={() => first.mutate()} />}
          {first.data && first.data.days.length === 0 && (
            <EmptyState title="Nothing logged yet." hint="Type a line above to start. There is no format to follow." />
          )}
          {days.map((day) => (
            <LogDaySection
              key={day.log_date}
              day={day}
              isToday={day.log_date === today}
              showToday={day.log_date === today}
              query=""
              classifying={classifying === day.log_date}
              onClassify={classify}
              onChanged={refresh}
            />
          ))}
          {hasMore && (
            <button
              onClick={loadOlder}
              disabled={loadingOlder}
              className="mt-8 border border-hairline px-3.5 py-2 text-[12px] text-ink-muted hover:text-ink disabled:opacity-50"
            >
              {loadingOlder ? "Loading…" : "Load earlier days"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
