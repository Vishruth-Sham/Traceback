import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NoteQuickAdd } from "../NoteQuickAdd";

const createCapture = vi.fn();
const listLocations = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/apiClient", () => ({ newIdempotencyKey: () => "note-key" }));
vi.mock("@/lib/traceback", () => ({
  createCapture: (...args: unknown[]) => createCapture(...args),
  listLocations: (...args: unknown[]) => listLocations(...args),
  getCapture: vi.fn(), correctCapture: vi.fn(), retryCapture: vi.fn(), interpretCaptureManually: vi.fn(), createItem: vi.fn(),
}));
vi.mock("../Toast", () => ({ useToast: () => ({ push }) }));

beforeEach(() => {
  createCapture.mockReset();
  listLocations.mockReturnValue(new Promise(() => undefined));
});

describe("NoteQuickAdd", () => {
  it("renders compose and blocks an empty note", () => {
    render(<NoteQuickAdd />);
    expect(screen.getByRole("heading", { name: "Quick add note" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find location" })).toBeDisabled();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("persists the exact body, title, hint, timezone and one idempotency key", async () => {
    listLocations.mockResolvedValue({ items: [{ kind: "category", id: "other", title: "Other", path: "Other", category_id: "other", version: null }], next_cursor: null });
    createCapture.mockResolvedValue({
      id: "capture-1", raw_text: "Line 1\n\n**exact**", metadata: { processing_profile: "note_quick_add" }, corrections: {}, version: 1,
      processing: { state: "pending", generation: 1, proposal: null },
    });
    render(<NoteQuickAdd />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Optional title" } });
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Line 1\n\n**exact**" } });
    fireEvent.change(screen.getByLabelText("Placement hint"), { target: { value: "my reading folder" } });
    fireEvent.click(screen.getByRole("button", { name: "Find location" }));
    await waitFor(() => expect(createCapture).toHaveBeenCalledTimes(1));
    expect(createCapture).toHaveBeenCalledWith(expect.objectContaining({
      source_type: "typed", raw_text: "Line 1\n\n**exact**", timestamp_origin: "client_supplied",
      captured_at: expect.any(String), source_timezone: expect.any(String),
      metadata: { processing_profile: "note_quick_add", supplied_title: "Optional title", placement_hint: "my reading folder" },
    }), "note-key");
    expect(await screen.findByRole("heading", { name: "Review note" })).toBeInTheDocument();
  });
});
