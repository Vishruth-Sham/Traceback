"use client";

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="mb-5 flex gap-2 text-[12.5px]">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={
            "rounded border px-3 py-1 " +
            (value === opt.value ? "border-accent-navy text-accent-navy" : "border-hairline text-ink-muted")
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
