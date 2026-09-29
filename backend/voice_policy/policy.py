"""Compose grounding, intent, date, and destination rules into a stored CommandProposal.

Everything here is derived by the backend from stored evidence. Processor-supplied
slots are untrusted suggestions; model flags can only *add* review, and nothing
the model reports (including confidence) influences the disposition.
"""
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.voice_policy.dates import parse_deadline
from backend.voice_policy.destinations import resolve_destination
from backend.voice_policy.intent import (
    ORGANIZATION_INTENTS,
    derive_intent,
    derive_note_title,
    derive_task_title,
    deterministic_flags,
    strip_span,
)
from backend.voice_policy.text import is_grounded

POLICY_VERSION = 1
CREATE_INTENTS = {"create_note", "create_task"}
MODEL_FLAGS = {"multi_intent", "self_correction", "unclear_audio", "requested_delete", "unsupported_request"}
DELAYED_INGEST_SECONDS = 300
CLOCK_AHEAD_SECONDS = -120
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _non_english(transcript: str) -> bool:
    letters = _LETTERS.findall(transcript)
    if len(letters) < 4:
        return False
    return sum(1 for ch in letters if not _LATIN.match(ch)) / len(letters) > 0.3


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _destination_out(entry: dict[str, Any] | None, source: str | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {"kind": entry["kind"], "id": entry["id"], "title": entry.get("title"), "path": entry.get("path"), "version": entry.get("version"), "source": source}


def evaluate(
    *,
    transcript: str,
    slots: dict[str, Any],
    captured_at: datetime,
    received_at: datetime,
    source_timezone: str,
    now: datetime,
    catalog: list[dict[str, Any]],
    entry_point: str | None = None,
    allowed_intents: list[str] | None = None,
    contextual_id: str | None = None,
    title_exists: Callable[[str], bool] | None = None,
    auto_apply_intents: list[str] | tuple[str, ...] = (),
    model_confidence: str | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []

    def warn(code: str) -> None:
        if code not in warnings:
            warnings.append(code)

    transcript = transcript or ""
    zone = ZoneInfo(source_timezone)
    model_intent = slots.get("intent")

    # --- model flags may only add review; backend flags are derived independently ---
    for flag in slots.get("flags") or []:
        if flag in MODEL_FLAGS:
            warn(flag)
    derived_flags = deterministic_flags(transcript)
    for flag in sorted(derived_flags - {"organization_request"}):
        warn(flag)
    if _non_english(transcript):
        warn("unsupported_language")

    # --- grounding of every span the model supplied ---
    def grounded(name: str) -> str | None:
        value = slots.get(name)
        if value is None or not str(value).strip():
            return None
        if is_grounded(value, transcript):
            return str(value).strip()
        warn("ungrounded_text")
        return None

    date_phrase = grounded("date_phrase")
    time_phrase = grounded("time_phrase")
    destination_phrase = grounded("destination_phrase")
    grounded("target_phrase")

    # --- intent ---
    lexicon = derive_intent(transcript, has_deadline=bool(date_phrase or time_phrase))
    intent = lexicon["intent"]
    basis = lexicon["basis"]
    alternative_intent = lexicon["alternative"]
    if lexicon["conflict"]:
        warn("intent_conflict")
    restricted = False
    unsupported_reason: str | None = None
    if "requested_delete" in warnings or "unsupported_request" in warnings:
        intent, unsupported_reason = "unsupported", "unsupported_request"
    elif model_intent in ORGANIZATION_INTENTS or "organization_request" in derived_flags:
        intent, unsupported_reason = "unsupported", "organization_not_available"
    elif model_intent == "unsupported" and intent is None:
        intent, unsupported_reason = "unsupported", "unsupported_request"
    elif intent is None:
        if model_intent == "capture_only":
            intent, basis = "capture_only", "model_capture_only"
        else:
            if model_intent in CREATE_INTENTS:
                alternative_intent = model_intent
            intent, basis = "ambiguous", basis or "no_lexicon_match"
    else:
        if not lexicon["explicit"]:
            warn("intent_inferred")
        if model_intent in CREATE_INTENTS and model_intent != intent:
            warn("intent_conflict")
            alternative_intent = alternative_intent or model_intent
        elif model_intent in ("capture_only", "ambiguous", "unsupported"):
            warn("intent_conflict")
    lexicon_agrees = model_intent == intent

    if intent in CREATE_INTENTS and allowed_intents is not None and intent not in allowed_intents:
        restricted = True
        unsupported_reason = "restricted_launcher"
        alternative_intent = intent
        intent = "unsupported"

    # --- destination ---
    destination = resolve_destination(destination_phrase, catalog)
    destination_source = "spoken" if destination["status"] != "none" else None
    if destination["status"] == "none" and contextual_id:
        context = next((entry for entry in catalog if entry["id"] == str(contextual_id)), None)
        if context is not None:
            destination = {"status": "resolved", "phrase": None, "source": "surface_context", "candidates": [{k: context.get(k) for k in ("kind", "id", "title", "path", "version")}],
                           "chosen": {k: context.get(k) for k in ("kind", "id", "title", "path", "version")}, "confidence": "low"}
            destination_source = "surface_context"
            warn("destination_from_context")
    if destination["status"] == "ambiguous":
        warn("destination_ambiguous")
    elif destination["status"] == "not_found":
        warn("destination_not_found")
    elif destination["status"] == "resolved" and destination_source == "spoken" and destination["confidence"] == "low":
        warn("destination_fuzzy")

    # --- title / content / deadline (creates only) ---
    operation: dict[str, Any] | None = None
    deadline_info: dict[str, Any] = {"phrase": date_phrase, "time_phrase": time_phrase, "basis": None, "default": None, "alternatives": []}
    skew_s = int((received_at - captured_at).total_seconds())
    anchor_info = {
        "captured_at": _iso(captured_at),
        "received_at": _iso(received_at),
        "skew_s": skew_s,
        "timezone": source_timezone,
    }
    if intent in CREATE_INTENTS:
        item_type = "task" if intent == "create_task" else "note"
        model_title = slots.get("title")
        title = None
        if model_title and str(model_title).strip():
            if is_grounded(model_title, transcript):
                title = str(model_title).strip()
                if item_type == "task":
                    for phrase in (time_phrase, date_phrase):
                        title = strip_span(title, phrase) or title
            else:
                warn("ungrounded_text")
        content_md = ""
        content = slots.get("content")
        if content and str(content).strip():
            if is_grounded(content, transcript):
                content_md = str(content).strip() if item_type == "note" else ""
            else:
                warn("ungrounded_text")
        if title is None:
            if item_type == "task":
                title = derive_task_title(transcript, date_phrase=date_phrase, time_phrase=time_phrase, destination_phrase=destination_phrase)
            else:
                title, derived = derive_note_title(transcript, destination_phrase=destination_phrase)
                if derived:
                    warn("title_derived")
                    content_md = content_md or transcript.strip()
            if title and item_type == "task":
                warn("title_derived")
        if title:
            title = title[:1].upper() + title[1:]  # spoken/STT text is often lowercase; only the first letter is touched
        if not title:
            intent, basis = "ambiguous", "no_title"
            warn("title_missing")
        else:
            due: dict[str, Any] = {"due_date": None, "due_time": None, "due_timezone": None}
            if item_type == "task" and (date_phrase or time_phrase):
                result = parse_deadline(date_phrase, time_phrase, anchor=captured_at, timezone=source_timezone, receipt=received_at)
                for code in result.warnings:
                    warn(code)
                due = result.as_dict()
                deadline_info.update(basis=result.basis, default=due["due_date"], alternatives=result.alternatives)
                if result.relative and skew_s > DELAYED_INGEST_SECONDS:
                    warn("delayed_ingest")
                elif result.relative and skew_s < CLOCK_AHEAD_SECONDS:
                    warn("clock_ahead")
                if result.due_date is not None:
                    if result.due_time is not None:
                        due_at = datetime.combine(result.due_date, result.due_time).replace(tzinfo=ZoneInfo(result.due_timezone))
                        if due_at < now:
                            warn("deadline_past")
                    elif result.due_date < now.astimezone(zone).date():
                        warn("deadline_past")
            if title_exists is not None and title_exists(title):
                warn("possible_duplicate")
            dest_entry = destination["chosen"]
            operation = {
                "type": "create",
                "item_type": item_type,
                "title": title,
                "content_md": content_md,
                **due,
                "destination": _destination_out(dest_entry, destination_source),
            }

    # --- disposition (model confidence is deliberately not an input) ---
    reasons: list[str] = []
    if intent == "unsupported":
        disposition = "reject"
        reasons.append(unsupported_reason or "unsupported_request")
    elif operation is None:
        disposition = "review"
        reasons.append("no_operation_" + intent)
    else:
        disposition = "review"
        reasons.extend(warnings)
        eligible = (
            intent == "create_task"
            and intent in auto_apply_intents
            and basis in ("explicit_reminder_verb", "explicit_task_word")
            and lexicon_agrees
            and operation["destination"] is None
            and entry_point != "mcp_typed"
            and not warnings
            and not slots.get("flags")
        )
        if eligible:
            disposition = "auto_apply_eligible"
        elif intent not in auto_apply_intents:
            reasons.append("auto_apply_disabled")

    explanation = _explain(intent, operation, destination, unsupported_reason)
    proposal = {
        "kind": "voice_command",
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "policy_evaluated_at": _iso(now),
        "intent": intent,
        "operation": operation,
        "resolution": {
            "intent": {"basis": basis, "lexicon_agrees": lexicon_agrees, "alternative": alternative_intent, "model_intent": model_intent},
            "anchor": anchor_info,
            "date": deadline_info,
            "destination": destination,
        },
        "warnings": warnings,
        "model_confidence": model_confidence,
        "explanation": explanation,
        "disposition": disposition,
        "disposition_reasons": reasons,
    }
    proposal["inputs_sha256"] = _sha(
        {"slots": slots, "transcript": transcript, "anchor": anchor_info, "catalog": [(e["id"], e.get("version")) for e in catalog if e["id"] in {c["id"] for c in destination.get("candidates", [])}],
         "allowed_intents": allowed_intents, "contextual_id": contextual_id, "policy_version": POLICY_VERSION}
    )
    return proposal


def _explain(intent: str, operation: dict | None, destination: dict, reason: str | None) -> str:
    if intent == "unsupported":
        return {
            "restricted_launcher": "This launcher can't do that; use the global mic. Nothing was saved.",
            "organization_not_available": "Organizing existing items by voice isn't available yet. Nothing was changed.",
        }.get(reason or "", "This request isn't supported by voice. Nothing was changed.")
    if intent == "capture_only":
        return "Kept as a capture. Choose whether to save it as a note or a task."
    if operation is None:
        return "Couldn't tell whether this is a note or a task. Pick one, or keep it in Inbox."
    kind = operation["item_type"]
    parts = [f"Recognized a {kind}"]
    if operation.get("due_date"):
        parts.append("with a deadline")
    dest = operation.get("destination")
    if dest:
        parts.append(f"for {dest['path']}")
    return " ".join(parts) + "."
