// Mirrors backend/schemas.py, backend/capture_schemas.py. Keep in sync with docs/backend-api.md.

export type ItemType = "note" | "task" | "project" | "folder";
export type RelationType = "part_of" | "about" | "related_to";
export type TaskStatus = "open" | "completed";

export interface Relation {
  id: string;
  from_item_id: string;
  relation: RelationType;
  to_item_id: string;
  created_at: string;
}

export interface Item {
  id: string;
  item_type: ItemType;
  title: string;
  content_md: string;
  category_id: string | null;
  placement_state: "inbox" | "classified";
  attributes: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  inbox_entered_at: string | null;
  last_user_action_at: string;
  status: TaskStatus | null;
  due_date: string | null;
  due_time: string | null;
  due_timezone: string | null;
  completed_at: string | null;
  overdue: boolean | null;
  relations: Relation[];
  action_id: string | null;
  source_ids: string[];
  asset_ids: string[];
}

export interface Category {
  id: string;
  slug: string;
  name: string;
  sort_order: number;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface InboxPage extends Page<Item> {
  captures: Capture[];
  captures_truncated: boolean;
}

// Mirrors backend/capture_models.py's ck_capture_processing_state check constraint exactly.
export type ProcessingState = "pending" | "processing" | "awaiting_review" | "failed" | "resolved";

export interface NoteProposal {
  title: string;
  destination_kind: "category" | "project" | "folder" | null;
  destination_id: string | null;
  destination_version: number | null;
  explanation: string;
  confidence: "high" | "medium" | "low" | null;
  generation: number;
}

export type VoiceIntent = "create_note" | "create_task" | "capture_only" | "ambiguous" | "unsupported";
export type VoiceEntryPoint = "global" | "tasks" | "notes" | "project" | "folder" | "category" | "inbox" | "mcp_typed";

export interface VoiceDestination {
  kind: "category" | "project" | "folder";
  id: string;
  title: string | null;
  path: string | null;
  version: number | null;
  source: "spoken" | "surface_context" | null;
}

export interface VoiceOperation {
  type: "create";
  item_type: "note" | "task";
  title: string;
  content_md: string;
  due_date: string | null;
  due_time: string | null;
  due_timezone: string | null;
  destination: VoiceDestination | null;
}

export interface VoiceDateAlternative {
  due_date: string;
  due_time: string | null;
  anchor?: "receipt";
}

export interface VoiceProposal {
  kind: "voice_command";
  schema_version: number;
  generation: number;
  proposal_sha256: string;
  policy_version: number;
  intent: VoiceIntent;
  operation: VoiceOperation | null;
  resolution: {
    intent: { basis: string | null; lexicon_agrees: boolean; alternative: string | null };
    anchor: { captured_at: string; received_at: string; skew_s: number; timezone: string; observed_captured_at?: string | null };
    date: { phrase: string | null; time_phrase: string | null; basis: string | null; default: string | null; alternatives: VoiceDateAlternative[] };
    destination: {
      status: "none" | "resolved" | "ambiguous" | "not_found";
      phrase: string | null;
      candidates: { kind: string; id: string; title: string; path: string; version: number | null }[];
    };
  };
  warnings: string[];
  explanation: string;
  disposition: "review" | "reject" | "auto_apply_eligible";
  disposition_reasons: string[];
  // Deliberately absent from the UI: `model_confidence` is stored server-side for offline evaluation only.
}

export type CaptureProposal = NoteProposal | VoiceProposal;

export function isVoiceProposal(proposal: CaptureProposal | null | undefined): proposal is VoiceProposal {
  return !!proposal && (proposal as VoiceProposal).kind === "voice_command";
}

// Mirrors backend/voice_query.py's result shapes exactly (kind discriminates the panel state).
export interface VoiceQueryMatch {
  id: string;
  item_type: ItemType | "page" | "category";
  title: string;
  path: string | null;
  meta: string | null;
  route: string;
}

export interface VoiceQueryFooterAction {
  label: string;
  route: string;
}

export interface VoiceQueryResult {
  kind: "result" | "confirm" | "ambiguous" | "no_results";
  query_text?: string | null;
  label?: string | null;
  note?: string | null;
  matches?: VoiceQueryMatch[];
  confirm?: VoiceQueryMatch;
  footer_action?: VoiceQueryFooterAction | null;
  numbered?: boolean;
}

export interface Processing {
  generation: number;
  state: ProcessingState;
  transcript: string | null;
  proposal?: CaptureProposal | null;
  proposed_at?: string | null;
  query_result?: VoiceQueryResult | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  lease_expires_at: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type CaptureSourceType = "typed" | "audio" | "file" | "url" | "import";

export interface Capture {
  id: string;
  source_type: CaptureSourceType;
  raw_text: string | null;
  original_description: string | null;
  original_url: string | null;
  captured_at: string | null;
  source_date: string | null;
  source_timezone: string | null;
  timestamp_origin: string;
  metadata: Record<string, unknown>;
  corrections: Record<string, unknown>;
  asset_ids: string[];
  resulting_item_ids: string[];
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  processing: Processing;
  action_id: string | null;
}

export interface VoiceCapabilities {
  enabled: boolean;
  accepts_audio: boolean;
  reason: string | null;
  max_seconds: number;
  max_upload_bytes: number;
  accepted_mime_types: string[];
  allowed_intents: string[];
  auto_apply_intents: string[];
  policy_version: number;
  low_disk: boolean;
}

export interface Capabilities {
  voice_commands: VoiceCapabilities;
  query_commands: { enabled: boolean; kinds: string[] };
  queue: { pending_voice: number; oldest_pending_age_s: number | null };
}

export interface Location {
  kind: "category" | "project" | "folder";
  id: string;
  title: string;
  path: string;
  category_id: string | null;
  version: number | null;
}

export interface Revision {
  id: string;
  action_id: string;
  resulting_version: number;
  before_snapshot: Record<string, unknown> | null;
  after_snapshot: Record<string, unknown> | null;
  created_at: string;
}

export interface Source {
  id: string;
  item_id: string;
  capture_id: string;
  action_id: string | null;
  link_kind: string;
  created_at: string;
}

export interface Asset {
  id: string;
  original_filename: string;
  declared_mime_type: string | null;
  detected_mime_type: string;
  byte_size: number;
  sha256: string;
  uploaded_at: string;
  source_created_at: string | null;
  source_modified_at: string | null;
  archived_at: string | null;
  version: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.status = status;
    this.code = body.error.code;
    this.details = body.error.details;
  }

  get isVersionConflict(): boolean {
    return this.status === 409;
  }
}


// Mirrors backend/log_schemas.py (daily log).
export interface LogEntry {
  id: string;
  logged_at: string;
  log_date: string;
  text: string;
  origin: "ui" | "mcp";
  labels: string[];
}

export interface LogDay {
  log_date: string;
  summary: string | null;
  entries: LogEntry[];
}

export interface LogDaysPage {
  today: string;
  days: LogDay[];
  next_before: string | null;
}

export interface LogCategory {
  id: string;
  name: string;
  description: string;
}

export interface ClassifyResult {
  classified_days: string[];
  failed_days: string[];
}
