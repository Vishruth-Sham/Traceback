"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Check, Loader2, Mic, RotateCcw } from "lucide-react";
import { ApiError, Capture, Location, VoiceDateAlternative, VoiceProposal, isVoiceProposal } from "@/lib/types";
import { archiveCapture, archiveItem, getCapture, interpretCaptureManually, listLocations, retryCapture } from "@/lib/traceback";
import { AcceptOverrides, acceptProposal, assetContentUrl, correctTranscript } from "@/lib/voice";
import { useToast } from "../Toast";
import { useOptionalVoice } from "./voiceContext";
import { FAILURE_TEXT, REJECT_TEXT, formatOverdue, warningText } from "./voiceLabels";

const POLL_MS = 1500;
const WAITING_AFTER_MS = 20_000;

type Draft = {
  item_type: "note" | "task";
  title: string;
  content_md: string;
  due_date: string;
  due_time: string;
  destinationId: string; // "" = Inbox / no destination
};

function draftFrom(proposal: VoiceProposal): Draft {
  const op = proposal.operation;
  return {
    item_type: op?.item_type ?? "note",
    title: op?.title ?? "",
    content_md: op?.content_md ?? "",
    due_date: op?.due_date ?? "",
    due_time: op?.due_time?.slice(0, 5) ?? "",
    destinationId: op?.destination?.id ?? "",
  };
}

function sameDraft(a: Draft, b: Draft): boolean {
  return (Object.keys(a) as (keyof Draft)[]).every((key) => a[key] === b[key]);
}

function transcriptOf(capture: Capture): string {
  return (capture.corrections?.transcript_text as string | undefined) ?? capture.processing.transcript ?? capture.raw_text ?? "";
}

export interface CommandReviewCardProps {
  capture: Capture;
  variant: "tray" | "inbox";
  onChanged: () => void;
  onDismiss?: () => void;
}

/**
 * The single review / accept / edit / discard surface for a voice capture. It renders whatever the
 * backend computed (transcript, deterministic warnings, resolved destination) and applies nothing
 * itself: Accept, Save-as and Discard are explicit user actions sent to REST with the versions read.
 */
export function CommandReviewCard({ capture: initial, variant, onChanged, onDismiss }: CommandReviewCardProps) {
  const toast = useToast();
  const voice = useOptionalVoice();
  const [capture, setCapture] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"review" | "saveAs" | "typeIt" | "editTranscript">("review");
  const [saveAsKind, setSaveAsKind] = useState<"note" | "task">("note");
  const [text, setText] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [overdue, setOverdue] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [baseline, setBaseline] = useState<Draft | null>(null);
  const [seenProposal, setSeenProposal] = useState<string | null>(null);
  const [seenInitial, setSeenInitial] = useState(initial);
  const [now, setNow] = useState(() => Date.now());

  // Adopt a new server copy of the capture (e.g. the Inbox list refreshed) without an effect.
  if (initial !== seenInitial) {
    setSeenInitial(initial);
    setCapture(initial);
  }

  const state = capture.processing.state;
  const proposal = isVoiceProposal(capture.processing.proposal) ? capture.processing.proposal : null;
  const voiceEnabled = voice?.capabilities?.enabled ?? true;

  // Poll only while the local processor may still change the capture.
  useEffect(() => {
    if (state !== "pending" && state !== "processing") return;
    const interval = setInterval(() => {
      setNow(Date.now());
      getCapture(capture.id)
        .then((fresh) => setCapture(fresh))
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [state, capture.id]);

  // A new proposal generation resets the draft only when the user has not edited; edits survive a refetch.
  const proposalKey = proposal?.proposal_sha256 ?? null;
  if (proposalKey !== seenProposal) {
    setSeenProposal(proposalKey);
    const fresh = proposal ? draftFrom(proposal) : null;
    const dirty = draft !== null && baseline !== null && !sameDraft(draft, baseline);
    setBaseline(fresh);
    if (!dirty) setDraft(fresh);
  }

  const needsLocations = state === "awaiting_review" || mode === "saveAs" || mode === "typeIt";
  const { data: locationsPage } = useSWR(needsLocations ? "voice-locations" : null, () => listLocations());
  const locations: Location[] = useMemo(() => locationsPage?.items ?? [], [locationsPage]);

  const refetch = useCallback(async () => {
    const fresh = await getCapture(capture.id);
    setCapture(fresh);
    return fresh;
  }, [capture.id]);

  const overridesFor = useCallback((): AcceptOverrides => {
    if (!proposal?.operation || !draft) return {};
    const op = proposal.operation;
    const base = draftFrom(proposal);
    const overrides: AcceptOverrides = {};
    if (draft.item_type !== base.item_type) overrides.item_type = draft.item_type;
    if (draft.title !== base.title) overrides.title = draft.title;
    if (draft.content_md !== base.content_md) overrides.content_md = draft.content_md;
    if (draft.item_type === "task") {
      if (draft.due_date !== base.due_date || draft.due_time !== base.due_time) {
        overrides.due_date = draft.due_date || null;
        overrides.due_time = draft.due_time ? `${draft.due_time}:00` : null;
        overrides.due_timezone = draft.due_time ? (op.due_timezone ?? capture.source_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone) : null;
      }
    }
    if (draft.destinationId !== base.destinationId) {
      const target = locations.find((location) => location.id === draft.destinationId);
      overrides.destination = target
        ? { kind: target.kind, id: target.id, ...(target.version !== null ? { version: target.version } : {}) }
        : null;
    }
    return overrides;
  }, [capture.source_timezone, draft, locations, proposal]);

  async function accept(confirmOverdue = false, retried = false) {
    if (!proposal?.operation || busy) return;
    setBusy(true);
    try {
      const result = await acceptProposal(capture, { overrides: overridesFor(), confirmOverdue });
      const item = result.items[0];
      setCapture(result.capture);
      setOverdue(null);
      toast.push(`${item.item_type === "task" ? "Task added" : "Note added"}: ${item.title}`, "success", {
        label: "Undo",
        onClick: async () => {
          try {
            await archiveItem(item.id, item.version);
            toast.push("Archived. The recording is still saved.", "info");
            onChanged();
          } catch (err) {
            toast.push(err instanceof ApiError ? err.message : "Could not undo.", "error");
          }
        },
      });
      onChanged();
      onDismiss?.();
    } catch (err) {
      if (err instanceof ApiError && err.code === "overdue_confirmation_required") {
        setOverdue(Number(err.details?.overdue_by_seconds ?? 0));
      } else if (err instanceof ApiError && err.status === 409) {
        // Stale: refetch. If the proposal itself is unchanged and nothing was edited, resubmit once silently.
        const before = proposal.proposal_sha256;
        const fresh = await refetch().catch(() => null);
        const freshProposal = fresh && isVoiceProposal(fresh.processing.proposal) ? fresh.processing.proposal : null;
        const untouched = draft !== null && baseline !== null && sameDraft(draft, baseline);
        if (!retried && fresh && freshProposal?.proposal_sha256 === before && untouched && fresh.processing.state === "awaiting_review") {
          setBusy(false);
          await acceptFresh(fresh, confirmOverdue);
          return;
        }
        toast.push("This changed while you were reviewing. Check it and try again.", "info");
      } else {
        toast.push(err instanceof ApiError ? err.message : "Could not save.", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  async function acceptFresh(fresh: Capture, confirmOverdue: boolean) {
    setBusy(true);
    try {
      const result = await acceptProposal(fresh, { overrides: overridesFor(), confirmOverdue });
      setCapture(result.capture);
      toast.push(`${result.items[0].item_type === "task" ? "Task added" : "Note added"}: ${result.items[0].title}`, "success");
      onChanged();
      onDismiss?.();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not save.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await archiveCapture(capture.id, capture.version);
      toast.push("Discarded.", "success");
      onChanged();
      onDismiss?.();
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not discard.", "error");
    } finally {
      setBusy(false);
      setConfirmDiscard(false);
    }
  }

  async function retry() {
    setBusy(true);
    try {
      setCapture(await retryCapture(capture.id, capture.version, capture.processing.generation));
      toast.push("Trying again.", "success");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Retry failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveEditedTranscript() {
    setBusy(true);
    try {
      setCapture(await correctTranscript(capture, text));
      setMode("review");
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not update the transcript.", "error");
    } finally {
      setBusy(false);
    }
  }

  const startedAt = new Date(capture.created_at).getTime();
  const waiting = state === "pending" && (!voiceEnabled || now - startedAt > WAITING_AFTER_MS);
  const canTypeInstead = state === "pending" || state === "failed" || state === "awaiting_review";
  const isAudio = capture.source_type === "audio" && capture.asset_ids.length > 0;

  function openSaveAs(kind: "note" | "task") {
    setSaveAsKind(kind);
    setText(transcriptOf(capture));
    setMode("saveAs");
  }

  const badge =
    state === "awaiting_review"
      ? { label: "Needs review", tone: "border-accent-navy text-accent-navy" }
      : state === "failed"
        ? { label: "Couldn't process", tone: "border-danger text-danger" }
        : state === "resolved"
          ? { label: "Added", tone: "border-success text-success" }
          : { label: state === "processing" ? "Understanding…" : "Saved • transcribing", tone: "border-hairline text-ink-faint" };

  return (
    <section
      aria-label="Voice command"
      className="flex flex-col gap-2.5 rounded-lg border border-hairline bg-paper-soft p-3.5 text-[13px]"
      onKeyDown={(event) => {
        const target = event.target as HTMLElement;
        const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
        if (event.key === "Enter" && !typing && mode === "review" && proposal?.operation && overdue === null) void accept();
        if (event.key.toLowerCase() === "e" && !typing && mode === "review" && canTypeInstead) {
          setText(transcriptOf(capture));
          setMode(voiceEnabled ? "editTranscript" : "typeIt");
        }
        if (event.key === "Escape") {
          if (mode !== "review") setMode("review");
          else onDismiss?.();
        }
      }}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-ink-faint">
        <Mic size={12} />
        <span>{capture.source_type === "audio" ? "voice command" : "typed command"}</span>
        <span className={`rounded border px-1.5 py-0.5 normal-case ${badge.tone}`}>{badge.label}</span>
        <span className="ml-auto flex items-center gap-2 normal-case">
          {variant === "tray" && onDismiss && state !== "processing" && (
            <button type="button" onClick={onDismiss} className="text-ink-faint hover:text-ink" aria-label="Close">
              Close
            </button>
          )}
        </span>
      </div>

      {isAudio && <audio controls preload="none" src={assetContentUrl(capture.asset_ids[0])} className="h-8 w-full" aria-label="Recording" />}
      {transcriptOf(capture) && mode === "review" && <p className="text-ink">&ldquo;{transcriptOf(capture)}&rdquo;</p>}

      {(state === "pending" || state === "processing") && (
        <div className="flex items-center gap-2 text-ink-muted">
          <Loader2 size={12} className="animate-spin" />
          <span>{waiting ? (voiceEnabled ? "Waiting for the local processor…" : "Voice processing is off.") : state === "processing" ? "Working on it…" : "Saved • transcribing"}</span>
        </div>
      )}

      {state === "failed" && (
        <div className="flex flex-col gap-1 text-danger" role="alert">
          <span>{FAILURE_TEXT[capture.processing.error_code ?? ""] ?? "Couldn't process this. Your recording is saved."}</span>
        </div>
      )}

      {state === "resolved" && <p className="text-ink-muted">Added to your items.</p>}

      {state === "awaiting_review" && proposal && mode === "review" && (
        <ProposalReview
          capture={capture}
          proposal={proposal}
          draft={draft}
          setDraft={setDraft}
          locations={locations}
        />
      )}
      {state === "awaiting_review" && !proposal && mode === "review" && (
        <p className="text-ink-muted">Suggested organization is ready. Choose Save as note or Save as task.</p>
      )}

      {overdue !== null && (
        <div className="rounded border border-danger bg-danger-soft p-2.5 text-danger" role="alertdialog" aria-label="Overdue deadline">
          <p>This deadline has passed by {formatOverdue(overdue)}. Add as overdue?</p>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => void accept(true)} disabled={busy} className="rounded border border-danger px-2.5 py-1 font-medium">
              Add as overdue
            </button>
            <button type="button" onClick={() => setOverdue(null)} className="px-2 py-1 underline">
              Cancel
            </button>
          </div>
        </div>
      )}

      {mode === "editTranscript" && (
        <div className="flex flex-col gap-2">
          <label className="text-ink-faint" htmlFor={`transcript-${capture.id}`}>
            Fix the transcript
          </label>
          <textarea id={`transcript-${capture.id}`} value={text} onChange={(event) => setText(event.target.value)} rows={3} className="rounded border border-hairline bg-paper p-2" />
          <div className="flex gap-2">
            <button type="button" onClick={() => void saveEditedTranscript()} disabled={busy || !text.trim()} className="rounded border border-hairline px-2.5 py-1 hover:border-accent-navy">
              Re-run
            </button>
            <button type="button" onClick={() => setMode("review")} className="px-2 py-1 underline">
              Cancel
            </button>
          </div>
        </div>
      )}

      {(mode === "saveAs" || mode === "typeIt") && (
        <SaveAsPanel
          capture={capture}
          kind={saveAsKind}
          setKind={setSaveAsKind}
          text={text}
          setText={setText}
          locations={locations}
          heading={mode === "typeIt" ? "Type it instead" : `Save as ${saveAsKind}`}
          onCancel={() => setMode("review")}
          onSaved={(updated) => {
            setCapture(updated);
            onChanged();
            onDismiss?.();
          }}
        />
      )}

      {mode === "review" && (
        <div className="flex flex-wrap items-center gap-2">
          {state === "awaiting_review" && proposal?.operation && (
            <button type="button" onClick={() => void accept()} disabled={busy || !draft?.title.trim()} className="flex items-center gap-1 rounded bg-accent-navy px-3 py-1.5 font-medium text-paper disabled:opacity-40">
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Accept
            </button>
          )}
          {state === "awaiting_review" && !proposal?.operation && (
            <>
              <button type="button" onClick={() => openSaveAs("note")} className="rounded border border-hairline px-2.5 py-1 hover:border-accent-navy hover:text-accent-navy">
                Save as note
              </button>
              <button type="button" onClick={() => openSaveAs("task")} className="rounded border border-hairline px-2.5 py-1 hover:border-accent-navy hover:text-accent-navy">
                Save as task
              </button>
              {variant === "tray" ? (
                <button type="button" onClick={onDismiss} className="rounded border border-hairline px-2.5 py-1 hover:border-accent-navy">
                  Keep in Inbox
                </button>
              ) : (
                <span className="text-ink-faint">Stays in Inbox until you act.</span>
              )}
            </>
          )}
          {state === "failed" && (
            <button
              type="button"
              onClick={() => void retry()}
              disabled={busy || !voiceEnabled}
              title={voiceEnabled ? undefined : "Voice processing is turned off"}
              className="flex items-center gap-1 rounded border border-hairline px-2.5 py-1 hover:border-accent-navy disabled:opacity-40"
            >
              <RotateCcw size={11} /> Retry
            </button>
          )}
          {canTypeInstead && (waiting || state === "failed" || !voiceEnabled) && (
            <button type="button" onClick={() => { setText(transcriptOf(capture)); setMode("typeIt"); }} className="rounded border border-hairline px-2.5 py-1 hover:border-accent-navy">
              Type it instead
            </button>
          )}
          {canTypeInstead && voiceEnabled && transcriptOf(capture) && state !== "pending" && (
            <button type="button" onClick={() => { setText(transcriptOf(capture)); setMode("editTranscript"); }} className="px-1 py-1 text-ink-faint underline">
              Edit transcript
            </button>
          )}
          {state !== "resolved" &&
            (confirmDiscard ? (
              <span className="ml-auto flex items-center gap-2">
                <span className="text-ink-muted">Discard this?</span>
                <button type="button" onClick={() => void discard()} disabled={busy} className="font-medium text-danger underline">
                  Discard
                </button>
                <button type="button" onClick={() => setConfirmDiscard(false)} className="underline">
                  Keep
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmDiscard(true)} className="ml-auto px-1 py-1 text-ink-faint underline hover:text-ink">
                Discard
              </button>
            ))}
        </div>
      )}
    </section>
  );
}

function ProposalReview({
  capture,
  proposal,
  draft,
  setDraft,
  locations,
}: {
  capture: Capture;
  proposal: VoiceProposal;
  draft: Draft | null;
  setDraft: (draft: Draft) => void;
  locations: Location[];
}) {
  const operation = proposal.operation;
  const warnings = proposal.warnings.filter((code) => code !== "delayed_ingest" && code !== "clock_ahead");
  const skewed = proposal.warnings.some((code) => code === "delayed_ingest" || code === "clock_ahead");
  const rejectReason = proposal.disposition === "reject" ? REJECT_TEXT[proposal.disposition_reasons[0]] ?? proposal.explanation : null;

  if (!operation || !draft) {
    return (
      <div className="flex flex-col gap-1.5">
        <p className="text-ink">{rejectReason ?? proposal.explanation}</p>
        {warnings.length > 0 && <WarningList codes={warnings} />}
      </div>
    );
  }

  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const alternatives = proposal.resolution.date.alternatives ?? [];
  const applyAlternative = (alt: VoiceDateAlternative) => set({ due_date: alt.due_date, due_time: alt.due_time?.slice(0, 5) ?? draft.due_time });
  const spokenAt = new Date(proposal.resolution.anchor.captured_at).toLocaleString();
  const savedAt = new Date(capture.created_at).toLocaleString();

  return (
    <div className="flex flex-col gap-2">
      <p className="text-ink-muted">{proposal.explanation}</p>
      {skewed && (
        <p className="text-ink-muted">
          Spoken {spokenAt} · saved {savedAt}
        </p>
      )}
      <fieldset className="flex items-center gap-3">
        <legend className="sr-only">Save as</legend>
        {(["note", "task"] as const).map((kind) => (
          <label key={kind} className="flex items-center gap-1">
            <input type="radio" name={`kind-${capture.id}`} checked={draft.item_type === kind} onChange={() => set({ item_type: kind })} />
            {kind === "note" ? "Note" : "Task with deadline"}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-0.5">
        <span className="text-ink-faint">Title</span>
        <input value={draft.title} onChange={(event) => set({ title: event.target.value })} className="rounded border border-hairline bg-paper px-2 py-1" aria-label="Title" />
      </label>
      {draft.item_type === "note" && (
        <label className="flex flex-col gap-0.5">
          <span className="text-ink-faint">Note text</span>
          <textarea value={draft.content_md} onChange={(event) => set({ content_md: event.target.value })} rows={2} className="rounded border border-hairline bg-paper px-2 py-1" aria-label="Note text" />
        </label>
      )}
      {draft.item_type === "task" && (
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-ink-faint">Deadline date</span>
            <input type="date" value={draft.due_date} onChange={(event) => set({ due_date: event.target.value })} className="rounded border border-hairline bg-paper px-2 py-1" aria-label="Deadline date" />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-ink-faint">Time (optional)</span>
            <input type="time" value={draft.due_time} onChange={(event) => set({ due_time: event.target.value })} className="rounded border border-hairline bg-paper px-2 py-1" aria-label="Deadline time" />
          </label>
          {(draft.due_date || draft.due_time) && (
            <button type="button" onClick={() => set({ due_date: "", due_time: "" })} className="pb-1 text-ink-faint underline">
              No deadline
            </button>
          )}
        </div>
      )}
      {draft.item_type === "task" && alternatives.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Other dates">
          <span className="text-ink-faint">Or:</span>
          {alternatives.map((alt) => (
            <button key={`${alt.due_date}-${alt.anchor ?? ""}`} type="button" onClick={() => applyAlternative(alt)} className="rounded border border-hairline px-2 py-0.5 hover:border-accent-navy">
              Use {alt.due_date}
              {alt.anchor === "receipt" ? " (from when it was saved)" : ""}
            </button>
          ))}
        </div>
      )}
      <label className="flex flex-col gap-0.5">
        <span className="text-ink-faint">Where</span>
        <select value={draft.destinationId} onChange={(event) => set({ destinationId: event.target.value })} className="rounded border border-hairline bg-paper px-2 py-1" aria-label="Destination">
          <option value="">Inbox (no location yet)</option>
          {draft.destinationId && !locations.some((location) => location.id === draft.destinationId) && operation.destination && (
            <option value={draft.destinationId}>{operation.destination.path ?? operation.destination.title}</option>
          )}
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.path}
            </option>
          ))}
        </select>
        {proposal.resolution.destination.status === "ambiguous" && (
          <span className="text-ink-faint">Matches: {proposal.resolution.destination.candidates.map((candidate) => candidate.path).join("; ")}</span>
        )}
      </label>
      {warnings.length > 0 && <WarningList codes={warnings} />}
    </div>
  );
}

function WarningList({ codes }: { codes: string[] }) {
  return (
    <ul className="flex flex-col gap-0.5 text-ink-muted" aria-label="Things to check">
      {codes.map((code) => (
        <li key={code}>• {warningText(code)}</li>
      ))}
    </ul>
  );
}

function SaveAsPanel({
  capture,
  kind,
  setKind,
  text,
  setText,
  locations,
  heading,
  onCancel,
  onSaved,
}: {
  capture: Capture;
  kind: "note" | "task";
  setKind: (kind: "note" | "task") => void;
  text: string;
  setText: (text: string) => void;
  locations: Location[];
  heading: string;
  onCancel: () => void;
  onSaved: (capture: Capture) => void;
}) {
  const toast = useToast();
  const [title, setTitle] = useState(() => text.split("\n")[0].slice(0, 80));
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [busy, setBusy] = useState(false);
  const zone = capture.source_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

  async function save() {
    const target = locations.find((location) => location.id === destinationId);
    const item = {
      item_type: kind,
      title: title.trim() || text.trim().slice(0, 80) || "Untitled",
      content_md: kind === "note" ? text : "",
      ...(kind === "task" && dueDate ? { due_date: dueDate, ...(dueTime ? { due_time: `${dueTime}:00`, due_timezone: zone } : {}) } : {}),
      ...(target?.kind === "category" ? { category_id: target.id } : {}),
    };
    const container =
      target?.kind === "project" && target.version !== null
        ? { project_id: target.id, project_expected_version: target.version }
        : target?.kind === "folder" && target.version !== null
          ? { folder_id: target.id, folder_expected_version: target.version }
          : {};
    setBusy(true);
    try {
      const result = await interpretCaptureManually(capture.id, {
        expected_version: capture.version,
        expected_generation: capture.processing.generation,
        items: [{ kind: "create", item, ...container } as never],
      });
      toast.push(kind === "task" ? "Task added." : "Note added.", "success");
      onSaved(result.capture);
    } catch (err) {
      toast.push(err instanceof ApiError ? err.message : "Could not save.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2" role="group" aria-label={heading}>
      <div className="flex items-center gap-3">
        <span className="font-medium text-ink">{heading}</span>
        {(["note", "task"] as const).map((option) => (
          <label key={option} className="flex items-center gap-1">
            <input type="radio" name={`saveas-${capture.id}`} checked={kind === option} onChange={() => setKind(option)} />
            {option === "note" ? "Note" : "Task"}
          </label>
        ))}
      </div>
      <textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} aria-label="Text" className="rounded border border-hairline bg-paper p-2" />
      <input value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Title" placeholder="Title" className="rounded border border-hairline bg-paper px-2 py-1" />
      {kind === "task" && (
        <div className="flex gap-2">
          <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} aria-label="Deadline date" className="rounded border border-hairline bg-paper px-2 py-1" />
          <input type="time" value={dueTime} onChange={(event) => setDueTime(event.target.value)} aria-label="Deadline time" className="rounded border border-hairline bg-paper px-2 py-1" />
        </div>
      )}
      <select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} aria-label="Destination" className="rounded border border-hairline bg-paper px-2 py-1">
        <option value="">Inbox (no location yet)</option>
        {locations.map((location) => (
          <option key={location.id} value={location.id}>
            {location.path}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <button type="button" onClick={() => void save()} disabled={busy || !(title.trim() || text.trim())} className="rounded bg-accent-navy px-3 py-1.5 font-medium text-paper disabled:opacity-40">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-2 py-1 underline">
          Cancel
        </button>
      </div>
    </div>
  );
}
