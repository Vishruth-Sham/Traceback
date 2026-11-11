import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { CaptureBox } from "../CaptureBox";
import { Capture } from "@/lib/types";

const createCapture = vi.fn();
const getCapture = vi.fn();
const getItem = vi.fn();
const retryCapture = vi.fn();
const undoCaptureFiling = vi.fn();
const toastPush = vi.fn();

vi.mock("@/lib/apiClient", () => ({ newIdempotencyKey: () => "key-1" }));
vi.mock("@/lib/traceback", () => ({
  createCapture: (...args: unknown[]) => createCapture(...args),
  getCapture: (...args: unknown[]) => getCapture(...args),
  getItem: (...args: unknown[]) => getItem(...args),
  retryCapture: (...args: unknown[]) => retryCapture(...args),
  undoCaptureFiling: (...args: unknown[]) => undoCaptureFiling(...args),
}));
vi.mock("../Toast", () => ({ useToast: () => ({ push: toastPush }) }));

function makeCapture(overrides: Partial<Capture> = {}, state = "pending"): Capture {
  return {
    id: "cap-1",
    source_type: "typed",
    raw_text: "Write tests tomorrow",
    original_description: null,
    original_url: null,
    captured_at: null,
    source_date: null,
    source_timezone: null,
    timestamp_origin: "client_supplied",
    metadata: {},
    corrections: {},
    asset_ids: [],
    resulting_item_ids: [],
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    processing: { generation: 1, state, transcript: null, error_code: null, error_message: null, attempt_count: 0, lease_expires_at: null, queued_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null },
    action_id: null,
    ...overrides,
  } as Capture;
}

beforeEach(() => {
  vi.useFakeTimers();
  [createCapture, getCapture, getItem, retryCapture, undoCaptureFiling, toastPush].forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CaptureBox", () => {
  it("saves a general capture, shows what was filed, and undoes the whole filing", async () => {
    createCapture.mockResolvedValue(makeCapture());
    getCapture.mockResolvedValue(makeCapture({ resulting_item_ids: ["item-1"], version: 3 }, "resolved"));
    getItem.mockResolvedValue({ id: "item-1", item_type: "task", title: "Write tests" });
    undoCaptureFiling.mockResolvedValue({ capture: makeCapture({ version: 4 }, "failed"), item_ids: ["item-1"] });
    const onChanged = vi.fn();

    render(<CaptureBox onChanged={onChanged} />);
    fireEvent.change(screen.getByLabelText("Add anything"), { target: { value: "Write tests tomorrow" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });
    expect(createCapture).toHaveBeenCalledWith(
      expect.objectContaining({ source_type: "typed", raw_text: "Write tests tomorrow", timestamp_origin: "client_supplied" }),
      "key-1",
    );
    expect(createCapture.mock.calls[0][0].metadata).toBeUndefined();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(screen.getByRole("listitem")).toHaveTextContent("task · Write tests");
    expect(screen.getByText("filed")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /undo/ }));
    });
    expect(undoCaptureFiling).toHaveBeenCalledWith("cap-1", 3);
    expect(screen.getByText(/filing undone/)).toBeInTheDocument();
  });
});
