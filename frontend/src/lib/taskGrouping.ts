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
