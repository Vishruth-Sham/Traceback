import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import { ApiError, Capture } from "@/lib/types";
import { CommandReviewCard } from "../CommandReviewCard";
import { CAPS, fakeVoice, makeVoiceCapture, noOperationProposal, taskProposal, WithVoice } from "./helpers";

const acceptProposal = vi.fn();
const correctTranscript = vi.fn();
const archiveCapture = vi.fn();
const archiveItem = vi.fn();
const getCapture = vi.fn();
const retryCapture = vi.fn();
const interpretCaptureManually = vi.fn();
const listLocations = vi.fn();
const toastPush = vi.fn();

vi.mock("@/lib/voice", async (original) => ({
  ...(await original<typeof import("@/lib/voice")>()),
  acceptProposal: (...a: unknown[]) => acceptProposal(...a),
  correctTranscript: (...a: unknown[]) => correctTranscript(...a),
}));
vi.mock("@/lib/traceback", () => ({
  archiveCapture: (...a: unknown[]) => archiveCapture(...a),
  archiveItem: (...a: unknown[]) => archiveItem(...a),
  getCapture: (...a: unknown[]) => getCapture(...a),
  retryCapture: (...a: unknown[]) => retryCapture(...a),
  interpretCaptureManually: (...a: unknown[]) => interpretCaptureManually(...a),
  listLocations: (...a: unknown[]) => listLocations(...a),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ push: toastPush }) }));

const LOCATIONS = [
  { kind: "category", id: "cat-learning", title: "Learning", path: "Learning", category_id: "cat-learning", version: null },
  { kind: "folder", id: "f-db", title: "Database Systems", path: "Learning / Database Systems", category_id: "cat-learning", version: 3 },
  { kind: "project", id: "p-kitchen", title: "Kitchen renovation", path: "Projects / Kitchen renovation", category_id: "cat-projects", version: 2 },
];

function renderCard(capture: Capture, voice = fakeVoice(), extra: { onChanged?: () => void; onDismiss?: () => void; variant?: "tray" | "inbox" } = {}) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <WithVoice value={voice}>
        <CommandReviewCard capture={capture} variant={extra.variant ?? "inbox"} onChanged={extra.onChanged ?? (() => undefined)} onDismiss={extra.onDismiss} />
      </WithVoice>
    </SWRConfig>,
  );
}

beforeEach(() => {
  for (const mock of [acceptProposal, correctTranscript, archiveCapture, archiveItem, getCapture, retryCapture, interpretCaptureManually, listLocations, toastPush]) mock.mockReset();
  listLocations.mockResolvedValue({ items: LOCATIONS, next_cursor: null });
  getCapture.mockResolvedValue(makeVoiceCapture());
});
afterEach(() => vi.useRealTimers());

const resultFor = (title = "Submit the report", item_type: "task" | "note" = "task") => ({
  capture: makeVoiceCapture({ state: "resolved" }),
  items: [{ id: "item-1", item_type, title, version: 1 }],
  action_id: "act-1",
});

describe("stage states", () => {
  it("shows Saved • transcribing while pending, with an audio player and the processor wait state after 20 s", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-26T04:44:30Z")); // 28 s after created_at
    renderCard(makeVoiceCapture({ state: "pending" }));
    expect(screen.getAllByText(/Saved • transcribing/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Recording")).toHaveAttribute("src", "/api/v1/assets/asset-1/content");
    await act(async () => vi.advanceTimersByTime(1600)); // first poll tick updates "now"
    expect(screen.getByText("Waiting for the local processor…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Type it instead" })).toBeInTheDocument();
  });

  it("polls while pending and adopts the fetched review state", async () => {
    vi.useFakeTimers();
    getCapture.mockResolvedValue(makeVoiceCapture({ proposal: taskProposal() }));
    renderCard(makeVoiceCapture({ state: "pending" }));
    await act(async () => vi.advanceTimersByTime(1600));
    expect(getCapture).toHaveBeenCalledWith("cap-1");
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });

  it("explains a no_speech failure, keeps the audio, and offers Retry, Type it instead and Discard", () => {
    const failed = makeVoiceCapture({ state: "failed" });
    failed.processing.error_code = "no_speech";
    renderCard(failed);
    expect(screen.getByRole("alert")).toHaveTextContent("No speech was detected. Your recording is saved.");
    expect(screen.getByLabelText("Recording")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Type it instead" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard" })).toBeInTheDocument();
  });

  it("disables Retry with a reason while voice is off, and Type it instead completes the capture by hand", async () => {
    const failed = makeVoiceCapture({ state: "failed" });
    failed.processing.error_code = "TranscriptionError";
    renderCard(failed, fakeVoice({ capabilities: { ...CAPS, enabled: false, accepts_audio: false }, disabledReason: "Voice commands are turned off on this server" }));
    const retry = screen.getByRole("button", { name: /Retry/ });
    expect(retry).toBeDisabled();
    expect(retry).toHaveAttribute("title", "Voice processing is turned off");
    interpretCaptureManually.mockResolvedValue({ capture: makeVoiceCapture({ state: "resolved" }), items: [], action_id: "a" });
    fireEvent.click(screen.getByRole("button", { name: "Type it instead" }));
    const panel = screen.getByRole("group", { name: "Type it instead" });
    fireEvent.change(within(panel).getByLabelText("Text"), { target: { value: "Call the plumber" } });
    fireEvent.change(within(panel).getByLabelText("Title"), { target: { value: "Call the plumber" } });
    fireEvent.click(within(panel).getByLabelText("Task"));
    fireEvent.click(within(panel).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(interpretCaptureManually).toHaveBeenCalled());
    expect(interpretCaptureManually).toHaveBeenCalledWith("cap-1", {
      expected_version: 2,
      expected_generation: 1,
      items: [{ kind: "create", item: { item_type: "task", title: "Call the plumber", content_md: "" } }],
    });
  });
});

describe("review of a create proposal", () => {
  it("shows transcript, editable title/deadline/destination, plain-language warnings and no confidence label", async () => {
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    expect(screen.getByText(/Remind me to submit the report/)).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Submit the report");
    expect(screen.getByLabelText("Deadline date")).toHaveValue("2026-10-02");
    expect(screen.getByLabelText("Deadline time")).toHaveValue("17:00");
    expect(screen.getByLabelText("Destination")).toHaveValue("");
    expect(screen.getByLabelText("Things to check")).toHaveTextContent("“Next” could mean two different days");
    expect(screen.getByText("Task with deadline")).toBeInTheDocument(); // never "Reminder"
    expect(document.body.textContent).not.toMatch(/confidence|reminder|high|medium|low\b/i);
    expect(document.body.textContent).not.toMatch(/Today|Everyday Life/);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });

  it("date alternative chips change the deadline before accepting", async () => {
    acceptProposal.mockResolvedValue(resultFor());
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.click(screen.getByRole("button", { name: "Use 2026-10-09" }));
    expect(screen.getByLabelText("Deadline date")).toHaveValue("2026-10-09");
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(acceptProposal).toHaveBeenCalled());
    const [, input] = acceptProposal.mock.calls[0];
    expect(input.overrides).toEqual({ due_date: "2026-10-09", due_time: "17:00:00", due_timezone: "Asia/Kolkata" });
  });

  it("accepting without edits sends no overrides, uses the versions read, and offers Undo that archives the item", async () => {
    acceptProposal.mockResolvedValue(resultFor());
    const onChanged = vi.fn();
    renderCard(makeVoiceCapture({ proposal: taskProposal() }), fakeVoice(), { onChanged });
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(acceptProposal).toHaveBeenCalledTimes(1));
    const [capture, input] = acceptProposal.mock.calls[0];
    expect(capture.version).toBe(2);
    expect(capture.processing.generation).toBe(1);
    expect(input.overrides).toEqual({});
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [message, kind, action] = toastPush.mock.calls.find((call) => call[2]) ?? [];
    expect(message).toBe("Task added: Submit the report");
    expect(kind).toBe("success");
    archiveItem.mockResolvedValue({});
    await act(async () => action.onClick());
    expect(archiveItem).toHaveBeenCalledWith("item-1", 1); // undo = archive the created item
  });

  it("sends only the fields the user changed, including a new destination with its version", async () => {
    acceptProposal.mockResolvedValue(resultFor("Edited title"));
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Edited title" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Learning / Database Systems" })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "f-db" } });
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(acceptProposal).toHaveBeenCalled());
    expect(acceptProposal.mock.calls[0][1].overrides).toEqual({ title: "Edited title", destination: { kind: "folder", id: "f-db", version: 3 } });
  });

  it("asks before adding an overdue deadline and only then resends with confirmation", async () => {
    acceptProposal.mockRejectedValueOnce(new ApiError(422, { error: { code: "overdue_confirmation_required", message: "passed", details: { overdue_by_seconds: 3600 } } }));
    acceptProposal.mockResolvedValueOnce(resultFor());
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Overdue deadline" });
    expect(dialog).toHaveTextContent("This deadline has passed by 1 h. Add as overdue?");
    expect(acceptProposal).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Add as overdue" }));
    await waitFor(() => expect(acceptProposal).toHaveBeenCalledTimes(2));
    expect(acceptProposal.mock.calls[1][1].confirmOverdue).toBe(true);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("cancelling the overdue prompt writes nothing", async () => {
    acceptProposal.mockRejectedValueOnce(new ApiError(422, { error: { code: "overdue_confirmation_required", message: "passed", details: { overdue_by_seconds: 90000 } } }));
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("25 h");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(acceptProposal).toHaveBeenCalledTimes(1);
  });

  it("shows both timestamps for a delayed ingest and the receipt-anchored alternative", () => {
    const proposal = taskProposal({ warnings: ["delayed_ingest"] });
    proposal.resolution.anchor = { ...proposal.resolution.anchor, skew_s: 9000 };
    proposal.resolution.date.alternatives = [{ due_date: "2026-09-28", due_time: null, anchor: "receipt" }];
    renderCard(makeVoiceCapture({ proposal }));
    expect(screen.getByText(/Spoken .* · saved /)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use 2026-09-28 \(from when it was saved\)/ })).toBeInTheDocument();
    expect(screen.queryByText(/Saved long after/)).not.toBeInTheDocument(); // rendered as timestamps, not duplicated as a warning
  });

  it("Enter accepts and Escape closes without discarding", async () => {
    acceptProposal.mockResolvedValue(resultFor());
    const onDismiss = vi.fn();
    renderCard(makeVoiceCapture({ proposal: taskProposal() }), fakeVoice(), { onDismiss, variant: "tray" });
    const region = screen.getByRole("region", { name: "Voice command" });
    fireEvent.keyDown(region, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(archiveCapture).not.toHaveBeenCalled();
    fireEvent.keyDown(region, { key: "Enter" });
    await waitFor(() => expect(acceptProposal).toHaveBeenCalled());
  });
});

describe("stale proposal handling (409)", () => {
  const conflict = () => new ApiError(409, { error: { code: "version_conflict", message: "changed", details: { version: 3, generation: 1, state: "awaiting_review", proposal_sha256: "sha-1" } } });

  it("silently resubmits once when the proposal is unchanged and nothing was edited", async () => {
    acceptProposal.mockRejectedValueOnce(conflict());
    acceptProposal.mockResolvedValueOnce(resultFor());
    const fresh = makeVoiceCapture({ proposal: taskProposal(), version: 3 });
    getCapture.mockResolvedValue(fresh);
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(acceptProposal).toHaveBeenCalledTimes(2));
    expect(acceptProposal.mock.calls[1][0].version).toBe(3); // the refetched version
    expect(toastPush).not.toHaveBeenCalledWith(expect.stringContaining("changed while you were reviewing"), expect.anything());
  });

  it("keeps the user's edits and asks again when the proposal itself changed", async () => {
    acceptProposal.mockRejectedValueOnce(conflict());
    getCapture.mockResolvedValue(makeVoiceCapture({ proposal: taskProposal({ proposal_sha256: "sha-2" }), version: 3 }));
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "My edited title" } });
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    await waitFor(() => expect(toastPush).toHaveBeenCalledWith("This changed while you were reviewing. Check it and try again.", "info"));
    expect(acceptProposal).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Title")).toHaveValue("My edited title");
  });
});

describe("outcomes that write nothing", () => {
  it.each([["capture_only" as const], ["ambiguous" as const]])("%s offers Save as note / Save as task / Keep in Inbox / Discard and never a raw-capture location", (intent) => {
    renderCard(makeVoiceCapture({ proposal: noOperationProposal(intent) }), fakeVoice(), { variant: "tray", onDismiss: () => undefined });
    for (const name of ["Save as note", "Save as task", "Keep in Inbox", "Discard"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Choose location/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Accept/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Destination")).not.toBeInTheDocument(); // the picker lives inside Save as
  });

  it("the destination picker appears only inside Save as, and saving uses the manual interpretation route with the container version", async () => {
    interpretCaptureManually.mockResolvedValue({ capture: makeVoiceCapture({ state: "resolved" }), items: [], action_id: "a" });
    renderCard(makeVoiceCapture({ proposal: noOperationProposal("capture_only") }));
    fireEvent.click(screen.getByRole("button", { name: "Save as note" }));
    const panel = screen.getByRole("group", { name: "Save as note" });
    await waitFor(() => expect(within(panel).getByRole("option", { name: "Learning / Database Systems" })).toBeInTheDocument());
    fireEvent.change(within(panel).getByLabelText("Title"), { target: { value: "Gift ideas" } });
    fireEvent.change(within(panel).getByLabelText("Destination"), { target: { value: "f-db" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(interpretCaptureManually).toHaveBeenCalled());
    const [id, body] = interpretCaptureManually.mock.calls[0];
    expect(id).toBe("cap-1");
    expect(body.items[0]).toMatchObject({ kind: "create", item: { item_type: "note", title: "Gift ideas" }, folder_id: "f-db", folder_expected_version: 3 });
  });

  it("a restricted-launcher rejection explains itself and only offers keeping or discarding", () => {
    renderCard(makeVoiceCapture({ proposal: noOperationProposal("unsupported") }), fakeVoice(), { variant: "tray", onDismiss: () => undefined });
    expect(screen.getByText("This launcher can't do that. Use the main mic instead. Nothing was saved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Accept/ })).not.toBeInTheDocument();
  });

  it("inbox variant says it stays in Inbox until the user acts", () => {
    renderCard(makeVoiceCapture({ proposal: noOperationProposal("capture_only") }), fakeVoice(), { variant: "inbox" });
    expect(screen.getByText("Stays in Inbox until you act.")).toBeInTheDocument();
  });
});

describe("discard and transcript editing", () => {
  it("Discard needs an explicit confirmation and then archives the capture at the read version", async () => {
    archiveCapture.mockResolvedValue({});
    const onChanged = vi.fn();
    renderCard(makeVoiceCapture({ proposal: taskProposal() }), fakeVoice(), { onChanged });
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(archiveCapture).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByText("Discard this?").parentElement as HTMLElement).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(archiveCapture).toHaveBeenCalledWith("cap-1", 2));
    expect(onChanged).toHaveBeenCalled();
  });

  it("Edit transcript re-runs interpretation through the correction route while voice is on", async () => {
    correctTranscript.mockResolvedValue(makeVoiceCapture({ state: "pending" }));
    renderCard(makeVoiceCapture({ proposal: taskProposal() }));
    fireEvent.click(screen.getByRole("button", { name: "Edit transcript" }));
    fireEvent.change(screen.getByLabelText("Fix the transcript"), { target: { value: "Remind me to submit the report Friday" } });
    fireEvent.click(screen.getByRole("button", { name: "Re-run" }));
    await waitFor(() => expect(correctTranscript).toHaveBeenCalled());
    expect(correctTranscript.mock.calls[0][1]).toBe("Remind me to submit the report Friday");
  });

  it("never offers transcript re-run while voice is off (Type it instead is the path)", () => {
    renderCard(makeVoiceCapture({ proposal: taskProposal() }), fakeVoice({ capabilities: { ...CAPS, enabled: false, accepts_audio: false }, disabledReason: "off" }));
    expect(screen.queryByRole("button", { name: "Edit transcript" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Type it instead" })).toBeInTheDocument();
  });
});
