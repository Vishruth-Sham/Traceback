import { PageHeader } from "@/components/PageHeader";

const SKILLS: {
  name: string;
  status: "Available" | "Planned" | "Disabled";
  description: string;
}[] = [
  {
    name: "Typed capture & manual organization",
    status: "Available",
    description: "Save typed text instantly and file it into a note by hand — no model required.",
  },
  {
    name: "Audio capture",
    status: "Available",
    description: "Record audio in the browser and save the original file before anything is transcribed.",
  },
  {
    name: "Local transcription (whisper.cpp)",
    status: "Available",
    description: "Turns saved audio into text. Requires the local processor and Whisper model to be running.",
  },
  {
    name: "Local organization suggestions (Qwen 3.5 4B)",
    status: "Available",
    description: "Proposes a note split for a capture. Requires the local processor and Ollama to be running.",
  },
  {
    name: "Receipt / photo extraction",
    status: "Planned",
    description: "Pull structured line items out of a photographed receipt into Health & Food.",
  },
  {
    name: "Link summaries",
    status: "Planned",
    description: "Summarize a saved URL capture automatically before it reaches Inbox.",
  },
  {
    name: "Weekly digest",
    status: "Planned",
    description: "A standing summary of what moved across Tasks, Projects, and categories this week.",
  },
  {
    name: "Personal memory graph",
    status: "Planned",
    description: "Source-backed facts and relationships across everything you've captured. See the personal memory plan.",
  },
];

const statusStyles: Record<string, string> = {
  Available: "border-accent-navy text-accent-navy",
  Planned: "border-hairline text-ink-faint",
  Disabled: "border-hairline text-ink-faint",
};

export default function SkillsPage() {
  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="automations that run in the background"
        title="Skills"
        description="What works today, and what's intentionally still on the backlog."
      />

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded border border-hairline bg-hairline">
        {SKILLS.map((skill) => (
          <div key={skill.name} className="flex flex-col gap-1.5 bg-paper-soft px-4 py-3.5">
            <div className="flex items-start justify-between gap-2">
              <span className="font-serif text-[14.5px] font-semibold text-ink">{skill.name}</span>
              <span className={"flex-none rounded border px-2 py-0.5 text-[10.5px] " + statusStyles[skill.status]}>
                {skill.status.toLowerCase()}
              </span>
            </div>
            <p className="text-[12.5px] text-ink-muted">{skill.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
