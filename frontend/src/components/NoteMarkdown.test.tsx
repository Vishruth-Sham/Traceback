import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NoteMarkdown } from "./NoteMarkdown";

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async () => ({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>Diagram rendered</text><script>alert(1)</script></svg>' })),
  },
}));

it("sanitizes note HTML and renders mermaid fences", async () => {
  const { container } = render(<NoteMarkdown content={'<img src=x onerror="alert(1)">\n\n```mermaid\ngraph TD; A-->B\n```'} />);
  await screen.findByRole("img", { name: "Mermaid diagram" });
  await waitFor(() => expect(container.querySelector(".note-mermaid text")?.textContent).toBe("Diagram rendered"));
  expect(container.querySelector("[onerror]")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
});

it("renders an inline Traceback image", async () => {
  render(<NoteMarkdown content="Before\n\n![Diagram](/api/v1/assets/asset-1/content)\n\nAfter" />);
  const image = await screen.findByAltText("Diagram");
  expect(image).toHaveAttribute("src", "/api/v1/assets/asset-1/content");
});
