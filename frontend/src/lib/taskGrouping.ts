import { Item } from "./types";

export interface TaskGroups {
  overdue: Item[];
  upcoming: Item[];
  undated: Item[];
}

// Server order (backend/api.py `tasks`) is already due_date asc, timed-before-
// date-only, undated last. This only buckets that same order for section
// headers; it must not re-sort within a bucket.
export function groupOpenTasks(items: Item[]): TaskGroups {
  const groups: TaskGroups = { overdue: [], upcoming: [], undated: [] };
  for (const item of items) {
    if (item.due_date === null) {
      groups.undated.push(item);
    } else if (item.overdue) {
      groups.overdue.push(item);
    } else {
      groups.upcoming.push(item);
    }
  }
  return groups;
}

export function formatDeadline(item: Pick<Item, "due_date" | "due_time" | "due_timezone">): string | null {
  if (!item.due_date) return null;
  const date = new Date(`${item.due_date}T00:00:00`);
  const dateLabel = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (item.due_time) {
    const [h, m] = item.due_time.split(":");
    const hour = Number(h);
    const suffix = hour >= 12 ? "PM" : "AM";
    const hour12 = ((hour + 11) % 12) + 1;
    return `${dateLabel}, ${hour12}:${m} ${suffix}`;
  }
  return dateLabel;
}

export interface DayGroups {
  overdue: Item[];
  due: Item[];
  done: Item[];
}

/** A local calendar day as YYYY-MM-DD, matching the format of `due_date`. */
export function toDayString(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function isDayString(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(new Date(`${value}T00:00:00`).getTime());
}

export function shiftDay(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00`);
  date.setDate(date.getDate() + days);
  return toDayString(date);
}

export function formatDayLabel(day: string, today: string): string {
  if (day === today) return "Today";
  if (day === shiftDay(today, 1)) return "Tomorrow";
  if (day === shiftDay(today, -1)) return "Yesterday";
  const date = new Date(`${day}T00:00:00`);
  const sameYear = day.slice(0, 4) === today.slice(0, 4);
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

// Buckets tasks for one day. Overdue carry-over only shows when looking at
// today, since "overdue as of a past or future day" is not useful. Server order
// is preserved within each bucket, as in groupOpenTasks.
export function groupTasksForDay(open: Item[], completed: Item[], day: string, today: string): DayGroups {
  const groups: DayGroups = { overdue: [], due: [], done: [] };
  for (const item of open) {
    if (item.due_date === day) groups.due.push(item);
    else if (day === today && item.due_date !== null && item.due_date < day) groups.overdue.push(item);
  }
  for (const item of completed) {
    if (item.due_date === day) groups.done.push(item);
  }
  return groups;
}
