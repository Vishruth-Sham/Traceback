import { LogDay, LogEntry } from "./types";

function parseDay(logDate: string): Date {
  const [year, month, day] = logDate.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function dayHeading(logDate: string): string {
  return parseDay(logDate).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

export function entryTime(loggedAt: string): string {
  return new Date(loggedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function localDate(loggedAt: string): string {
  const d = new Date(loggedAt);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** True when the entry's wall-clock date differs from the log day it was filed under (a late-night entry). */
export function isAfterMidnight(entry: LogEntry): boolean {
  return localDate(entry.logged_at) !== entry.log_date;
}

/** Group search hits (newest first) into days, keeping each day's entries in time order. */
export function groupByDay(entries: LogEntry[]): LogDay[] {
  const days = new Map<string, LogEntry[]>();
  for (const entry of entries) {
    const list = days.get(entry.log_date) ?? [];
    list.push(entry);
    days.set(entry.log_date, list);
  }
  return [...days.entries()]
    .sort(([a], [b]) => (a < b ? 1 : -1))
    .map(([log_date, list]) => ({
      log_date,
      summary: null,
      entries: [...list].sort((a, b) => a.logged_at.localeCompare(b.logged_at)),
    }));
}

/** Split text around case-insensitive matches of `query` so the caller can highlight them. */
export function splitMatches(text: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim();
  if (!needle) return [{ text, match: false }];
  const parts: { text: string; match: boolean }[] = [];
  const lower = text.toLowerCase();
  const target = needle.toLowerCase();
  let from = 0;
  for (;;) {
    const at = lower.indexOf(target, from);
    if (at < 0) break;
    if (at > from) parts.push({ text: text.slice(from, at), match: false });
    parts.push({ text: text.slice(at, at + target.length), match: true });
    from = at + target.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), match: false });
  return parts.length ? parts : [{ text, match: false }];
}
