import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { Capture, Item } from "@/lib/types";
import { fakeVoice, makeVoiceCapture, taskProposal, WithVoice } from "./helpers";

const trackers = { toast: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/tasks",
  useParams: () => ({ slug: "learning", id: "proj-1" }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ push: trackers.toast }) }));
vi.mock("@/lib/traceback", async (original) => ({
  ...(await original<typeof import("@/lib/traceback")>()),
  listTasks: vi.fn(async () => ({ items: [], next_cursor: null })),
  listItems: vi.fn(async () => ({ items: [], next_cursor: null })),
  listLocations: vi.fn(async () => ({ items: [], next_cursor: null })),
  listCategories: vi.fn(async () => [{ id: "cat-learning", slug: "learning", name: "Learning", sort_order: 4 }]),
  getInbox: vi.fn(async () => ({ items: [], next_cursor: null, captures: inboxCaptures, captures_truncated: false })),
  getCapture: vi.fn(async () => inboxCaptures[0]),
  getItem: vi.fn(async () => ({ id: "proj-1", item_type: "project", title: "Kitchen", content_md: "", category_id: "cat-projects", version: 1, archived_at: null }) as Item),
}));

let inboxCaptures: Capture[] = [];

function surface(node: React.ReactNode, voice = fakeVoice()) {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <WithVoice value={voice}>{node}</WithVoice>
    </SWRConfig>,
  );
  return voice;
}

beforeEach(() => {
  trackers.toast.mockReset();
  inboxCaptures = [];
});

describe("page-level voice controls", () => {
  it("uses only the global voice control on Tasks", async () => {
    const { default: TasksPage } = await import("@/app/tasks/page");
    surface(<TasksPage />);
    expect(screen.queryByRole("button", { name: "Dictate a task" })).not.toBeInTheDocument();
  });

  it("uses only the global voice control on note screens", async () => {
    const { default: Page } = await import("@/app/notes/quick-add/page");
    surface(<Page />);
    expect(screen.queryByRole("button", { name: "Dictate a note" })).not.toBeInTheDocument();
  });

  it("keeps folder actions focused on creating folders and documents", async () => {
    const { FolderTree } = await import("@/components/FolderTree");
    surface(
      <>
        <FolderTree categoryId="cat-learning" parentId={null} />
        <FolderTree categoryId="cat-learning" parentId="folder-9" />
        <FolderTree categoryId="cat-projects" parentId="proj-1" />
      </>,
    );
    await screen.findAllByText("new folder");
    expect(screen.queryByRole("button", { name: "Speak here" })).not.toBeInTheDocument();
  });
});

describe("Inbox visibility", () => {
  it("lists voice captures with the review card and a Needs review badge beside ordinary captures", async () => {
    const plain = makeVoiceCapture({ id: "cap-plain", source_type: "typed", raw_text: "plain typed capture", metadata: {} });
    inboxCaptures = [makeVoiceCapture({ proposal: taskProposal() }), plain];
    const { default: InboxPage } = await import("@/app/inbox/page");
    surface(<InboxPage />);
    expect(await screen.findByText("Needs review")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Submit the report");
    expect(screen.getByText(/plain typed capture/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Speak a command" })).not.toBeInTheDocument();
  });

  it("shows a failed voice capture with its audio and recovery actions", async () => {
    const failed = makeVoiceCapture({ state: "failed" });
    failed.processing.error_code = "no_speech";
    inboxCaptures = [failed];
    const { default: InboxPage } = await import("@/app/inbox/page");
    surface(<InboxPage />);
    expect(await screen.findByText("No speech was detected. Your recording is saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Recording")).toBeInTheDocument();
  });
});
