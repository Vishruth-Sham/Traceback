"use client";

export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <div className="mb-6">
      <div className="text-[12px] italic text-ink-muted">{eyebrow}</div>
      <h1 className="font-serif text-[26px] font-semibold text-ink">{title}</h1>
      {description && <p className="mt-1.5 text-[13px] text-ink-muted">{description}</p>}
    </div>
  );
}
