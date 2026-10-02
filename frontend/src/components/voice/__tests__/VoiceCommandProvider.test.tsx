import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ApiError } from "@/lib/types";
import { VoiceCommandProvider } from "../VoiceCommandProvider";
import { useVoice } from "../voiceContext";
import { VoiceLaunchButton } from "../VoiceLaunchButton";
import { CAPS, makeVoiceCapture } from "./helpers";

const getCapabilities = vi.fn();
const uploadVoiceCapture = vi.fn();
const createCapture = vi.fn();
const toastPush = vi.fn();
const routerPush = vi.fn();
const getCapture = vi.fn(async () => makeVoiceCapture());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
}));
vi.mock("@/lib/voice", async (original) => ({
  ...(await original<typeof import("@/lib/voice")>()),
  getCapabilities: () => getCapabilities(),
  uploadVoiceCapture: (...args: unknown[]) => uploadVoiceCapture(...args),
  sha256Hex: vi.fn(async () => "b".repeat(64)),
}));
vi.mock("@/lib/traceback", () => ({
  createCapture: (...args: unknown[]) => createCapture(...args),
  getCapture: () => getCapture(),
  archiveCapture: vi.fn(),
  archiveItem: vi.fn(),
  interpretCaptureManually: vi.fn(),
  listLocations: vi.fn(async () => ({ items: [], next_cursor: null })),
  retryCapture: vi.fn(),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ push: toastPush }) }));

// ---- fakes for the browser APIs the recorder drives ----
class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static supported = new Set(["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]);
  static isTypeSupported = (mime: string) => FakeRecorder.supported.has(mime);
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  started = false;
  constructor(_stream: MediaStream, options: { mimeType: string }) {
    this.mimeType = options.mimeType;
    FakeRecorder.instances.push(this);
  }
  start() {
    this.started = true;
  }
  stop() {
    this.ondataavailable?.({ data: new Blob([new Uint8Array(2048)], { type: this.mimeType }) });
    this.onstop?.();
  }
}

const trackStop = vi.fn();
let getUserMedia: ReturnType<typeof vi.fn>;
let heldLocks: Set<string>;

function installBrowser({ locks = true } = {}) {
  FakeRecorder.instances = [];
  FakeRecorder.supported = new Set(["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]);
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  const track = { stop: trackStop, addEventListener: vi.fn() };
  getUserMedia = vi.fn(async () => ({ getTracks: () => [track], getAudioTracks: () => [track] }));
  heldLocks = new Set();
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: locks
      ? {
          request: (name: string, _opts: unknown, cb: (lock: unknown) => Promise<void> | undefined) => {
            if (heldLocks.has(name)) return Promise.resolve(cb(null));
            heldLocks.add(name);
            return Promise.resolve(cb({ name })).finally(() => heldLocks.delete(name));
          },
        }
      : undefined,
  });
}

function Harness() {
  const voice = useVoice();
  return (
    <div>
      <span data-testid="state">{voice.state}</span>
      <span data-testid="reason">{voice.disabledReason ?? ""}</span>
      <VoiceLaunchButton entryPoint="tasks" allowedIntents={["create_task"]} label="Dictate a task" />
      <VoiceLaunchButton entryPoint="notes" allowedIntents={["create_note"]} label="Dictate a note" />
      <button onClick={voice.stop}>stop</button>
      <button onClick={voice.cancel}>cancel</button>
    </div>
  );
}

async function mount() {
  render(
    <VoiceCommandProvider>
      <Harness />
    </VoiceCommandProvider>,
  );
  await act(async () => undefined);
}

const state = () => screen.getByTestId("state").textContent;
const click = async (name: string) => {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  vi.setSystemTime(new Date("2026-09-26T04:44:00Z"));
  getCapabilities.mockReset();
  getCapabilities.mockResolvedValue({ voice_commands: CAPS, queue: { pending_voice: 0, oldest_pending_age_s: null } });
  uploadVoiceCapture.mockReset();
  uploadVoiceCapture.mockResolvedValue(makeVoiceCapture());
  createCapture.mockReset();
  createCapture.mockResolvedValue(makeVoiceCapture({ source_type: "typed" }));
  toastPush.mockReset();
  routerPush.mockReset();
  getCapture.mockReset();
  getCapture.mockResolvedValue(makeVoiceCapture());
  trackStop.mockReset();
  installBrowser();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function record(ms: number) {
  await click("Dictate a task");
  expect(state()).toBe("recording");
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await click("stop");
}

describe("single global command panel", () => {
  it("does not start recording on Option + Space, including in the command input", async () => {
    await mount();
    fireEvent.keyDown(window, { key: " ", code: "Space", altKey: true });
    fireEvent.keyUp(window, { key: " ", code: "Space", altKey: true });
    const input = screen.getByRole("textbox", { name: "Command" });
    fireEvent.keyDown(input, { key: " ", code: "Space", altKey: true });
    fireEvent.keyUp(input, { key: " ", code: "Space", altKey: true });
    expect(state()).toBe("idle");
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("records from the global command bar", async () => {
    await mount();
    expect(screen.getByPlaceholderText("Ask or give a command…")).toBeInTheDocument();
    expect(screen.queryByText("Hold ⌥ Option + Space to speak")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Voice command" })).toHaveAttribute("title", "Voice command");
    await click("Voice command");
    expect(state()).toBe("recording");
    expect(screen.getByPlaceholderText("Listening…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice command" })).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTime(1000));
    await click("Stop voice command");
    expect(uploadVoiceCapture).toHaveBeenCalledTimes(1);
    expect(uploadVoiceCapture.mock.calls[0][0].entryPoint).toBe("global");
  });

  it("submits a typed command from the bar and retains its retry key after a failed response", async () => {
    createCapture.mockRejectedValueOnce(new Error("connection lost"));
    await mount();
    const input = screen.getByRole("textbox", { name: "Command" });
    fireEvent.change(input, { target: { value: "What are my tasks?" } });
    await act(async () => { fireEvent.submit(input.closest("form")!); });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not send the command");
    await act(async () => { fireEvent.submit(input.closest("form")!); });
    expect(createCapture).toHaveBeenCalledTimes(2);
    expect(createCapture.mock.calls[1]).toEqual(createCapture.mock.calls[0]);
    expect(createCapture.mock.calls[0][0]).toMatchObject({
      source_type: "typed",
      raw_text: "What are my tasks?",
      metadata: { processing_profile: "voice_command", entry_point: "global" },
    });
    expect(screen.getByText(/Finding matches/)).toBeInTheDocument();
  });
});

describe("recording state machine", () => {
  it("sends nothing until Stop, then uploads one request with the entry point, anchor, digest and a key", async () => {
    await mount();
    await click("Dictate a task");
    await act(async () => vi.advanceTimersByTime(2000));
    expect(uploadVoiceCapture).not.toHaveBeenCalled(); // no network before Stop
    await click("stop");
    expect(uploadVoiceCapture).toHaveBeenCalledTimes(1);
    const attempt = uploadVoiceCapture.mock.calls[0][0];
    expect(attempt).toMatchObject({ entryPoint: "tasks", allowedIntents: ["create_task"], sha256: "b".repeat(64), durationMs: 2000, capturedAt: "2026-09-26T04:44:00.000Z" });
    expect(attempt.idempotencyKey).toMatch(/.+/);
    expect(attempt.blob.size).toBe(2048);
    expect(state()).toBe("idle");
    expect(trackStop).toHaveBeenCalled(); // microphone released
    expect(screen.getByText(/Finding matches/)).toBeInTheDocument(); // palette takes over with a processing state
  });

  it("discards a recording shorter than 0.7 s without any request", async () => {
    await mount();
    await record(300);
    expect(uploadVoiceCapture).not.toHaveBeenCalled();
    expect(toastPush).toHaveBeenCalledWith("Too short. Nothing was saved.", "info");
    expect(state()).toBe("idle");
  });

  it("stops by itself at the server's maximum length", async () => {
    await mount();
    await click("Dictate a task");
    await act(async () => vi.advanceTimersByTime(61_000));
    expect(uploadVoiceCapture).toHaveBeenCalledTimes(1);
    expect(uploadVoiceCapture.mock.calls[0][0].durationMs).toBeLessThanOrEqual(60_250);
  });

  it("Cancel discards before upload: nothing sent, nothing retained", async () => {
    await mount();
    await click("Dictate a task");
    await click("cancel");
    expect(uploadVoiceCapture).not.toHaveBeenCalled();
    expect(state()).toBe("idle");
    expect(trackStop).toHaveBeenCalled();
  });

  it("reports a denied microphone and stays idle", async () => {
    await mount();
    getUserMedia.mockRejectedValueOnce(new Error("denied"));
    await click("Dictate a task");
    expect(screen.getByText(/Grant microphone access/)).toBeInTheDocument();
    expect(state()).toBe("idle");
    expect(heldLocks.size).toBe(0); // the cross-tab lock was released
  });

  it("refuses when no recorder format is acceptable to the server", async () => {
    FakeRecorder.supported = new Set();
    await mount();
    await click("Dictate a task");
    expect(screen.getByText("This browser records in a format the server doesn't accept.")).toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("re-reads capabilities on every click and refuses when they turned off", async () => {
    await mount();
    getCapabilities.mockResolvedValue({ voice_commands: { ...CAPS, enabled: false, accepts_audio: false }, queue: { pending_voice: 0, oldest_pending_age_s: null } });
    await click("Dictate a task");
    expect(getCapabilities).toHaveBeenCalledTimes(2); // on load and on the click
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(state()).toBe("idle");
  });
});

describe("one-recording mutex", () => {
  it("a second launcher during recording starts nothing and reports where it started", async () => {
    await mount();
    await click("Dictate a task");
    await click("Dictate a note");
    expect(FakeRecorder.instances).toHaveLength(1);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(toastPush).toHaveBeenCalledWith("Already recording (started from Tasks)", "info");
    expect(state()).toBe("recording");
  });

  it("a double click in the same tick yields one recorder", async () => {
    await mount();
    const button = screen.getByRole("button", { name: "Dictate a task" });
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    expect(FakeRecorder.instances).toHaveLength(1);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("another window holding the Web Lock refuses this tab", async () => {
    await mount();
    heldLocks.add("traceback-voice-recorder");
    await click("Dictate a task");
    expect(toastPush).toHaveBeenCalledWith("Recording is active in another window.", "info");
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(state()).toBe("idle");
  });

  it("releases the Web Lock when the recording finishes so the next recording can start", async () => {
    await mount();
    await record(1500);
    expect(state()).toBe("idle");
    expect(heldLocks.size).toBe(0);
    await click("Dictate a note");
    expect(state()).toBe("recording");
  });
});

describe("failed upload keeps the recording", () => {
  it("retains the blob, blocks new recordings, and retry replays the identical key, bytes and anchor", async () => {
    uploadVoiceCapture.mockRejectedValueOnce(new ApiError(503, { error: { code: "backend_unreachable", message: "The local Traceback API is not reachable." } }));
    await mount();
    await record(1500);
    expect(state()).toBe("failed_unsent");
    expect(screen.getByRole("alert")).toHaveTextContent("Your recording is still here");
    await click("Dictate a note"); // blocked until retry / save / discard
    expect(toastPush).toHaveBeenCalledWith("Retry, save, or discard the unsent recording first.", "info");
    expect(FakeRecorder.instances).toHaveLength(1);

    await click("Retry");
    expect(uploadVoiceCapture).toHaveBeenCalledTimes(2);
    const [first, second] = uploadVoiceCapture.mock.calls.map((call) => call[0]);
    expect(second.idempotencyKey).toBe(first.idempotencyKey);
    expect(second.sha256).toBe(first.sha256);
    expect(second.capturedAt).toBe(first.capturedAt);
    expect(second.blob).toBe(first.blob);
    expect(state()).toBe("idle");
  });

  it("does not offer retry for a policy refusal, but still allows saving to a file or discarding", async () => {
    uploadVoiceCapture.mockRejectedValueOnce(new ApiError(403, { error: { code: "capability_disabled", message: "Voice commands are disabled on this server" } }));
    await mount();
    await record(1500);
    expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save recording to a file" })).toBeEnabled();
    await click("Discard");
    expect(state()).toBe("idle");
  });

  it("exports the retained blob to a local file", async () => {
    uploadVoiceCapture.mockRejectedValueOnce(new ApiError(503, { error: { code: "backend_unreachable", message: "down" } }));
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await mount();
    await record(1500);
    await click("Save recording to a file");
    expect(createObjectURL).toHaveBeenCalledWith(uploadVoiceCapture.mock.calls[0][0].blob);
    expect(clicked).toHaveBeenCalled();
  });

  it("follows the existing capture when the server reports a duplicate recording", async () => {
    uploadVoiceCapture.mockRejectedValueOnce(new ApiError(409, { error: { code: "duplicate_recording", message: "already saved", details: { capture_id: "cap-existing" } } }));
    await mount();
    await record(1500);
    expect(state()).toBe("idle");
    expect(screen.getByText(/Finding matches/)).toBeInTheDocument(); // followed the existing capture into the palette
  });

  it("guards against leaving the page while recording, uploading, or unsent", async () => {
    await mount();
    const listeners: string[] = [];
    const add = vi.spyOn(window, "addEventListener");
    await click("Dictate a task");
    listeners.push(...add.mock.calls.map((call) => String(call[0])));
    expect(listeners).toContain("beforeunload");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("capability-driven disabled state", () => {
  it("disables every launcher with the reason and never falls back to another path", async () => {
    getCapabilities.mockResolvedValue({ voice_commands: { ...CAPS, enabled: false, accepts_audio: false, reason: "voice_disabled" }, queue: { pending_voice: 0, oldest_pending_age_s: null } });
    await mount();
    for (const name of ["Dictate a task", "Dictate a note"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Voice commands are turned off on this server");
    }
    expect(uploadVoiceCapture).not.toHaveBeenCalled();
  });

  it("disables launchers with a reason when the server can't be reached", async () => {
    getCapabilities.mockRejectedValue(new Error("offline"));
    await mount();
    expect(screen.getByRole("button", { name: "Dictate a task" })).toBeDisabled();
    expect(screen.getByTestId("reason")).toHaveTextContent("unavailable");
  });

  it("enables launchers when voice is on", async () => {
    await mount();
    expect(screen.getByRole("button", { name: "Dictate a task" })).toBeEnabled();
  });
});

function makeQueryCapture(query_result: NonNullable<ReturnType<typeof makeVoiceCapture>["processing"]["query_result"]>, id?: string) {
  const base = makeVoiceCapture(id ? { id } : {});
  return { ...base, processing: { ...base.processing, state: "resolved" as const, proposal: null, query_result } };
}

describe("read-only query results (the palette, never a mutation path)", () => {
  it("shows a numbered result list and navigates without asking for confirmation on click", async () => {
    getCapture.mockResolvedValue(
      makeQueryCapture({
        kind: "result",
        label: "Overdue tasks",
        matches: [{ id: "t1", item_type: "task", title: "Submit expense report", path: null, meta: "3d late", route: "/tasks?open=t1" }],
        note: null,
        footer_action: { label: "Open Tasks", route: "/tasks" },
      }),
    );
    await mount();
    await record(1500);
    expect(screen.getByText("Overdue tasks")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Submit expense report"));
    expect(routerPush).toHaveBeenCalledWith("/tasks?open=t1"); // read-only: a click navigates, it never mutates the task
    expect(uploadVoiceCapture).toHaveBeenCalledTimes(1); // no further request was ever made to accept/mutate anything
  });

  it("auto-navigates on a uniquely resolved target and shows the one-line confirmation", async () => {
    getCapture.mockResolvedValue(
      makeQueryCapture({ kind: "confirm", confirm: { id: "p1", item_type: "project", title: "DSA Learning", path: "Projects / DSA Learning", meta: null, route: "/projects/p1" } }),
    );
    await mount();
    await record(1500);
    expect(routerPush).toHaveBeenCalledWith("/projects/p1");
    expect(screen.getByText(/Opened:/)).toBeInTheDocument();
  });

  it("ambiguity always lists every candidate and never auto-picks one", async () => {
    getCapture.mockResolvedValue(
      makeQueryCapture({
        kind: "ambiguous",
        query_text: "Open Renovation",
        label: "I found 2 projects named Renovation",
        matches: [
          { id: "a1", item_type: "project", title: "Renovation", path: "Home", meta: null, route: "/projects/a1" },
          { id: "a2", item_type: "folder", title: "Renovation", path: "Archive", meta: null, route: "/category/archive?open=a2" },
        ],
        note: "Say “the first one” or select it — Traceback never guesses.",
        numbered: true,
      }),
    );
    await mount();
    await record(1500);
    expect(screen.getByText(/never guesses/)).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalled(); // nothing was guessed or opened automatically
    expect(screen.getAllByText("Renovation")).toHaveLength(2);
  });

  it("attaches the ambiguous capture as follow-up context on the next recording ('the first one')", async () => {
    getCapture.mockResolvedValue(
      makeQueryCapture(
        {
          kind: "ambiguous",
          matches: [{ id: "a1", item_type: "project", title: "Renovation", path: "Home", meta: null, route: "/projects/a1" }],
          numbered: true,
        },
        "cap-ambiguous",
      ),
    );
    uploadVoiceCapture.mockResolvedValue(makeVoiceCapture({ id: "cap-ambiguous" }));
    await mount();
    await record(1500); // produces the ambiguity above
    await click("Dictate a task"); // the user speaks a numbered follow-up next
    await act(async () => vi.advanceTimersByTime(1500));
    await click("stop");
    const secondAttempt = uploadVoiceCapture.mock.calls[1][0];
    expect(secondAttempt.contextualCaptureId).toBe("cap-ambiguous");
  });

  it("shows a plain no-results state with a rephrase suggestion, not a guess", async () => {
    getCapture.mockResolvedValue(makeQueryCapture({ kind: "no_results", query_text: "quantum entanglement", note: 'No matches found. Try rephrasing, or say "show all tasks".' }));
    await mount();
    await record(1500);
    expect(screen.getByText(/No matches found/)).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it("a processing failure surfaces as the unavailable state, not a silent drop", async () => {
    const base = makeVoiceCapture();
    getCapture.mockResolvedValue({
      ...base,
      processing: { ...base.processing, state: "failed", error_code: "ModelUnavailableError", error_message: "Ollama is not running", query_result: null },
    });
    await mount();
    await record(1500);
    expect(screen.getByText("Ollama is not running")).toBeInTheDocument();
  });
});
