import { render, screen, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { beforeEach, expect, it, vi } from "vitest";
import { Item } from "@/lib/types";
import NoteDetailPage from "./page";

const getItem = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "note-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/traceback", () => ({ getItem: (...args: unknown[]) => getItem(...args) }));
vi.mock("@/lib/useCategories", () => ({
  useCategories: () => ({ categories: [{ id: "learning", slug: "learning", name: "Learning" }], isLoading: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ push: vi.fn() }) }));
vi.mock("@/components/RelationsSection", () => ({ RelationsSection: () => null }));
vi.mock("@/components/HistoryList", () => ({ HistoryList: () => null }));

function item(id: string, title: string, itemType: Item["item_type"], parentId?: string): Item {
  return {
    id, title, item_type: itemType, category_id: "learning", content_md: "",
    placement_state: "classified", attributes: {}, version: 1,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    archived_at: null, inbox_entered_at: null, last_user_action_at: "2026-01-01T00:00:00Z",
    status: null, due_date: null, due_time: null, due_timezone: null,
    completed_at: null, overdue: null, action_id: null, source_ids: [], asset_ids: [],
    relations: parentId ? [{ id: `${id}-parent`, from_item_id: id, relation: "part_of", to_item_id: parentId, created_at: "2026-01-01T00:00:00Z" }] : [],
  };
}

beforeEach(() => {
  const items = new Map([
    ["note-1", item("note-1", "smart-filtering-deep-dive", "note", "interview-prep")],
    ["interview-prep", item("interview-prep", "Interview prep", "folder")],
  ]);
  getItem.mockReset();
  getItem.mockImplementation((id: string) => Promise.resolve(items.get(id)));
});

it("shows the full note location and links back to its immediate folder", async () => {
  render(<SWRConfig value={{ provider: () => new Map() }}><NoteDetailPage /></SWRConfig>);

  const location = await screen.findByRole("navigation", { name: "Note location" });
  expect(await within(location).findByRole("link", { name: "Interview prep" })).toHaveAttribute("href", "/folders/interview-prep");
  expect(within(location).getByRole("link", { name: "Learning" })).toHaveAttribute("href", "/category/learning");
  expect(within(location).getByRole("link", { name: "Back to Interview prep" })).toHaveAttribute("href", "/folders/interview-prep");
  expect(within(location).getByText("smart-filtering-deep-dive")).toHaveAttribute("aria-current", "page");
});
