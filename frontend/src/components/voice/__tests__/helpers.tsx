import { vi } from "vitest";
import { Capture, VoiceCapabilities, VoiceProposal } from "@/lib/types";
import { VoiceContext, VoiceContextValue } from "../voiceContext";

export const CAPS: VoiceCapabilities = {
  enabled: true,
  accepts_audio: true,
  reason: null,
  max_seconds: 60,
  max_upload_bytes: 10 * 1024 * 1024,
  accepted_mime_types: ["video/webm", "audio/mp4", "audio/ogg"],
  allowed_intents: ["create_note", "create_task"],
  auto_apply_intents: [],
  policy_version: 1,
  low_disk: false,
};

export function makeVoiceCapture(overrides: Partial<Capture> & { proposal?: VoiceProposal | null; state?: Capture["processing"]["state"] } = {}): Capture {
  const { proposal = null, state = proposal ? "awaiting_review" : "pending", ...rest } = overrides;
  return {
    id: "cap-1",
    source_type: "audio",
    raw_text: null,
    original_description: null,
    original_url: null,
    captured_at: "2026-09-26T10:14:00+05:30",
    source_date: null,
    source_timezone: "Asia/Kolkata",
    timestamp_origin: "client_supplied",
    metadata: { processing_profile: "voice_command", entry_point: "global" },
    corrections: {},
    asset_ids: ["asset-1"],
    resulting_item_ids: [],
    version: 2,
    created_at: "2026-09-26T04:44:02Z",
    updated_at: "2026-09-26T04:44:02Z",
    archived_at: null,
    processing: {
      generation: 1,
      state,
      transcript: "Remind me to submit the report next Friday at 5 PM",
      proposal,
      error_code: null,
      error_message: null,
      attempt_count: 1,
      lease_expires_at: null,
      queued_at: "2026-09-26T04:44:02Z",
      started_at: null,
      finished_at: null,
    },
    action_id: null,
    ...rest,
  };
}

export function taskProposal(overrides: Partial<VoiceProposal> = {}): VoiceProposal {
  return {
    kind: "voice_command",
    schema_version: 1,
    generation: 1,
    proposal_sha256: "sha-1",
    policy_version: 1,
    intent: "create_task",
    operation: {
      type: "create",
      item_type: "task",
      title: "Submit the report",
      content_md: "",
      due_date: "2026-10-02",
      due_time: "17:00:00",
      due_timezone: "Asia/Kolkata",
      destination: null,
    },
    resolution: {
      intent: { basis: "explicit_reminder_verb", lexicon_agrees: true, alternative: null },
      anchor: { captured_at: "2026-09-26T10:14:00+05:30", received_at: "2026-09-26T10:14:02+05:30", skew_s: 2, timezone: "Asia/Kolkata" },
      date: { phrase: "next Friday", time_phrase: "5 PM", basis: "next_calendar_week_weekday", default: "2026-10-02", alternatives: [{ due_date: "2026-10-09", due_time: "17:00:00" }] },
      destination: { status: "none", phrase: null, candidates: [] },
    },
    warnings: ["date_ambiguous_next_weekday"],
    explanation: "Recognized a task with a deadline.",
    disposition: "review",
    disposition_reasons: ["date_ambiguous_next_weekday", "auto_apply_disabled"],
    ...overrides,
  };
}

export function noOperationProposal(intent: "capture_only" | "ambiguous" | "unsupported", extra: Partial<VoiceProposal> = {}): VoiceProposal {
  return taskProposal({
    intent,
    operation: null,
    warnings: [],
    explanation: intent === "capture_only" ? "Kept as a capture. Choose whether to save it as a note or a task." : "Couldn't tell whether this is a note or a task.",
    disposition: intent === "unsupported" ? "reject" : "review",
    disposition_reasons: intent === "unsupported" ? ["restricted_launcher"] : ["no_operation_" + intent],
    ...extra,
  });
}

export function fakeVoice(overrides: Partial<VoiceContextValue> = {}): VoiceContextValue {
  return {
    capabilities: CAPS,
    disabledReason: null,
    state: "idle",
    activeEntry: null,
    start: vi.fn(async () => undefined),
    stop: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(async () => undefined),
    saveToFile: vi.fn(),
    discardUnsent: vi.fn(),
    trackCapture: vi.fn(),
    refreshCapabilities: vi.fn(async () => CAPS),
    ...overrides,
  };
}

export function WithVoice({ value, children }: { value: VoiceContextValue; children: React.ReactNode }) {
  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>;
}
