"""Voice-command REST surface: capabilities, atomic ingest, transcript checkpoint, claim-next, proposal accept.

Business rules live in `backend.voice_policy` and the shared capture transaction in
`backend.captures`; this module is transport, fencing, and audit only.
"""
import errno
import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import contains_eager

from backend.api import ActionContext, SessionDep, SettingsDep, authenticate
from backend.asset_models import Asset, CaptureAsset
from backend.capture_models import Capture, CaptureProcessing
from backend.capture_schemas import (
    CaptureInterpretationRequest,
    ClaimNextRequest,
    CreateInterpretationItem,
    ProposalAcceptRequest,
    ResolveQueryRequest,
    TranscriptCheckpointRequest,
    VoiceCreateIntent,
    VoiceEntryPoint,
)
from backend.captures import (
    add_capture_revision,
    apply_interpretation,
    capture_state_details,
    clear_lease,
    get_capture,
    json_capture,
    processing_conflict,
    require_live_lease,
    take_lease,
    validate_generation,
)
from backend.errors import DomainError
from backend.models import Action, Category, Item
from backend.schemas import ItemCreate
from backend.services import begin_action, finish_action, require_version, utcnow
from backend.voice_policy import POLICY_VERSION
from backend.voice_service import (
    effective_anchor,
    is_voice,
    overdue_by_seconds,
    profile_of,
    require_voice_enabled,
    sha256_text,
)
from backend.captures import effective_corrections
from backend.voice_query import resolve as resolve_voice_query

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

_HEX64 = r"^[0-9a-fA-F]{64}$"


# --------------------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------------------
def _free_disk(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return shutil.disk_usage(directory).free


@router.get("/capabilities")
def capabilities(session: SessionDep, settings: SettingsDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        low_disk = _free_disk(settings.asset_dir.resolve()) < settings.voice_min_free_disk_bytes * 2
    except OSError:
        low_disk = True
    profile = Capture.source_metadata["processing_profile"].astext
    pending = session.execute(
        select(func.count(), func.min(CaptureProcessing.queued_at))
        .select_from(Capture)
        .join(CaptureProcessing)
        .where(Capture.archived_at.is_(None), CaptureProcessing.state == "pending", profile == "voice_command")
    ).one()
    oldest_age = int((utcnow() - pending[1]).total_seconds()) if pending[1] else None
    return {
        "voice_commands": {
            "enabled": settings.voice_commands_enabled,
            "accepts_audio": settings.voice_commands_enabled,
            "reason": None if settings.voice_commands_enabled else "voice_disabled",
            "max_seconds": settings.voice_max_seconds,
            "max_upload_bytes": settings.voice_max_upload_bytes,
            "accepted_mime_types": settings.voice_mime_types,
            "allowed_intents": ["create_note", "create_task"],
            "auto_apply_intents": [],
            "policy_version": POLICY_VERSION,
            "low_disk": low_disk,
        },
        "query_commands": {
            "enabled": settings.voice_commands_enabled,
            "kinds": ["overdue_tasks", "inbox_summary", "search", "navigate", "followup_select"],
        },
        "queue": {"pending_voice": pending[0], "oldest_pending_age_s": oldest_age},
    }


# --------------------------------------------------------------------------------------
# Atomic, idempotent audio ingest
# --------------------------------------------------------------------------------------
def _detect_mime(path: Path) -> str:
    try:
        return subprocess.run(["/usr/bin/file", "--brief", "--mime-type", str(path)], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "application/octet-stream"


@router.post("/voice-captures", status_code=201)
async def create_voice_capture(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    context: ActionContext,
    size: Annotated[int, Query(ge=1)],
    sha256: Annotated[str, Query(pattern=_HEX64)],
    captured_at: AwareDatetime,
    source_timezone: Annotated[str, Query(min_length=1, max_length=64)],
    entry_point: VoiceEntryPoint,
    filename: Annotated[str, Query(min_length=1, max_length=255)] = "recording",
    contextual_item_id: uuid.UUID | None = None,
    contextual_capture_id: uuid.UUID | None = None,
    allowed_intent: Annotated[list[VoiceCreateIntent] | None, Query(max_length=2)] = None,
    duration_ms: Annotated[int | None, Query(ge=0, le=3_600_000)] = None,
):
    key = context[0]
    if not key:
        raise DomainError("idempotency_key_required", "POST /voice-captures requires an Idempotency-Key header", 400)
    if entry_point == "mcp_typed":
        raise DomainError("invalid_input", "mcp_typed is reserved for typed voice commands", 422)
    if any(c in filename for c in ("\x00", "\r", "\n")):
        raise DomainError("invalid_input", "Filename contains invalid characters", 422)
    try:
        ZoneInfo(source_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("invalid_input", "source_timezone must be an IANA timezone", 422) from None
    require_voice_enabled(settings)
    if size > settings.voice_max_upload_bytes:
        raise DomainError("upload_too_large", "Recording exceeds the voice upload limit", 413, {"max_upload_bytes": settings.voice_max_upload_bytes})
    if duration_ms is not None and duration_ms > (settings.voice_max_seconds + 2) * 1000:
        raise DomainError("duration_too_long", "Recording exceeds the voice duration limit", 422, {"max_seconds": settings.voice_max_seconds})
    declared_length = request.headers.get("content-length")
    if declared_length is not None and declared_length.isdigit() and int(declared_length) != size:
        raise DomainError("size_mismatch", "Content-Length does not match the declared size", 400)
    directory = settings.asset_dir.resolve()
    if await run_in_threadpool(_free_disk, directory) - size < settings.voice_min_free_disk_bytes:
        raise DomainError("insufficient_storage", "Not enough free disk space for this recording", 507)

    digest_hex = sha256.lower()
    payload = {
        "size": size,
        "sha256": digest_hex,
        "filename": filename,
        "captured_at": captured_at.isoformat(),
        "source_timezone": source_timezone,
        "entry_point": entry_point,
        "contextual_item_id": str(contextual_item_id) if contextual_item_id else None,
        "contextual_capture_id": str(contextual_capture_id) if contextual_capture_id else None,
        "allowed_intents": sorted(allowed_intent) if allowed_intent else None,
        "duration_ms": duration_ms,
    }
    # Blocking DB calls run in the thread pool so a same-key request waiting on the advisory
    # lock can never stall the event loop that is still streaming the first request's body.
    action, replay = await run_in_threadpool(begin_action, session, "create_voice_capture", payload, key, "user", context[1])
    if replay:
        return replay

    profile = Capture.source_metadata["processing_profile"].astext
    window_start = utcnow() - timedelta(seconds=settings.voice_duplicate_window_s)
    duplicate = await run_in_threadpool(
        lambda: session.scalar(
            select(Capture.id)
            .join(CaptureAsset, CaptureAsset.capture_id == Capture.id)
            .join(Asset, Asset.id == CaptureAsset.asset_id)
            .where(Asset.sha256 == digest_hex, Capture.archived_at.is_(None), profile == "voice_command", Capture.created_at > window_start)
            .limit(1)
        )
    )
    if duplicate:
        raise DomainError("duplicate_recording", "This recording was already saved moments ago", 409, {"capture_id": str(duplicate)})

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    asset_id = uuid.uuid4()
    destination = directory / str(asset_id)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            counted = 0
            digest = hashlib.sha256()
            async for chunk in request.stream():
                counted += len(chunk)
                if counted > size or counted > settings.voice_max_upload_bytes:
                    raise DomainError("size_mismatch", "Body is larger than the declared size", 422)
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if counted != size:
            raise DomainError("size_mismatch", "Body is smaller than the declared size", 422)
        if digest.hexdigest() != digest_hex:
            raise DomainError("digest_mismatch", "Body does not match the declared sha256", 422)
        detected = await run_in_threadpool(_detect_mime, temporary)
        if detected.lower() not in settings.voice_mime_types:
            raise DomainError("unsupported_media", "This audio format is not accepted", 415, {"detected_mime_type": detected})
        os.replace(temporary, destination)
        temporary = None
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

        def persist() -> dict[str, Any]:
            safe_name = Path(filename).name or "recording"
            asset = Asset(
                id=asset_id, storage_key=str(asset_id), original_filename=safe_name, extension=Path(safe_name).suffix[:32],
                declared_mime_type=(request.headers.get("content-type") or "application/octet-stream")[:255], detected_mime_type=detected,
                byte_size=counted, sha256=digest_hex, source_created_at=captured_at, timestamp_origin="client_supplied",
            )
            metadata: dict[str, Any] = {
                "processing_profile": "voice_command",
                "entry_point": entry_point,
                "observed_captured_at": captured_at.isoformat(),
                "timestamp_precision": "exact",
            }
            if contextual_item_id:
                metadata["contextual_item_id"] = str(contextual_item_id)
            if contextual_capture_id:
                metadata["contextual_capture_id"] = str(contextual_capture_id)
            if allowed_intent:
                metadata["allowed_intents"] = sorted(allowed_intent)
            if duration_ms is not None:
                metadata["duration_ms"] = duration_ms
            capture = Capture(
                source_type="audio", captured_at=captured_at, source_timezone=source_timezone, timestamp_origin="client_supplied", source_metadata=metadata,
            )
            capture.processing = CaptureProcessing(state="pending", generation=1, attempt_count=0)
            session.add_all([asset, capture])
            session.flush()
            session.add(CaptureAsset(capture_id=capture.id, asset_id=asset.id))
            add_capture_revision(session, capture, action, "created", {"source_type": "audio", "profile": "voice_command", "entry_point": entry_point})
            session.flush()
            result = json_capture(session, capture, action.id)
            finish_action(action, result)
            session.commit()
            return result

        return await run_in_threadpool(persist)
    except BaseException as exc:
        await run_in_threadpool(session.rollback)
        if temporary:
            temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            raise DomainError("insufficient_storage", "Not enough free disk space for this recording", 507) from exc
        raise


# --------------------------------------------------------------------------------------
# Transcript checkpoint (processor-only; no version bump)
# --------------------------------------------------------------------------------------
@router.post("/captures/{capture_id}/transcript")
def checkpoint_transcript(capture_id: uuid.UUID, body: TranscriptCheckpointRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "checkpoint_transcript", payload, context[0], actor="processor", client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    processing = capture.processing
    validate_generation(processing, body.expected_generation)
    if not is_voice(capture):
        raise DomainError("invalid_transcript", "Only voice-command captures accept transcript checkpoints", 422)
    require_live_lease(processing, body.lease_token)
    now = utcnow()
    if body.no_speech:
        processing.state = "failed"
        processing.error_code = "no_speech"
        processing.error_message = "No speech was detected in the recording"
        processing.finished_at = now
        clear_lease(processing)
        capture.version += 1
        add_capture_revision(session, capture, action, "processing_failed", {"generation": processing.generation, "error_code": "no_speech"})
        session.flush()
        result = {"capture_id": str(capture.id), "state": "failed", "version": capture.version, "generation": processing.generation, "transcript_saved": False}
    else:
        processing.transcript = body.transcript
        # Evidence lives on this action row and is folded into the next revision; no revision or version bump here.
        result = {
            "capture_id": str(capture.id),
            "state": processing.state,
            "version": capture.version,
            "generation": processing.generation,
            "transcript_saved": True,
            "transcript_sha256": sha256_text(body.transcript or ""),
            "transcript_length": len(body.transcript or ""),
            "language": body.language,
            "stt_model_id": body.stt_model_id,
            "duration_ms": body.duration_ms,
            "checkpointed_at": now.isoformat(),
        }
    finish_action(action, result)
    session.commit()
    return result


# --------------------------------------------------------------------------------------
# Read-only query resolution (processor-only). The processor supplies Qwen's classification
# (`kind`, `phrase`); every DB read happens here and the processor never sees item data. When
# there is nothing to resolve, `is_query` is false and `processing` is left untouched (still
# "processing") so the processor falls through to its normal create flow.
# --------------------------------------------------------------------------------------
@router.post("/captures/{capture_id}/resolve-query")
def resolve_query(capture_id: uuid.UUID, body: ResolveQueryRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "resolve_voice_query", payload, context[0], actor="processor", client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    processing = capture.processing
    validate_generation(processing, body.expected_generation)
    if not is_voice(capture):
        raise DomainError("invalid_input", "Only voice-command captures can resolve a query", 422)
    require_live_lease(processing, body.lease_token)
    corrections = effective_corrections(session, capture.id)
    transcript = corrections.get("transcript_text") or processing.transcript or (capture.raw_text if capture.source_type == "typed" else None)
    if not transcript:
        raise DomainError("invalid_input", "No transcript is available to classify", 422)

    result = resolve_voice_query(session, capture, transcript, kind=body.kind, phrase=body.phrase)
    if result is None:
        response = {"capture_id": str(capture.id), "state": processing.state, "version": capture.version, "generation": processing.generation, "is_query": False}
        finish_action(action, response)
        session.commit()
        return response

    processing.state = "resolved"
    processing.query_result = result
    processing.finished_at = utcnow()
    clear_lease(processing)
    capture.version += 1
    add_capture_revision(session, capture, action, "query_resolved", {"generation": processing.generation, "kind": result.get("kind")})
    session.flush()
    response = {
        "capture_id": str(capture.id),
        "state": processing.state,
        "version": capture.version,
        "generation": processing.generation,
        "is_query": True,
        "query_result": result,
    }
    finish_action(action, response)
    session.commit()
    return response


# --------------------------------------------------------------------------------------
# claim-next: backend-owned queue fairness
# --------------------------------------------------------------------------------------
def _claimable(capture: Capture, now) -> bool:
    processing = capture.processing
    return capture.archived_at is None and (
        processing.state == "pending"
        or (processing.state == "processing" and processing.lease_expires_at is not None and processing.lease_expires_at <= now)
    )


@router.post("/captures/claim-next")
def claim_next(body: ClaimNextRequest, session: SessionDep, context: ActionContext, settings: SettingsDep):
    now = utcnow()
    statement = (
        select(Capture)
        .join(CaptureProcessing)
        .options(contains_eager(Capture.processing))
        .where(
            Capture.archived_at.is_(None),
            or_(CaptureProcessing.state == "pending", (CaptureProcessing.state == "processing") & (CaptureProcessing.lease_expires_at <= now)),
        )
        .order_by(CaptureProcessing.queued_at, Capture.id)
        .limit(50)
    )
    candidates = list(session.scalars(statement).unique().all())
    if not settings.voice_commands_enabled:
        candidates = [c for c in candidates if not is_voice(c)]
    if not candidates:
        session.rollback()
        return Response(status_code=204)
    aging = timedelta(seconds=settings.voice_queue_aging_s)
    aged = [c for c in candidates if c.processing.queued_at <= now - aging]
    if aged:
        ranked = aged + [c for c in candidates if c not in aged]
    else:
        voice = [c for c in candidates if is_voice(c)]
        others = [c for c in candidates if not is_voice(c)]
        recent = session.scalars(
            select(Action).where(Action.operation == "claim_next", Action.actor == "processor").order_by(Action.created_at.desc(), Action.id).limit(2)
        ).all()
        streak = len(recent) == 2 and all((a.result or {}).get("profile_class") == "voice" for a in recent)
        older_waiting = bool(voice) and any(o.processing.queued_at < voice[0].processing.queued_at for o in others)
        ranked = others + voice if (streak and older_waiting) else voice + others
    # Lock only the capture being claimed (skipping rows another caller holds), so concurrent
    # callers proceed to different captures instead of blocking or all seeing an empty queue.
    for candidate in ranked:
        chosen = session.scalar(
            select(Capture)
            .join(CaptureProcessing)
            .options(contains_eager(Capture.processing))
            .where(Capture.id == candidate.id)
            .with_for_update(of=Capture, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if chosen is None or not _claimable(chosen, now):
            continue
        action, _ = begin_action(session, "claim_next", {"lease_seconds": body.lease_seconds}, None, actor="processor", client_label=context[1])
        result = take_lease(chosen, body.lease_seconds).model_dump(mode="json")
        result.update(version=chosen.version, profile=profile_of(chosen), profile_class="voice" if is_voice(chosen) else "other")
        finish_action(action, result)
        session.commit()
        return result
    session.rollback()
    return Response(status_code=204)


# --------------------------------------------------------------------------------------
# Proposal accept
# --------------------------------------------------------------------------------------
def _stale(capture: Capture, code: str, message: str, **extra: Any) -> DomainError:
    return DomainError(code, message, 409, {"id": str(capture.id), **capture_state_details(capture), **extra})


@router.post("/captures/{capture_id}/proposal/accept")
def accept_proposal(capture_id: uuid.UUID, body: ProposalAcceptRequest, session: SessionDep, context: ActionContext, settings: SettingsDep):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json", exclude_unset=True)}
    action, replay = begin_action(session, "accept_capture_proposal", payload, context[0], client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    processing = capture.processing
    if capture.version != body.expected_version:
        raise _stale(capture, "version_conflict", "The capture changed since it was read", expected_version=body.expected_version, actual_version=capture.version)
    if processing.generation != body.expected_generation:
        raise _stale(capture, "processing_generation_conflict", "Capture processing generation changed", expected_generation=body.expected_generation)
    if capture.archived_at is not None or processing.state != "awaiting_review":
        raise processing_conflict("There is no reviewable proposal in the capture's current state", processing, capture)
    stored = processing.proposal
    if not is_voice(capture) or not stored or stored.get("kind") != "voice_command":
        raise DomainError("nothing_to_accept", "This capture has no voice proposal to accept", 422)
    operation = stored.get("operation")
    if operation is None:
        raise DomainError("nothing_to_accept", "This proposal does not propose creating anything; save it as a note or task instead", 422)

    overrides = body.overrides
    fields = overrides.model_fields_set if overrides else set()
    merged = dict(operation)
    for name in ("item_type", "title", "content_md", "due_date", "due_time", "due_timezone"):
        if name in fields:
            merged[name] = getattr(overrides, name)
    if merged["item_type"] != "task":
        merged.update(due_date=None, due_time=None, due_timezone=None)
    destination = operation.get("destination")
    version_hint: int | None = None
    if "destination" in fields:
        destination = None if overrides.destination is None else {"kind": overrides.destination.kind, "id": str(overrides.destination.id)}
        version_hint = overrides.destination.version if overrides.destination else None
    try:
        item = ItemCreate(
            item_type=merged["item_type"], title=merged["title"], content_md=merged.get("content_md") or "",
            due_date=merged.get("due_date"), due_time=merged.get("due_time"), due_timezone=merged.get("due_timezone"),
        )
    except ValidationError as exc:
        raise DomainError("invalid_input", "The edited proposal is not valid", 422, {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}) from exc

    _anchor, zone = effective_anchor(capture, effective_corrections(session, capture.id), settings.user_timezone)
    behind = overdue_by_seconds(
        {"due_date": item.due_date, "due_time": item.due_time, "due_timezone": item.due_timezone}, zone, utcnow()
    )
    if behind is not None and not body.confirm_overdue:
        raise DomainError("overdue_confirmation_required", "This deadline has already passed", 422, {"overdue_by_seconds": behind})

    container: dict[str, Any] = {}
    if destination:
        kind, dest_id = destination["kind"], uuid.UUID(str(destination["id"]))
        if kind == "category":
            if session.get(Category, dest_id) is None:
                raise _stale(capture, "destination_changed", "The destination no longer exists")
            item = item.model_copy(update={"category_id": dest_id})
        else:
            target = session.scalar(select(Item).where(Item.id == dest_id).with_for_update(of=Item))
            if target is None or target.archived_at is not None or target.item_type != kind:
                raise _stale(capture, "destination_changed", "The destination was archived, removed, or changed type")
            if version_hint is not None:
                require_version(target, version_hint)
            container = {f"{kind}_id": dest_id, f"{kind}_expected_version": target.version}
    interpretation = CaptureInterpretationRequest(
        expected_version=capture.version,
        expected_generation=processing.generation,
        mode="manual",
        items=[CreateInterpretationItem(item=item, **container)],
    )
    result = apply_interpretation(
        session, capture, action, interpretation, accept_path="accept_endpoint", overdue_confirmed=behind is not None and body.confirm_overdue
    )
    session.commit()
    return result
