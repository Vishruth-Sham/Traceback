export const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"]);
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;

export function validNoteImage(file: File): boolean {
  return IMAGE_TYPES.has(file.type) && file.size > 0 && file.size <= MAX_IMAGE_BYTES;
}

export function imageMarkdown(assetId: string, filename: string): string {
  const alt = filename.replace(/[\\\[\]\r\n]/g, " ").trim() || "Image";
  return `![${alt}](/api/v1/assets/${assetId}/content)`;
}

export function insertAtSelection(content: string, insertion: string, start: number, end: number): { content: string; cursor: number } {
  const prefix = content.slice(0, start);
  const suffix = content.slice(end);
  const before = prefix && !prefix.endsWith("\n") ? "\n\n" : "";
  const after = suffix && !suffix.startsWith("\n") ? "\n\n" : "";
  const next = `${prefix}${before}${insertion}${after}${suffix}`;
  return { content: next, cursor: (prefix + before + insertion).length };
}
