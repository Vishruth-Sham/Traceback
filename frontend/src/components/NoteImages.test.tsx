import { render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { expect, it, vi } from "vitest";
import { Item } from "@/lib/types";
import { NoteImages } from "./NoteImages";

vi.mock("@/lib/traceback", () => ({
  getAsset: vi.fn(async () => ({ id: "asset-1", original_filename: "old.png", detected_mime_type: "image/png" })),
  unlinkNoteImage: vi.fn(),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ push: vi.fn() }) }));

it("shows older linked images only when they are not placed inline", async () => {
  const item = { id: "note-1", version: 2, asset_ids: ["asset-1"], content_md: "A note" } as Item;
  const view = render(<SWRConfig value={{ provider: () => new Map() }}><NoteImages item={item} onChanged={async () => undefined} onInsert={async () => undefined} /></SWRConfig>);
  expect(await screen.findByAltText("old.png")).toBeInTheDocument();
  view.rerender(<SWRConfig value={{ provider: () => new Map() }}><NoteImages item={{ ...item, content_md: "![old](/api/v1/assets/asset-1/content)" }} onChanged={async () => undefined} onInsert={async () => undefined} /></SWRConfig>);
  expect(screen.queryByAltText("old.png")).toBeNull();
});
