"use client";

import { useOptionalVoice } from "./voiceContext";

/** Skills entry driven by the server's capabilities: never claims more than the backend reports. */
export function VoiceSkillCard() {
  const voice = useOptionalVoice();
  const enabled = voice?.capabilities?.enabled === true;
  const status = enabled ? "Available (review-first)" : "Planned";
  return (
    <div className="flex flex-col gap-1.5 bg-paper-soft px-4 py-3.5">
      <div className="flex items-start justify-between gap-2">
        <span className="font-serif text-[14.5px] font-semibold text-ink">Voice commands</span>
        <span className={"flex-none rounded border px-2 py-0.5 text-[10.5px] " + (enabled ? "border-accent-navy text-accent-navy" : "border-hairline text-ink-faint")}>
          {status.toLowerCase()}
        </span>
      </div>
      <p className="text-[12.5px] text-ink-muted">
        {enabled
          ? "Say a note or a task with a deadline. Nothing is saved until you accept it. Recognition quality on your voice has not been benchmarked yet."
          : "Turned off on this server. Typed capture and manual forms always work."}
      </p>
    </div>
  );
}
