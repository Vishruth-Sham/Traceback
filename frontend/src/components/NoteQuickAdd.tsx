"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Plus, RotateCcw, Search } from "lucide-react";
import {
  correctCapture,
  createCapture,
  createItem,
  getCapture,
  interpretCaptureManually,
  listLocations,
  retryCapture,
} from "@/lib/traceback";
import { ApiError, Capture, Location, isVoiceProposal } from "@/lib/types";
import { newIdempotencyKey } from "@/lib/apiClient";
import { useToast } from "./Toast";

type View = "compose" | "review" | "picker";

export function NoteQuickAdd() {
  const router = useRouter();
  const toast = useToast();
  const [view, setView] = useState<View>("compose");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [hint, setHint] = useState("");
  const [capture, setCapture] = useState<Capture | null>(null);
  const [selected, setSelected] = useState<Location | null>(null);
  const [locations, setLocations] = useState<Location[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [folderName, setFolderName] = useState("");
  const submission = useRef<{ key: string; capturedAt: string; timezone: string; title: string; body: string; hint: string } | null>(null);

  const storedProposal = capture?.processing.proposal;
  const proposal = storedProposal && !isVoiceProposal(storedProposal) ? storedProposal : null;
  const suggested = proposal?.destination_id
    ? locations.find((location) => location.id === proposal.destination_id && location.kind === proposal.destination_kind) ?? null
    : null;
  const destination = selected ?? suggested;

  useEffect(() => {
    listLocations().then((page) => setLocations(page.items)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (view !== "picker") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setView("review");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [view]);

  useEffect(() => {
    if (!capture || !["pending", "processing"].includes(capture.processing.state)) return;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getCapture(capture.id);
        setCapture(fresh);
        if (fresh.processing.state === "awaiting_review") setView("review");
      } catch { /* a transient poll failure is retried */ }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [capture]);

  async function findLocation() {
    if (!body.trim()) return;
    setBusy(true);
    try {
      let fresh = capture;
      if (!fresh) {
        submission.current ??= {
          key: newIdempotencyKey(),
          capturedAt: new Date().toISOString(),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          title,
          body,
          hint,
        };
        const saved = submission.current;
        fresh = await createCapture(
          {
            source_type: "typed",
            raw_text: saved.body,
            captured_at: saved.capturedAt,
            source_timezone: saved.timezone,
            timestamp_origin: "client_supplied",
            metadata: { processing_profile: "note_quick_add", supplied_title: saved.title || undefined, placement_hint: saved.hint || undefined },
          },
          saved.key,
        );
      } else {
        const effective = fresh.corrections;
        const savedTitle = (effective.supplied_title ?? fresh.metadata.supplied_title ?? "") as string;
        const savedBody = (effective.note_text ?? fresh.raw_text ?? "") as string;
        const savedHint = (effective.placement_hint ?? fresh.metadata.placement_hint ?? "") as string;
        if (title !== savedTitle || body !== savedBody || hint !== savedHint) {
          fresh = await correctCapture(fresh.id, {
            expected_version: fresh.version,
            note_text: body,
            supplied_title: title,
            placement_hint: hint,
          });
        }
      }
      setCapture(fresh);
      setSelected(null);
      setView("review");
    } catch (error) {
      toast.push(error instanceof ApiError ? error.message : "Could not save the note.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!capture) return;
    setBusy(true);
    try {
      setCapture(await retryCapture(capture.id, capture.version, capture.processing.generation));
    } catch (error) {
      toast.push(error instanceof ApiError ? error.message : "Retry failed.", "error");
    } finally { setBusy(false); }
  }

  async function save() {
    if (!capture || !body.trim()) return;
    setBusy(true);
    try {
      const currentDestination = selected ?? suggested;
      const item = { item_type: "note" as const, title: title.trim() || proposal?.title || "Untitled note", content_md: body, category_id: currentDestination?.kind === "category" ? currentDestination.id : null };
      const operation = currentDestination?.kind === "project"
        ? { kind: "create" as const, item: { ...item, category_id: null }, project_id: currentDestination.id, project_expected_version: currentDestination.version! }
        : currentDestination?.kind === "folder"
          ? { kind: "create" as const, item: { ...item, category_id: null }, folder_id: currentDestination.id, folder_expected_version: currentDestination.version! }
          : { kind: "create" as const, item };
      const result = await interpretCaptureManually(capture.id, {
        expected_version: capture.version,
        expected_generation: capture.processing.generation,
        items: [operation],
      });
      router.push(`/notes/${result.items[0].id}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setCapture(await getCapture(capture.id));
        toast.push("The note or destination changed. Review the latest state.", "error");
      } else toast.push(error instanceof ApiError ? error.message : "Could not save the note.", "error");
    } finally { setBusy(false); }
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? locations.filter((location) => location.path.toLowerCase().includes(needle)) : locations;
  }, [locations, query]);

  async function createFolderInline() {
    if (!folderName.trim() || !selected) return;
    setBusy(true);
    try {
      const folder = await createItem({
        item_type: "folder",
        title: folderName.trim(),
        ...(selected.kind === "category"
          ? { category_id: selected.id }
          : selected.kind === "project"
            ? { project_id: selected.id, project_expected_version: selected.version! }
            : { folder_id: selected.id, folder_expected_version: selected.version! }),
      });
      const fresh = await listLocations();
      setLocations(fresh.items);
      setSelected(fresh.items.find((location) => location.id === folder.id) ?? null);
      setFolderName("");
    } catch (error) { toast.push(error instanceof ApiError ? error.message : "Could not create folder.", "error"); }
    finally { setBusy(false); }
  }

  if (view === "picker") return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <button onClick={() => setView("review")} className="mb-5 flex items-center gap-1.5 text-[12px] text-ink-faint"><ArrowLeft size={13}/> Back</button>
      <h1 className="font-serif text-[25px] font-semibold">Choose a location</h1>
      <p className="mb-5 text-[13px] text-ink-muted">Categories, projects, and folders are all valid destinations.</p>
      <label className="mb-3 flex items-center gap-2 rounded border border-hairline bg-paper-soft px-3 py-2">
        <Search size={13}/><input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search locations" className="w-full bg-transparent text-[13px] outline-none"/>
      </label>
      <div role="listbox" className="max-h-[360px] overflow-y-auto rounded border border-hairline bg-paper-soft p-2">
        {filtered.map((location) => <button key={`${location.kind}:${location.id}`} role="option" aria-selected={selected?.id === location.id} onClick={() => setSelected(location)} className={`block w-full rounded px-3 py-2 text-left ${selected?.id === location.id ? "bg-accent-navy text-paper" : "hover:bg-paper"}`}><span className="block text-[13px]">{location.title}</span><span className="block text-[11px] opacity-70">{location.path}</span></button>)}
      </div>
      {selected && <div className="mt-3 flex gap-2"><input value={folderName} onChange={(e) => setFolderName(e.target.value)} placeholder={`New folder inside ${selected.title}`} className="flex-1 rounded border border-hairline bg-paper-soft px-3 py-2 text-[12px] outline-none"/><button onClick={createFolderInline} disabled={busy || !folderName.trim()} className="flex items-center gap-1 rounded border border-hairline px-3 text-[12px]"><Plus size={12}/> Create</button></div>}
      <div className="mt-5 flex justify-end"><button onClick={() => setView("review")} disabled={!selected} className="rounded bg-accent-navy px-4 py-2 text-[13px] text-paper disabled:opacity-40">Use this location</button></div>
    </div>
  );

  if (view === "review") return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <button onClick={() => setView("compose")} className="mb-5 flex items-center gap-1.5 text-[12px] text-ink-faint"><ArrowLeft size={13}/> Back to note</button>
      <h1 className="font-serif text-[25px] font-semibold">Review note</h1>
      {capture && ["pending", "processing"].includes(capture.processing.state) && <div className="mt-8 flex items-center gap-2 text-[13px] text-ink-muted"><Loader2 size={14} className="animate-spin"/> Finding a location with local Qwen…</div>}
      {capture?.processing.state === "failed" && <div className="mt-6 rounded border border-danger bg-danger-soft p-4 text-[13px]"><p>Location suggestion failed. Your note is saved.</p><div className="mt-3 flex gap-2"><button onClick={retry} className="flex items-center gap-1 rounded border border-danger px-3 py-1.5"><RotateCcw size={12}/> Retry</button><button onClick={() => setView("picker")} className="rounded border border-danger px-3 py-1.5">Choose location manually</button></div></div>}
      {(proposal || selected) && <div className="mt-6 rounded border border-hairline bg-paper-soft p-5"><div className="text-[11px] uppercase tracking-wide text-ink-faint">Suggested location</div><div className="mt-1 font-serif text-[20px] font-semibold">{destination?.path ?? "Inbox"}</div>{proposal?.explanation && <p className="mt-2 text-[12.5px] text-ink-muted">{proposal.explanation}</p>}<button onClick={() => setView("picker")} className="mt-4 text-[12px] text-accent-navy underline">Choose a different location</button></div>}
      <div className="mt-5 rounded border border-hairline bg-paper-soft p-5"><h2 className="font-serif text-[21px] font-semibold">{title.trim() || proposal?.title || "Untitled note"}</h2><pre className="mt-3 whitespace-pre-wrap font-mono text-[13px]">{body}</pre></div>
      <div className="mt-5 flex justify-between">
        {capture && ["pending", "processing"].includes(capture.processing.state) ? (
          <button onClick={() => setView("picker")} className="rounded border border-hairline px-4 py-2 text-[13px]">Choose location manually</button>
        ) : <span />}
        <button onClick={save} disabled={busy || !capture} className="rounded bg-accent-navy px-4 py-2 text-[13px] text-paper disabled:opacity-40">Accept and save</button>
      </div>
    </div>
  );

  return <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
    <button onClick={() => router.push("/inbox")} className="mb-5 flex items-center gap-1.5 text-[12px] text-ink-faint"><ArrowLeft size={13}/> Inbox</button>
    <h1 className="font-serif text-[25px] font-semibold">Quick add note</h1><p className="mb-5 text-[13px] text-ink-muted">Write freely. Traceback saves your exact note before suggesting where it belongs.</p>
    <div className="rounded border border-hairline bg-paper-soft p-5"><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional title" aria-label="Title" className="mb-3 w-full border-b border-hairline bg-transparent pb-2 font-serif text-[21px] font-semibold outline-none"/><textarea autoFocus value={body} onChange={(e) => setBody(e.target.value)} rows={13} placeholder="Write your note in Markdown…" aria-label="Note" className="w-full resize-y bg-transparent text-[13.5px] outline-none"/><input value={hint} onChange={(e) => setHint(e.target.value)} placeholder="Where might this belong? (optional)" aria-label="Placement hint" className="mt-4 w-full rounded border border-hairline bg-paper px-3 py-2 text-[12.5px] outline-none"/></div>
    {capture && <p className="mt-3 text-[11.5px] text-ink-faint">Saved in Inbox. Editing and finding again creates a versioned correction.</p>}
    <div className="mt-5 flex justify-end"><button onClick={findLocation} disabled={busy || !body.trim()} className="flex items-center gap-2 rounded bg-accent-navy px-4 py-2 text-[13px] text-paper disabled:opacity-40">{busy && <Loader2 size={13} className="animate-spin"/>} Find location</button></div>
  </div>;
}
