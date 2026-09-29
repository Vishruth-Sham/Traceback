"""Database-aware helpers for voice-command captures.

Business rules live in the pure `backend.voice_policy` package; this module only
gathers stored evidence (transcript, anchors, catalog) for it and derives the
audit records. It must not import `backend.captures` (which imports it).
"""
import hashlib
import json
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.capture_models import Capture
from backend.config import Settings
from backend.errors import DomainError
from backend.locations import build_catalog
from backend.models import Item
from backend.voice_policy import POLICY_VERSION, evaluate

VOICE_PROFILE = "voice_command"


def profile_of(capture: Capture) -> str:
    return capture.source_metadata.get("processing_profile", "general")


def is_voice(capture: Capture) -> bool:
    return profile_of(capture) == VOICE_PROFILE


def capability_disabled() -> DomainError:
    return DomainError("capability_disabled", "Voice commands are disabled on this server", 403)


def require_voice_enabled(settings: Settings, *, status: int = 403) -> None:
    if not settings.voice_commands_enabled:
        error = capability_disabled()
        error.status_code = status
        raise error


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def effective_transcript(capture: Capture, corrections: dict[str, Any]) -> str | None:
    """Corrected transcript, else the checkpointed STT transcript, else the immutable typed text."""
    for candidate in (corrections.get("transcript_text"), capture.processing.transcript, capture.raw_text):
        if candidate and str(candidate).strip():
            return str(candidate)
    return None


def _aware(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise DomainError("invalid_input", "captured_at must include a timezone offset", 422)
    return parsed


def effective_anchor(capture: Capture, corrections: dict[str, Any], default_timezone: str) -> tuple[datetime, str]:
    raw = corrections.get("captured_at") or capture.captured_at or capture.created_at
    zone = corrections.get("source_timezone") or capture.source_timezone or default_timezone
    return _aware(raw), zone


def proposal_digest(proposal: dict[str, Any]) -> str:
    body = {key: value for key, value in proposal.items() if key != "proposal_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_voice_proposal(
    session: Session,
    capture: Capture,
    corrections: dict[str, Any],
    slots: dict[str, Any],
    model_confidence: str | None,
    settings: Settings,
    now: datetime,
) -> dict[str, Any]:
    transcript = effective_transcript(capture, corrections)
    if transcript is None:
        raise DomainError("transcript_missing", "A transcript must be checkpointed before a proposal", 422)
    anchor, zone = effective_anchor(capture, corrections, settings.user_timezone)
    catalog = build_catalog(session)

    def title_exists(title: str) -> bool:
        return (
            session.scalar(
                select(Item.id)
                .where(func.lower(Item.title) == title.lower(), Item.archived_at.is_(None), Item.item_type.in_(("note", "task")))
                .limit(1)
            )
            is not None
        )

    proposal = evaluate(
        transcript=transcript,
        slots=slots,
        captured_at=anchor,
        received_at=capture.created_at,
        source_timezone=zone,
        now=now,
        catalog=catalog,
        entry_point=capture.source_metadata.get("entry_point"),
        allowed_intents=capture.source_metadata.get("allowed_intents"),
        contextual_id=capture.source_metadata.get("contextual_item_id"),
        title_exists=title_exists,
        auto_apply_intents=[],  # review-first release: the policy can never mark a proposal auto-apply eligible
        model_confidence=model_confidence,
    )
    original = capture.source_metadata.get("observed_captured_at") or capture.captured_at
    proposal["resolution"]["anchor"]["observed_captured_at"] = original if isinstance(original, str) else (original.isoformat() if original else None)
    return proposal


def overdue_by_seconds(operation: dict[str, Any], default_timezone: str, now: datetime) -> int | None:
    """Seconds by which the operation's deadline has passed at `now`, or None when it has not."""
    due_date = operation.get("due_date")
    if not due_date:
        return None
    day = date.fromisoformat(due_date) if isinstance(due_date, str) else due_date
    wall = operation.get("due_time")
    zone_name = operation.get("due_timezone") or default_timezone
    zone = ZoneInfo(zone_name)
    if wall:
        clock = time.fromisoformat(wall) if isinstance(wall, str) else wall
        due_at = datetime.combine(day, clock).replace(tzinfo=zone)
        return int((now - due_at).total_seconds()) if due_at < now else None
    today = now.astimezone(zone).date()
    if day < today:
        end_of_day = datetime.combine(day, time(23, 59, 59)).replace(tzinfo=zone)
        return max(1, int((now - end_of_day).total_seconds()))
    return None


def _norm(value: Any) -> Any:
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    return value if value not in ("", None) else None


def voice_audit(
    *,
    stored: dict[str, Any] | None,
    submitted: dict[str, Any],
    content_md: str,
    accept_path: str,
    overdue_confirmed: bool,
) -> dict[str, Any]:
    """Server-computed override evidence; nothing here is taken from the client."""
    operation = (stored or {}).get("operation") if stored else None
    edited: list[str] | None = None
    if operation is not None:
        edited = []
        for field in ("title", "content_md", "due_date", "due_time", "due_timezone", "item_type"):
            if _norm(operation.get(field)) != _norm(submitted.get(field)):
                edited.append("content" if field == "content_md" else field)
        stored_dest = operation.get("destination")
        stored_key = (stored_dest["kind"], stored_dest["id"]) if stored_dest else None
        sub_dest = submitted.get("destination")
        submitted_key = (sub_dest["kind"], sub_dest["id"]) if sub_dest else None
        if stored_key != submitted_key:
            edited.append("destination")
        implied = "create_task" if submitted.get("item_type") == "task" else "create_note"
        if stored and stored.get("intent") != implied:
            edited.append("intent")
    return {
        "proposal_present": stored is not None,
        "proposal_generation": stored.get("generation") if stored else None,
        "proposal_sha256": stored.get("proposal_sha256") if stored else None,
        "policy_version": stored.get("policy_version", POLICY_VERSION) if stored else None,
        "accept_path": accept_path,
        "accepted": {
            "item_type": submitted.get("item_type"),
            "title": submitted.get("title"),
            "due_date": _norm(submitted.get("due_date")),
            "due_time": _norm(submitted.get("due_time")),
            "due_timezone": submitted.get("due_timezone"),
            "destination": submitted.get("destination"),
            "content_sha256": sha256_text(content_md),
            "content_length": len(content_md),
        },
        "edited_fields": edited,
        "overdue_confirmed": overdue_confirmed,
    }
