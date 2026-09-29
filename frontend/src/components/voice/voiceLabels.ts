// Plain-language copy for the deterministic warnings/reasons the backend attaches to a proposal.
// Model confidence is intentionally never rendered anywhere in the UI.

export const WARNING_TEXT: Record<string, string> = {
  date_ambiguous_next_weekday: "“Next” could mean two different days. Check the date.",
  date_ambiguous_same_weekday: "That weekday is today. Choose today or next week.",
  time_passed_today: "That time has already passed today.",
  date_assumed: "No day was said, so tomorrow was assumed.",
  meridiem_assumed: "AM or PM wasn't said, so it was guessed.",
  year_assumed: "No year was said, so the next matching year was assumed.",
  year_two_digit: "A two-digit year was interpreted as 20xx.",
  date_numeric_ambiguous: "That numeric date can be read two ways. Pick one.",
  date_numeric_format: "Numeric dates are ambiguous. Check the date.",
  date_unresolved: "The date couldn't be worked out, so no deadline was set.",
  time_period_only: "Only a part of the day was said, so no clock time was set.",
  time_midnight_ambiguous: "“Midnight” could mean the start or the end of that day.",
  time_unresolved: "The time couldn't be worked out.",
  deadline_past: "This deadline has already passed.",
  dst_gap: "That time doesn't exist that day because of a clock change. Pick another time.",
  delayed_ingest: "Saved long after it was spoken. Dates use when you spoke.",
  clock_ahead: "This device's clock looked ahead. Dates use when you spoke.",
  intent_inferred: "Note or task was guessed from the wording.",
  intent_conflict: "The wording fits both a note and a task.",
  title_derived: "The title was taken from what you said.",
  title_missing: "No title could be found.",
  ungrounded_text: "Part of the suggestion wasn't in what you said and was dropped.",
  destination_not_found: "That destination wasn't found, so it stays in Inbox.",
  destination_ambiguous: "More than one destination matches. Choose one.",
  destination_fuzzy: "The destination name was matched approximately. Check it.",
  destination_from_context: "Suggested: the page you were on.",
  multi_intent: "Several commands were heard. Nothing was combined.",
  self_correction: "You seemed to change your mind. Check the text.",
  unclear_audio: "The audio may have been unclear.",
  unsupported_language: "Only English commands are understood.",
  possible_duplicate: "An item with this title already exists.",
  requested_delete: "Deleting by voice isn't supported.",
  unsupported_request: "That request isn't supported by voice.",
};

export const REJECT_TEXT: Record<string, string> = {
  restricted_launcher: "This launcher can't do that. Use the main mic instead. Nothing was saved.",
  organization_not_available: "Organizing existing items by voice isn't available yet. Nothing was changed.",
  unsupported_request: "That isn't supported by voice. Nothing was changed.",
};

export const FAILURE_TEXT: Record<string, string> = {
  no_speech: "No speech was detected. Your recording is saved.",
  unsupported_audio: "This recording couldn't be decoded. Your recording is saved.",
  audio_too_long: "This recording is too long. Your recording is saved.",
  legacy_audio_requires_review: "Saved for review.",
};

export function warningText(code: string): string {
  return WARNING_TEXT[code] ?? code.replace(/_/g, " ");
}

export function formatOverdue(seconds: number): string {
  if (seconds < 90) return "less than a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

export const ENTRY_LABEL: Record<string, string> = {
  global: "the main bar",
  tasks: "Tasks",
  notes: "Notes",
  project: "a project",
  folder: "a folder",
  category: "a category",
  inbox: "Inbox",
  mcp_typed: "MCP",
};
