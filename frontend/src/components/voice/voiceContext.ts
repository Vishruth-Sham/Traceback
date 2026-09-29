"use client";

import { createContext, useContext } from "react";
import type { VoiceCapabilities } from "@/lib/types";
import type { LaunchOptions } from "@/lib/voice";

export type RecorderState = "idle" | "requesting_permission" | "recording" | "stopping" | "uploading" | "failed_unsent";

export interface VoiceContextValue {
  capabilities: VoiceCapabilities | null;
  /** Null when the mic may be used; otherwise the reason shown as the disabled tooltip. */
  disabledReason: string | null;
  state: RecorderState;
  activeEntry: LaunchOptions | null;
  start: (options: LaunchOptions) => Promise<void>;
  stop: () => void;
  cancel: () => void;
  retry: () => Promise<void>;
  saveToFile: () => void;
  discardUnsent: () => void;
  trackCapture: (id: string) => void;
  refreshCapabilities: () => Promise<VoiceCapabilities | null>;
}

export const VoiceContext = createContext<VoiceContextValue | null>(null);

export function useVoice(): VoiceContextValue {
  const ctx = useContext(VoiceContext);
  if (!ctx) throw new Error("useVoice must be used inside VoiceCommandProvider");
  return ctx;
}

/** Like useVoice, but tolerates a missing provider (the review card also renders standalone in Inbox and tests). */
export function useOptionalVoice(): VoiceContextValue | null {
  return useContext(VoiceContext);
}
