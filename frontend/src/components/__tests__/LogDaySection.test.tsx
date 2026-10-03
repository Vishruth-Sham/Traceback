import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LogDaySection } from "../LogDaySection";
import { LogDay } from "@/lib/types";

vi.mock("../Toast", () => ({ useToast: () => ({ push: vi.fn() }) }));

const entries = [
  { id: "1", logged_at: "2026-10-02T09:00:00", log_date: "2026-10-02", text: "Invoice backlog", origin: "ui" as const, labels: ["work"] },
  { id: "2", logged_at: "2026-10-02T19:00:00", log_date: "2026-10-02", text: "Walk around the lake", origin: "mcp" as const, labels: [] },
];

function day(over: Partial<LogDay> = {}): LogDay {
  return { log_date: "2026-10-02", summary: null, entries, ...over };
}

function renderDay(d: LogDay, props: Partial<Parameters<typeof LogDaySection>[0]> = {}) {
  const onClassify = vi.fn();
  render(<LogDaySection day={d} isToday={false} query="" classifying={false} onClassify={onClassify} onChanged={() => {}} {...props} />);
  return onClassify;
}

describe("LogDaySection", () => {
  it("offers to classify an unclassified day and reports which day", () => {
    const onClassify = renderDay(day());
    expect(screen.getByText(/Not classified yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Classify" }));
    expect(onClassify).toHaveBeenCalledWith("2026-10-02");
  });

  it("labels the button for today", () => {
    renderDay(day(), { isToday: true });
    expect(screen.getByRole("button", { name: "Classify today" })).toBeInTheDocument();
  });

  it("shows the summary and tags and no classify prompt once classified", () => {
    renderDay(day({ summary: "A quiet day." }));
    expect(screen.getByText(/A quiet day\./)).toBeInTheDocument();
    expect(screen.getByText("work")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Classify/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Not classified yet/)).not.toBeInTheDocument();
  });

  it("hides the classify prompt while searching and highlights matches", () => {
    renderDay(day(), { query: "lake" });
    expect(screen.queryByRole("button", { name: /^Classify/ })).not.toBeInTheDocument();
    expect(screen.getByText("lake").tagName).toBe("MARK");
  });

  it("renders an empty today with a placeholder instead of a classify prompt", () => {
    renderDay(day({ entries: [] }), { isToday: true, showToday: true });
    expect(screen.getByText("Nothing logged yet today.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Classify/ })).not.toBeInTheDocument();
  });
});
