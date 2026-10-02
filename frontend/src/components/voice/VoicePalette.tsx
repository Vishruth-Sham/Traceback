"use client";

import { useState } from "react";
import { AlertTriangle, Check, Mic } from "lucide-react";
import { ApiError } from "@/lib/types";
import type { VoiceQueryFooterAction, VoiceQueryMatch } from "@/lib/types";
import styles from "./VoicePalette.module.css";

export type PaletteView =
  | { kind: "idle" }
  | { kind: "recording"; elapsedMs: number; maxMs: number }
  | { kind: "processing"; queryText: string | null; progressLabel?: string }
  | {
      kind: "result";
      label: string | null;
      matches: VoiceQueryMatch[];
      note: string | null;
      numbered?: boolean;
      footerAction?: VoiceQueryFooterAction | null;
    }
  | { kind: "confirm"; match: VoiceQueryMatch }
  | { kind: "ambiguous"; queryText: string | null; label: string | null; matches: VoiceQueryMatch[]; note: string | null }
  | { kind: "no_results"; queryText: string | null; note: string | null }
  | { kind: "unavailable"; message: string; canDismiss?: boolean }
  | { kind: "permission"; message: string }
  | { kind: "cancelled" };

export interface VoicePaletteProps {
  view: PaletteView;
  onDismiss: () => void;
  onSelect: (match: VoiceQueryMatch) => void;
  onFooterAction: (action: VoiceQueryFooterAction) => void;
  onOpenSettings: () => void;
  onStartRecording: () => void;
  onSubmitTyped: (text: string) => Promise<void>;
  onStopRecording: () => void;
}

function MatchRow({ match, index, numbered, onSelect }: { match: VoiceQueryMatch; index: number; numbered?: boolean; onSelect: (m: VoiceQueryMatch) => void }) {
  return (
    <button type="button" className={styles.prow} onClick={() => onSelect(match)}>
      {numbered ? <span className={styles.idx}>{index + 1}</span> : <span className={styles.bullet} aria-hidden />}
      <span className={styles.main}>
        {match.title}
        {match.path && <div className={styles.path}>{match.path}</div>}
      </span>
      {match.meta && <span className={match.meta.toLowerCase().includes("late") ? styles.metaLate : styles.meta}>{match.meta}</span>}
    </button>
  );
}

/**
 * The global voice panel aligns with the page's content column in every state.
 * Recording and navigation logic lives in VoiceCommandProvider.
 */
export function VoicePalette({ view, onDismiss, onSelect, onFooterAction, onOpenSettings, onStartRecording, onSubmitTyped, onStopRecording }: VoicePaletteProps) {
  const [typedText, setTypedText] = useState("");
  const [typedBusy, setTypedBusy] = useState(false);
  const [typedError, setTypedError] = useState<string | null>(null);
  const recording = view.kind === "recording";
  const showDetails = view.kind !== "idle" && !recording;

  async function submitTyped(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = typedText.trim();
    if (!value || typedBusy) return;
    setTypedBusy(true);
    setTypedError(null);
    try {
      await onSubmitTyped(value);
      setTypedText("");
    } catch (error) {
      setTypedError(error instanceof ApiError ? error.message : "Could not send the command. Try again.");
    } finally {
      setTypedBusy(false);
    }
  }

  return (
    <div className={styles.root}>
      <div className={styles.dock} role="region" aria-label="Voice command">
        {showDetails && <div className={styles.panel}>
          {view.kind === "processing" && (
            <>
              {view.queryText && <div className={styles.query}>{view.queryText}</div>}
              <div className={styles.progress}>
                <span className={styles.spinner} aria-hidden />{" "}
                {view.progressLabel ?? (view.queryText ? "Finding matches…" : "Understanding your command…")}
              </div>
            </>
          )}

          {view.kind === "result" && (
            <>
              <div className={styles.head}>
                <b>{view.label ?? "Results"}</b>
                <span>{view.matches.length}</span>
              </div>
              {view.matches.length > 0 ? (
                <div className={styles.plist}>
                  {view.matches.map((match, index) => (
                    <MatchRow key={match.id} match={match} index={index} numbered={view.numbered} onSelect={onSelect} />
                  ))}
                </div>
              ) : (
                view.note && <div className={styles.note}>{view.note}</div>
              )}
              {view.matches.length > 0 && view.note && <div className={styles.note}>{view.note}</div>}
              <div className={styles.footer}>
                {view.footerAction ? (
                  <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => onFooterAction(view.footerAction!)}>
                    {view.footerAction.label}
                  </button>
                ) : (
                  <span />
                )}
                <button type="button" className={`${styles.btn} ${styles.btnGhost}`} onClick={onDismiss}>
                  Dismiss
                </button>
              </div>
            </>
          )}

          {view.kind === "confirm" && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              <Check size={14} className={styles.checkOk} aria-hidden /> <span className={styles.checkOk}>Opened:</span> {view.match.path ?? view.match.title}
            </div>
          )}

          {view.kind === "ambiguous" && (
            <>
              {view.queryText && <div className={styles.query} style={{ marginBottom: 10 }}>{view.queryText}</div>}
              <div className={styles.head}>
                <b>{view.label ?? "I found more than one match"}</b>
              </div>
              <div className={styles.plist}>
                {view.matches.map((match, index) => (
                  <MatchRow key={match.id} match={match} index={index} numbered onSelect={onSelect} />
                ))}
              </div>
              <div className={styles.note}>{view.note ?? 'Say "the first one" or select it — Traceback never guesses.'}</div>
              <div className={styles.footer}>
                <span />
                <button type="button" className={`${styles.btn} ${styles.btnGhost}`} onClick={onDismiss}>
                  Dismiss
                </button>
              </div>
            </>
          )}

          {view.kind === "no_results" && (
            <>
              {view.queryText && <div className={styles.query}>{view.queryText}</div>}
              <div className={styles.note} style={{ marginTop: 2 }}>
                {view.note ?? "No matches found. Try rephrasing."}
              </div>
            </>
          )}

          {view.kind === "unavailable" && (
            <>
              <div className={styles.status} style={{ marginBottom: 6 }}>
                <AlertTriangle size={13} className={styles.errTitle} aria-hidden /> <span className={styles.errTitle}>Voice processing unavailable</span>
              </div>
              <div className={styles.note} style={{ marginTop: 0 }}>
                {view.message}
              </div>
              <div className={styles.footer}>
                <span />
                <button type="button" className={`${styles.btn} ${styles.btnGhost}`} onClick={onDismiss}>
                  Dismiss
                </button>
              </div>
            </>
          )}

          {view.kind === "permission" && (
            <>
              <div className={styles.status} style={{ marginBottom: 6 }}>
                <AlertTriangle size={13} className={styles.errTitle} aria-hidden /> <span className={styles.errTitle}>Microphone access needed</span>
              </div>
              <div className={styles.note} style={{ marginTop: 0 }}>
                {view.message}
              </div>
              <div className={styles.footer}>
                <button type="button" className={`${styles.btn} ${styles.btnPrimary}`} onClick={onOpenSettings}>
                  Open Settings
                </button>
                <button type="button" className={`${styles.btn} ${styles.btnGhost}`} onClick={onDismiss}>
                  Dismiss
                </button>
              </div>
            </>
          )}

          {view.kind === "cancelled" && <div className={styles.note} style={{ margin: 0 }}>Cancelled &mdash; nothing was sent.</div>}
        </div>}
        {typedError && <div role="alert" className={styles.typedError}>{typedError}</div>}
        <form className={styles.commandBar} onSubmit={(event) => void submitTyped(event)}>
          <input
            id="voice-typed-command"
            type="text"
            aria-label="Command"
            value={typedText}
            onChange={(event) => { setTypedText(event.target.value); setTypedError(null); }}
            placeholder={recording ? "Listening…" : "Ask or give a command…"}
            disabled={typedBusy || recording}
            className={styles.commandInput}
          />
          <button
            type="button"
            className={styles.micButton}
            onClick={recording ? onStopRecording : onStartRecording}
            aria-label={recording ? "Stop voice command" : "Voice command"}
            title={recording ? "Stop and send" : "Voice command"}
          >
            {recording ? <span className={styles.dot} aria-hidden /> : <Mic size={16} aria-hidden />}
          </button>
        </form>
      </div>
    </div>
  );
}
