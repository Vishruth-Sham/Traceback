"use client";

export function CategoryTag({ label, active = false }: { label: string; active?: boolean }) {
  return (
    <span
      className={
        "whitespace-nowrap rounded border px-2 py-0.5 text-[11px] " +
        (active ? "border-accent-navy text-accent-navy" : "border-hairline text-ink-muted")
      }
    >
      {label}
    </span>
  );
}
