import { describe, expect, it } from "vitest";
import { groupOpenTasks, formatDeadline } from "../taskGrouping";
import { Item } from "../types";

function makeItem(overrides: Partial<Item>): Item {
  return {
    id: "id",
    item_type: "task",
    title: "Task",
    content_md: "",
    category_id: null,
    placement_state: "classified",
    attributes: {},
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    inbox_entered_at: null,
    last_user_action_at: "2026-01-01T00:00:00Z",
    status: "open",
    due_date: null,
    due_time: null,
    due_timezone: null,
    completed_at: null,
    overdue: null,
    relations: [],
    action_id: null,
    source_ids: [],
    asset_ids: [],
    ...overrides,
  };
}

describe("groupOpenTasks", () => {
  it("buckets items by overdue, upcoming, and undated while preserving server order", () => {
    const overdueTask = makeItem({ id: "1", due_date: "2020-01-01", overdue: true });
    const upcomingTask = makeItem({ id: "2", due_date: "2099-01-01", overdue: false });
    const undatedTask = makeItem({ id: "3", due_date: null, overdue: null });
    const secondUndated = makeItem({ id: "4", due_date: null, overdue: null });

    const groups = groupOpenTasks([overdueTask, upcomingTask, undatedTask, secondUndated]);

    expect(groups.overdue.map((i) => i.id)).toEqual(["1"]);
    expect(groups.upcoming.map((i) => i.id)).toEqual(["2"]);
    expect(groups.undated.map((i) => i.id)).toEqual(["3", "4"]);
  });

  it("treats a dated but not-yet-overdue task as upcoming even without an explicit overdue flag", () => {
    const task = makeItem({ id: "5", due_date: "2099-06-01", overdue: false });
    const groups = groupOpenTasks([task]);
    expect(groups.upcoming).toHaveLength(1);
    expect(groups.overdue).toHaveLength(0);
  });

  it("does not reorder items within a bucket", () => {
    const a = makeItem({ id: "a", due_date: "2099-01-01", overdue: false });
    const b = makeItem({ id: "b", due_date: "2099-02-01", overdue: false });
    const groups = groupOpenTasks([b, a]);
    expect(groups.upcoming.map((i) => i.id)).toEqual(["b", "a"]);
  });
});

describe("formatDeadline", () => {
  it("returns null when there is no due date", () => {
    expect(formatDeadline({ due_date: null, due_time: null, due_timezone: null })).toBeNull();
  });

  it("formats a date-only deadline without a time", () => {
    const label = formatDeadline({ due_date: "2026-03-05", due_time: null, due_timezone: null });
    expect(label).toBe("Mar 5");
  });

  it("formats a timed deadline with 12-hour clock", () => {
    const label = formatDeadline({ due_date: "2026-03-05", due_time: "15:30:00", due_timezone: "UTC" });
    expect(label).toBe("Mar 5, 3:30 PM");
  });

  it("formats midnight and noon correctly", () => {
    expect(formatDeadline({ due_date: "2026-03-05", due_time: "00:00:00", due_timezone: "UTC" })).toBe(
      "Mar 5, 12:00 AM",
    );
    expect(formatDeadline({ due_date: "2026-03-05", due_time: "12:00:00", due_timezone: "UTC" })).toBe(
      "Mar 5, 12:00 PM",
    );
  });
});
