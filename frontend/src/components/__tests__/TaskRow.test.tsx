import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { TaskRow } from "../TaskRow";
import { Item } from "@/lib/types";

vi.mock("@/lib/useCategories", () => ({
  useCategories: () => ({ categories: [{ id: "cat-1", slug: "books", name: "Books", sort_order: 30 }] }),
  categoryName: (categories: { id: string; name: string }[], id: string | null) =>
    categories.find((c) => c.id === id)?.name ?? null,
}));

function makeItem(overrides: Partial<Item>): Item {
  return {
    id: "id",
    item_type: "task",
    title: "Read a chapter",
    content_md: "",
    category_id: "cat-1",
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

describe("TaskRow", () => {
  it("shows an overdue label distinct from color alone", () => {
    render(
      <TaskRow
        item={makeItem({ due_date: "2020-01-01", overdue: true })}
        onOpen={() => {}}
        onToggle={() => {}}
        toggling={false}
      />,
    );
    expect(screen.getByText(/Overdue/)).toBeInTheDocument();
  });

  it("renders the category tag from the resolved category name", () => {
    render(<TaskRow item={makeItem({})} onOpen={() => {}} onToggle={() => {}} toggling={false} />);
    expect(screen.getByText("Books")).toBeInTheDocument();
  });

  it("strikes through a completed task's title", () => {
    render(
      <TaskRow
        item={makeItem({ status: "completed" })}
        onOpen={() => {}}
        onToggle={() => {}}
        toggling={false}
      />,
    );
    expect(screen.getByText("Read a chapter")).toHaveClass("line-through");
  });

  describe("completing an open task", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("plays a brief strike-then-fade before calling onToggle, without triggering onOpen", () => {
      const onToggle = vi.fn();
      const onOpen = vi.fn();
      render(<TaskRow item={makeItem({})} onOpen={onOpen} onToggle={onToggle} toggling={false} />);

      fireEvent.click(screen.getByRole("button", { name: /complete task/i }));
      expect(onToggle).not.toHaveBeenCalled();
      expect(onOpen).not.toHaveBeenCalled();

      act(() => vi.advanceTimersByTime(500));
      expect(onToggle).toHaveBeenCalledTimes(1);
      expect(onOpen).not.toHaveBeenCalled();
    });
  });

  it("reopening a completed task calls onToggle immediately", () => {
    const onToggle = vi.fn();
    render(<TaskRow item={makeItem({ status: "completed" })} onOpen={() => {}} onToggle={onToggle} toggling={false} />);
    fireEvent.click(screen.getByRole("button", { name: /reopen task/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
