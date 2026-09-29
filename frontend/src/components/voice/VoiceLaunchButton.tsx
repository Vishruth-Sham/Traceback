"use client";

import { Mic } from "lucide-react";
import { LaunchOptions } from "@/lib/voice";
import { useVoice } from "./voiceContext";

/**
 * Presentational launcher: it only asks the shared provider to start. All recording, upload,
 * retry and polling logic lives in VoiceCommandProvider, so every surface behaves identically.
 * `contextualItemId` is a hint (a suggested destination), never authority.
 */
export function VoiceLaunchButton({
  entryPoint,
  contextualItemId,
  allowedIntents,
  label = "Speak",
  className,
}: LaunchOptions & { label?: string; className?: string }) {
  const { capabilities, disabledReason, start } = useVoice();
  const loading = capabilities === null && disabledReason === null;
  const disabled = loading || disabledReason !== null;
  const title = disabledReason ?? (loading ? "Checking voice availability…" : label);
  return (
    <button
      type="button"
      onClick={() => void start({ entryPoint, contextualItemId, allowedIntents })}
      disabled={disabled}
      title={title}
      aria-label={label}
      className={
        className ??
        "flex items-center gap-1 text-[11.5px] text-ink-faint hover:text-accent-navy disabled:cursor-not-allowed disabled:opacity-40"
      }
    >
      <Mic size={11} /> {label}
    </button>
  );
}
