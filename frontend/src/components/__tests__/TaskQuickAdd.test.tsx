import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { TaskQuickAdd } from "../TaskQuickAdd";
import { Capture } from "@/lib/types";

const createCapture = vi.fn();
const getCapture = vi.fn();
const retryCapture = vi.fn();
const toastPush = vi.fn();
const newIdempotencyKey = vi.fn(() => "capture-key-1");

vi.mock("@/lib/apiClient", () => ({
  newIdempotencyKey: () => newIdempotencyKey(),
}));

vi.mock("@/lib/traceback", () => ({
  createCapture: (...args: unknown[]) => createCapture(...args),
  getCapture: (...args: unknown[]) => getCapture(...args),
  retryCapture: (...args: unknown[]) => retryCapture(...args),
}));

vi.mock("../Toast", () => ({
  useToast: () => ({ push: toastPush }),
}));

function makeCapture(overrides: Partial<Capture>): Capture {
  return {
    id: "cap-1",
    source_type: "typed",
    raw_text: "Email Sarah Friday afternoon about the apartment move",
    original_description: null,
    original_url: null,
    captured_at: null,
    source_date: null,
    source_timezone: null,
    timestamp_origin: "unknown",
    metadata: {},
    corrections: {},
    asset_ids: [],
    resulting_item_ids: [],
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    processing: { generation: 1, state: "pending", transcript: null, error_code: null, error_message: null, attempt_count: 0, lease_expires_at: null, queued_at: "2026-01-01T00:00:00Z", started_at: null, finished_at: null },
    action_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  createCapture.mockReset();
  getCapture.mockReset();
  retryCapture.mockReset();
  toastPush.mockReset();
  newIdempotencyKey.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TaskQuickAdd", () => {
  it("submits the exact free text as a typed capture and clears the input immediately", async () => {
    createCapture.mockResolvedValue(makeCapture({}));
    render(<TaskQuickAdd onTaskCreated={() => {}} />);

    const input = screen.getByLabelText("Add a task") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Email Sarah Friday afternoon about the apartment move" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(input.value).toBe("");
    expect(createCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        source_type: "typed",
        raw_text: "Email Sarah Friday afternoon about the apartment move",
        captured_at: expect.any(String),
        source_timezone: expect.any(String),
        timestamp_origin: "client_supplied",
        metadata: { processing_profile: "task_quick_add" },
      }),
      "capture-key-1",
    );
    await waitFor(() => expect(screen.getByText(/saved — awaiting processing/)).toBeInTheDocument());
    expect(screen.getByText(/Email Sarah Friday afternoon/)).toBeInTheDocument();
  });

  it("does not submit blank input", () => {
    render(<TaskQuickAdd onTaskCreated={() => {}} />);
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(createCapture).not.toHaveBeenCalled();
  });

  it("polls until resolved, then notifies the parent and removes the pending card", async () => {
    vi.useFakeTimers();
    createCapture.mockResolvedValue(makeCapture({ processing: { ...makeCapture({}).processing, state: "pending" } }));
    getCapture.mockResolvedValue(makeCapture({ processing: { ...makeCapture({}).processing, state: "resolved" } }));
    const onTaskCreated = vi.fn();

    render(<TaskQuickAdd onTaskCreated={onTaskCreated} />);
    const input = screen.getByLabelText("Add a task");
    fireEvent.change(input, { target: { value: "Buy milk" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    expect(getCapture).toHaveBeenCalledWith("cap-1");
    expect(onTaskCreated).toHaveBeenCalled();
    expect(screen.queryByText(/Buy milk/)).not.toBeInTheDocument();
  });

  it("shows a failed capture with retry and a manual-resolve link that preserves the original text", async () => {
    vi.useFakeTimers();
    createCapture.mockResolvedValue(makeCapture({}));
    getCapture.mockResolvedValue(
      makeCapture({
        processing: {
          generation: 1,
          state: "failed",
          transcript: null,
          error_code: "InterpretationError",
          error_message: "model did not return a schema-valid proposal",
          attempt_count: 1,
          lease_expires_at: null,
          queued_at: "2026-01-01T00:00:00Z",
          started_at: null,
          finished_at: null,
        },
      }),
    );

    render(<TaskQuickAdd onTaskCreated={() => {}} />);
    const input = screen.getByLabelText("Add a task");
    fireEvent.change(input, { target: { value: "Something ambiguous" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });

    expect(screen.getByText(/could not understand this/)).toBeInTheDocument();
    expect(screen.getByText(/Something ambiguous/)).toBeInTheDocument();
    const manualLinks = screen.getAllByRole("link", { name: "add manually" });
    const manualLink = manualLinks[manualLinks.length - 1];
    expect(manualLink.getAttribute("href")).toContain("raw=Something");
    expect(manualLink.getAttribute("href")).toContain("captureId=cap-1");
  });

  it("keeps the original text visible and offers retry when saving the capture itself fails", async () => {
    createCapture.mockRejectedValue(new Error("network down"));
    render(<TaskQuickAdd onTaskCreated={() => {}} />);
    const input = screen.getByLabelText("Add a task");
    fireEvent.change(input, { target: { value: "Will not lose this" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });

    expect(await screen.findByText(/could not save/)).toBeInTheDocument();
    expect(screen.getByText(/Will not lose this/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("reuses the capture idempotency key after an uncertain save failure", async () => {
    createCapture.mockRejectedValueOnce(new Error("response lost")).mockResolvedValueOnce(makeCapture({}));
    render(<TaskQuickAdd onTaskCreated={() => {}} />);
    fireEvent.change(screen.getByLabelText("Add a task"), { target: { value: "Pay rent tomorrow" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(await screen.findByRole("button", { name: /retry/i }));
    await screen.findByText(/saved — awaiting processing/);

    expect(createCapture).toHaveBeenCalledTimes(2);
    expect(createCapture.mock.calls[0][1]).toBe("capture-key-1");
    expect(createCapture.mock.calls[1][1]).toBe("capture-key-1");
    expect(createCapture.mock.calls[1][0]).toEqual(createCapture.mock.calls[0][0]);
    expect(newIdempotencyKey).toHaveBeenCalledTimes(1);
  });
});
