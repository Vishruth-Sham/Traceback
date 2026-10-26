import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../apiClient";
import { createFolder } from "../traceback";

describe("createFolder", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends project_id when the parent is a project", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ id: "proj-1", item_type: "project", version: 4 });
    const post = vi.spyOn(api, "post").mockResolvedValue({ id: "new" });
    await createFolder("Notes", "cat-1", "proj-1");
    expect(post.mock.calls[0][1]).toEqual({
      item_type: "folder",
      title: "Notes",
      project_id: "proj-1",
      project_expected_version: 4,
    });
  });

  it("sends folder_id when the parent is a folder", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ id: "f-1", item_type: "folder", version: 2 });
    const post = vi.spyOn(api, "post").mockResolvedValue({ id: "new" });
    await createFolder("Sub", "cat-1", "f-1");
    expect(post.mock.calls[0][1]).toEqual({
      item_type: "folder",
      title: "Sub",
      folder_id: "f-1",
      folder_expected_version: 2,
    });
  });
});
