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

export interface Processing {
  generation: number;
  state: ProcessingState;
  transcript: string | null;
  proposal?: NoteProposal | null;
  proposed_at?: string | null;
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
  filename: string | null;
  mime_type: string | null;
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
