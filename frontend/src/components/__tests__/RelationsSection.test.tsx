import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RelationsSection } from "../RelationsSection";
import { Item } from "@/lib/types";

const createRelation = vi.fn();
const deleteRelation = vi.fn();
const getItem = vi.fn();
const listItems = vi.fn();
const toastPush = vi.fn();

vi.mock("@/lib/traceback", () => ({
  createRelation: (...args: unknown[]) => createRelation(...args),
  deleteRelation: (...args: unknown[]) => deleteRelation(...args),
  getItem: (...args: unknown[]) => getItem(...args),
  listItems: (...args: unknown[]) => listItems(...args),
}));

vi.mock("../Toast", () => ({
  useToast: () => ({ push: toastPush }),
}));

function makeItem(overrides: Partial<Item>): Item {
  return {
    id: "item-1",
    item_type: "task",
    title: "Ship the release",
    content_md: "",
    category_id: null,
    placement_state: "inbox",
    attributes: {},
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    inbox_entered_at: "2026-01-01T00:00:00Z",
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

beforeEach(() => {
  createRelation.mockReset();
  deleteRelation.mockReset();
  getItem.mockReset();
  getItem.mockResolvedValue(makeItem({ id: "unused-default", title: "Unnamed" }));
  listItems.mockReset();
  toastPush.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RelationsSection", () => {
  it("hides an already-linked item from the link-search results", async () => {
    const item = makeItem({
      id: "item-1",
      relations: [
        { id: "rel-1", from_item_id: "item-1", relation: "related_to", to_item_id: "item-2", created_at: "2026-01-01T00:00:00Z" },
      ],
    });
    listItems.mockResolvedValue({
      items: [
        { id: "item-2", title: "Already linked task", item_type: "task" },
        { id: "item-3", title: "Not yet linked task", item_type: "task" },
      ],
      next_cursor: null,
    });

    render(<RelationsSection item={item} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("Link to another item…"), { target: { value: "task" } });

    await waitFor(() => expect(screen.getByText("Not yet linked task")).toBeInTheDocument());
    expect(screen.queryByText("Already linked task")).not.toBeInTheDocument();
  });

  it("hides an already-linked item regardless of relation direction", async () => {
    const item = makeItem({
      id: "item-1",
      relations: [
        // item-1 is the target here, not the source -- still already linked.
        { id: "rel-1", from_item_id: "item-2", relation: "related_to", to_item_id: "item-1", created_at: "2026-01-01T00:00:00Z" },
      ],
    });
    listItems.mockResolvedValue({
      items: [{ id: "item-2", title: "Already linked task", item_type: "task" }],
      next_cursor: null,
    });

    render(<RelationsSection item={item} onChanged={() => {}} />);
    // A distinct query string from the other tests: SWR's cache is global,
    // so reusing "task" here would serve a different test's cached result
    // instead of calling this test's `listItems` mock.
    fireEvent.change(screen.getByPlaceholderText("Link to another item…"), { target: { value: "reverse-direction" } });

    await waitFor(() => expect(listItems).toHaveBeenCalled());
    expect(screen.queryByText("Already linked task")).not.toBeInTheDocument();
  });

  it("links an unrelated result and clears the search", async () => {
    const item = makeItem({ id: "item-1" });
    listItems.mockResolvedValue({
      items: [{ id: "item-3", title: "Linkable note", item_type: "note", version: 2 }],
      next_cursor: null,
    });
    createRelation.mockResolvedValue({ id: "rel-new" });
    const onChanged = vi.fn();

    render(<RelationsSection item={item} onChanged={onChanged} />);
    fireEvent.change(screen.getByPlaceholderText("Link to another item…"), { target: { value: "note" } });

    const result = await screen.findByText("Linkable note");
    await act(async () => {
      fireEvent.click(result);
    });

    expect(createRelation).toHaveBeenCalledWith({
      from_item_id: "item-1",
      from_expected_version: 1,
      relation: "related_to",
      to_item_id: "item-3",
      to_expected_version: 2,
    });
    expect(onChanged).toHaveBeenCalled();
    expect(toastPush).toHaveBeenCalledWith("Linked.", "success");
  });

  it("renders existing links as tags below the link input, with the other item's title", async () => {
    const item = makeItem({
      id: "item-1",
      version: 3,
      relations: [
        { id: "rel-part-of", from_item_id: "item-1", relation: "part_of", to_item_id: "folder-1", created_at: "2026-01-01T00:00:00Z" },
        { id: "rel-related", from_item_id: "other-1", relation: "related_to", to_item_id: "item-1", created_at: "2026-01-01T00:00:00Z" },
      ],
    });
    getItem.mockImplementation((id: string) => {
      if (id === "folder-1") return Promise.resolve(makeItem({ id: "folder-1", item_type: "folder", title: "Traceback", version: 5 }));
      if (id === "other-1") return Promise.resolve(makeItem({ id: "other-1", title: "Sibling task", version: 2 }));
      throw new Error(`unexpected getItem(${id})`);
    });
    deleteRelation.mockResolvedValue({ deleted_relation_id: "rel-part-of" });
    const onChanged = vi.fn();

    render(<RelationsSection item={item} onChanged={onChanged} />);

    // Tags render below the "Link to another item…" input, not above it.
    const input = screen.getByPlaceholderText("Link to another item…");
    const folderTag = await screen.findByText("Traceback");
    expect(input.compareDocumentPosition(folderTag) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await screen.findByText("Sibling task");

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Unlink Traceback"));
    });

    expect(deleteRelation).toHaveBeenCalledWith("rel-part-of", item.version, 5);
    expect(onChanged).toHaveBeenCalled();
    expect(toastPush).toHaveBeenCalledWith("Unlinked.", "success");
  });
});
