import { describe, expect, it } from "vitest";
import { groupByDay, isAfterMidnight, splitMatches } from "../logDays";
import { LogEntry } from "../types";

function entry(over: Partial<LogEntry>): LogEntry {
  return { id: "x", logged_at: "2026-10-03T12:00:00", log_date: "2026-10-03", text: "t", origin: "ui", labels: [], ...over };
}

describe("splitMatches", () => {
  it("highlights every case-insensitive match and keeps the original casing", () => {
    expect(splitMatches("Walk by the lake, long walk", "WALK")).toEqual([
      { text: "Walk", match: true },
      { text: " by the lake, long ", match: false },
      { text: "walk", match: true },
    ]);
  });

  it("returns the text untouched for an empty or missing query", () => {
    expect(splitMatches("hello", "  ")).toEqual([{ text: "hello", match: false }]);
    expect(splitMatches("hello", "zzz")).toEqual([{ text: "hello", match: false }]);
  });
});

describe("isAfterMidnight", () => {
  it("is true when the wall-clock date differs from the log day", () => {
    expect(isAfterMidnight(entry({ logged_at: "2026-10-04T01:30:00", log_date: "2026-10-03" }))).toBe(true);
    expect(isAfterMidnight(entry({ logged_at: "2026-10-03T13:05:00", log_date: "2026-10-03" }))).toBe(false);
  });
});

describe("groupByDay", () => {
  it("groups newest day first with entries in time order", () => {
    const days = groupByDay([
      entry({ id: "b", log_date: "2026-10-02", logged_at: "2026-10-02T19:00:00" }),
      entry({ id: "a", log_date: "2026-10-03", logged_at: "2026-10-03T08:00:00" }),
      entry({ id: "c", log_date: "2026-10-02", logged_at: "2026-10-02T09:00:00" }),
    ]);
    expect(days.map((d) => d.log_date)).toEqual(["2026-10-03", "2026-10-02"]);
    expect(days[1].entries.map((e) => e.id)).toEqual(["c", "b"]);
  });
});
