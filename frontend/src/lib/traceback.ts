import { api, newIdempotencyKey } from "./apiClient";
import {
  Capture,
  Category,
  Asset,
  ClassifyResult,
  InboxPage,
  Item,
  ItemType,
  Location,
  LogCategory,
  LogDaysPage,
  LogEntry,
  Page,
  Revision,
  Source,
  VoiceEntryPoint,
} from "./types";

export const CATEGORY_SLUGS = [
  "health-food",
  "personal-growth",
  "books",
  "learning",
  "projects",
  "other",
] as const;
export type CategorySlug = (typeof CATEGORY_SLUGS)[number];

export const CATEGORY_LABELS: Record<CategorySlug, string> = {
  "health-food": "Health & Food",
  "personal-growth": "Personal Growth",
  books: "Books",
  learning: "Learning",
  projects: "Projects",
  other: "Other",
};

export async function listCategories(): Promise<Category[]> {
  return api.get<Category[]>("/categories");
}

export interface ListItemsParams {
  item_type?: ItemType;
  category_id?: string;
  project_id?: string;
  parent_id?: string;
  top_level?: boolean;
  inbox?: boolean;
  archived?: boolean;
  q?: string;
  cursor?: string;
  limit?: number;
}

function qs(params: object): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value === undefined || value === null) continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export async function listItems(params: ListItemsParams = {}): Promise<Page<Item>> {
  return api.get<Page<Item>>(`/items${qs(params)}`);
}

export async function getInbox(cursor?: string): Promise<InboxPage> {
  return api.get<InboxPage>(`/inbox${qs({ cursor })}`);
}

export async function getItem(id: string): Promise<Item> {
  return api.get<Item>(`/items/${id}`);
}

export interface CreateItemInput {
  item_type: ItemType;
  title: string;
  content_md?: string;
  category_id?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  due_timezone?: string | null;
  project_id?: string;
  project_expected_version?: number;
  folder_id?: string;
  folder_expected_version?: number;
}

export async function createItem(input: CreateItemInput): Promise<Item> {
  return api.post<Item>("/items", input, newIdempotencyKey());
}

export interface PatchItemInput {
  expected_version: number;
  title?: string;
  content_md?: string;
  category_id?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  due_timezone?: string | null;
}

export async function patchItem(id: string, input: PatchItemInput): Promise<Item> {
  return api.patch<Item>(`/items/${id}`, input);
}

export async function moveItem(
  id: string,
  destination: { expected_version: number } & (
    | { category_id: string }
    | { inbox: true }
    | { project_id: string; project_expected_version: number }
    | { folder_id: string; folder_expected_version: number }
  ),
): Promise<Item> {
  return api.post<Item>(`/items/${id}/move`, destination);
}

// Folders are plain items with item_type "folder"; nesting one item inside
// another (folder or project) is the same `part_of` relation the backend
// already uses for project membership. Always re-fetch the container right
// before nesting into it, rather than trusting a version held in state —
// the container's version bumps every time something is added to it.
export async function createFolder(title: string, categoryId: string, parentId?: string): Promise<Item> {
  if (parentId) {
    const parent = await getItem(parentId);
    return createItem({
      item_type: "folder",
      title,
      folder_id: parent.id,
      folder_expected_version: parent.version,
    });
  }
  return createItem({ item_type: "folder", title, category_id: categoryId });
}

export async function nestInFolder(itemId: string, itemVersion: number, folderId: string): Promise<Item> {
  const folder = await getItem(folderId);
  return moveItem(itemId, { expected_version: itemVersion, folder_id: folder.id, folder_expected_version: folder.version });
}

export async function appendItem(id: string, expected_version: number, content_md: string): Promise<Item> {
  return api.post<Item>(`/items/${id}/append`, { expected_version, content_md });
}

export async function archiveItem(id: string, expected_version: number): Promise<Item> {
  return api.post<Item>(`/items/${id}/archive`, { expected_version });
}

export async function restoreItem(id: string, expected_version: number): Promise<Item> {
  return api.post<Item>(`/items/${id}/restore`, { expected_version });
}

export async function deleteItemPermanently(id: string, expected_version: number): Promise<void> {
  return api.del<void>(`/items/${id}?expected_version=${expected_version}&confirm=true`);
}

export interface TasksParams {
  status?: "open" | "completed";
  category_id?: string;
  project_id?: string;
  cursor?: string;
  limit?: number;
}

export async function listTasks(params: TasksParams = {}): Promise<Page<Item>> {
  return api.get<Page<Item>>(`/tasks${qs(params)}`);
}

export async function completeTask(id: string, expected_version: number): Promise<Item> {
  return api.post<Item>(`/tasks/${id}/complete`, { expected_version });
}

export async function reopenTask(id: string, expected_version: number): Promise<Item> {
  return api.post<Item>(`/tasks/${id}/reopen`, { expected_version });
}

export async function createRelation(input: {
  from_item_id: string;
  from_expected_version: number;
  relation: "part_of" | "about" | "related_to";
  to_item_id: string;
  to_expected_version: number;
}) {
  return api.post(`/relations`, input);
}

export async function deleteRelation(
  relationId: string,
  from_expected_version: number,
  to_expected_version: number,
) {
  return api.del(`/relations/${relationId}`, { from_expected_version, to_expected_version });
}

export async function getHistory(itemId: string, cursor?: string): Promise<Page<Revision>> {
  return api.get<Page<Revision>>(`/items/${itemId}/history${qs({ cursor })}`);
}

export async function undoAction(actionId: string, expected_versions: Record<string, number>) {
  return api.post<{ action_id: string; items: Item[] }>(`/actions/${actionId}/undo`, {
    expected_versions,
  });
}

// Captures

export interface CreateCaptureInput {
  source_type: "typed" | "audio" | "file" | "url" | "import";
  raw_text?: string;
  description?: string;
  url?: string;
  asset_ids?: string[];
  captured_at?: string;
  source_timezone?: string;
  timestamp_origin?: "user_supplied" | "client_supplied" | "source_metadata" | "unknown";
  metadata?: {
    processing_profile?: "general" | "task_quick_add" | "note_quick_add" | "voice_command";
    supplied_title?: string;
    placement_hint?: string;
    entry_point?: VoiceEntryPoint;
    allowed_intents?: ("create_note" | "create_task")[];
  };
}

export async function createCapture(input: CreateCaptureInput, idempotencyKey = newIdempotencyKey()): Promise<Capture> {
  return api.post<Capture>("/captures", input, idempotencyKey);
}

export async function listCaptures(params: { archived?: boolean; q?: string; cursor?: string } = {}) {
  return api.get<Page<Capture>>(`/captures${qs(params)}`);
}

export async function getCapture(id: string): Promise<Capture> {
  return api.get<Capture>(`/captures/${id}`);
}

export async function correctCapture(
  id: string,
  input: { expected_version: number; note_text?: string; supplied_title?: string; placement_hint?: string },
): Promise<Capture> {
  return api.post<Capture>(`/captures/${id}/corrections`, input, newIdempotencyKey());
}

export async function listLocations(q?: string): Promise<Page<Location>> {
  const items: Location[] = [];
  let cursor: string | undefined;
  do {
    const page = await api.get<Page<Location>>(`/locations${qs({ q, cursor, limit: 200 })}`);
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return { items, next_cursor: null };
}

export async function archiveCapture(id: string, expected_version: number): Promise<Capture> {
  return api.post<Capture>(`/captures/${id}/archive`, { expected_version });
}

export async function restoreCapture(id: string, expected_version: number): Promise<Capture> {
  return api.post<Capture>(`/captures/${id}/restore`, { expected_version });
}

export async function deleteCapturePermanently(id: string, expected_version: number): Promise<void> {
  return api.del<void>(`/captures/${id}?expected_version=${expected_version}&confirm=true`);
}

export async function retryCapture(id: string, expected_version: number, expected_generation: number): Promise<Capture> {
  return api.post<Capture>(`/captures/${id}/retry`, { expected_version, expected_generation });
}

export type InterpretationOperation =
  | ({ kind: "create"; item: CreateItemInput } & (
      | { project_id: string; project_expected_version: number; folder_id?: undefined; folder_expected_version?: undefined }
      | { folder_id: string; folder_expected_version: number; project_id?: undefined; project_expected_version?: undefined }
      | { project_id?: undefined; project_expected_version?: undefined; folder_id?: undefined; folder_expected_version?: undefined }
    ))
  | { kind: "append"; item_id: string; expected_version: number; content_md: string };

export async function interpretCaptureManually(
  captureId: string,
  input: {
    expected_version: number;
    expected_generation: number;
    items: InterpretationOperation[];
  },
) {
  return api.post<{ capture: Capture; items: Item[]; action_id: string }>(`/captures/${captureId}/interpretations`, {
    mode: "manual",
    ...input,
  });
}

export async function uploadAsset(file: File): Promise<{ id: string; version: number }> {
  return api.uploadAsset(file.name, file, newIdempotencyKey());
}

export async function getAsset(id: string): Promise<Asset> {
  return api.get<Asset>(`/assets/${id}`);
}

export async function linkNoteImage(noteId: string, assetId: string, expectedVersion: number): Promise<{ version: number }> {
  return api.post<{ version: number }>(`/items/${noteId}/assets/${assetId}`, { expected_version: expectedVersion });
}

export async function unlinkNoteImage(noteId: string, assetId: string, expectedVersion: number): Promise<{ version: number }> {
  return api.del<{ version: number }>(`/items/${noteId}/assets/${assetId}`, { expected_version: expectedVersion });
}

export async function itemSources(itemId: string): Promise<Source[]> {
  return api.get<Source[]>(`/items/${itemId}/sources`);
}

// --- Daily log ---

export async function addLogEntry(text: string): Promise<LogEntry> {
  return api.post<LogEntry>("/log", { text });
}

export async function listLogDays(before?: string, limit = 14): Promise<LogDaysPage> {
  return api.getFresh<LogDaysPage>(`/log/days${qs({ before, limit })}`);
}

export async function searchLog(q: string, limit = 100): Promise<{ entries: LogEntry[] }> {
  return api.getFresh<{ entries: LogEntry[] }>(`/log/search${qs({ q, limit })}`);
}

export async function archiveLogEntry(id: string): Promise<void> {
  await api.del<void>(`/log/${id}`);
}

export async function classifyLog(target: { date?: string; all_days?: boolean }): Promise<ClassifyResult> {
  return api.post<ClassifyResult>("/log/classify", target);
}

export async function listLogCategories(): Promise<LogCategory[]> {
  return api.getFresh<LogCategory[]>("/log/categories");
}

export async function createLogCategory(name: string, description: string): Promise<LogCategory> {
  return api.post<LogCategory>("/log/categories", { name, description });
}

export async function updateLogCategory(id: string, patch: { name?: string; description?: string }): Promise<LogCategory> {
  return api.patch<LogCategory>(`/log/categories/${id}`, patch);
}

export async function deleteLogCategory(id: string): Promise<void> {
  await api.del<void>(`/log/categories/${id}`);
}
