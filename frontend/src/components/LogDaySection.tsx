"use client";

import { useState } from "react";
import { Archive as ArchiveIcon, Loader2 } from "lucide-react";
import { archiveLogEntry } from "@/lib/traceback";
import { dayHeading, entryTime, isAfterMidnight, splitMatches } from "@/lib/logDays";
import { ApiError, LogDay, LogEntry } from "@/lib/types";
import { useToast } from "./Toast";

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {splitMatches(text, query).map((part, index) =>
        part.match ? (
          <mark key={index} className="bg-accent-gold/30 text-ink">
            {part.text}
          </mark>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </>
  );
}

function EntryRow({ entry, query, onChanged }: { entry: LogEntry; query: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function archive() {
    setBusy(true);
    try {
      await archiveLogEntry(entry.id);
      onChanged();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not archive the entry.", "error");
      setBusy(false);
    }
  }

  return (
    <li className="group flex flex-wrap gap-x-5 gap-y-1 border-t border-hairline py-3">
      <div className="w-[76px] flex-none pt-1 text-[12px] text-ink-muted">
        {entryTime(entry.logged_at)}
        {isAfterMidnight(entry) && <div className="text-[10.5px] italic text-ink-faint">after midnight</div>}
      </div>
      <div className="min-w-0 flex-1 basis-[300px]">
        <div className="font-serif text-[18px] leading-snug text-ink">
          <Highlighted text={entry.text} query={query} />
        </div>
        {entry.labels.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {entry.labels.map((label) => (
              <span key={label} className="rounded-sm border border-hairline px-1.5 py-px text-[10.5px] text-ink-muted">
                {label}
              </span>
            ))}
          </div>
        )}
      </div>
      <button
        onClick={archive}
        disabled={busy}
        aria-label={`Archive entry: ${entry.text}`}
        className="self-start rounded border border-transparent p-1 text-ink-faint opacity-0 hover:border-hairline hover:text-ink focus:opacity-100 group-hover:opacity-100 disabled:opacity-50"
      >
        <ArchiveIcon size={13} />
      </button>
    </li>
  );
}

export function LogDaySection({
  day,
  isToday,
  query,
  classifying,
  onClassify,
  onChanged,
  showToday,
}: {
  day: LogDay;
  isToday: boolean;
  query: string;
  classifying: boolean;
  onClassify: (date: string) => void;
  onChanged: () => void;
  /** An empty today still renders so the day has a heading and a place for the classify button. */
  showToday?: boolean;
}) {
  const count = day.entries.length;
  const searching = query.trim().length > 0;
  return (
    <section className="mt-9" aria-label={dayHeading(day.log_date)}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-serif text-[24px] text-ink">{dayHeading(day.log_date)}</h2>
          <div className="mt-0.5 text-[11.5px] text-ink-muted">
            {isToday ? "Today · " : ""}
            {count} {count === 1 ? "entry" : "entries"}
          </div>
        </div>
        {!searching && count > 0 && !day.summary && (
          <button
            onClick={() => onClassify(day.log_date)}
            disabled={classifying}
            className="flex items-center gap-1.5 border border-ink bg-ink px-3.5 py-2 text-[12px] text-paper hover:opacity-90 disabled:opacity-50"
          >
            {classifying && <Loader2 size={12} className="animate-spin" />}
            {isToday ? "Classify today" : "Classify"}
          </button>
        )}
      </div>

      {day.summary && (
        <p className="mb-3 max-w-[640px] font-serif text-[17px] italic leading-relaxed text-ink">
          {day.summary}
          <span className="ml-2 align-middle font-mono text-[10.5px] not-italic text-ink-faint">Local summary</span>
        </p>
      )}
      {!searching && count > 0 && !day.summary && (
        <div className="mb-1 border border-dashed border-ink-muted px-3.5 py-2.5 text-[12px] text-ink-muted">
          Not classified yet. Tags and a summary appear after {isToday ? "“Classify today”" : "“Classify”"}.
        </div>
      )}
      {count === 0 && showToday && <div className="border-t border-hairline py-4 text-[13px] text-ink-muted">Nothing logged yet today.</div>}

      <ul>
        {day.entries.map((entry) => (
          <EntryRow key={entry.id} entry={entry} query={query} onChanged={onChanged} />
        ))}
      </ul>
    </section>
  );
}
