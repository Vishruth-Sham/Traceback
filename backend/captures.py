import base64
import binascii
import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from backend.api import ActionContext, authenticate, item_out
from backend.capture_models import Capture, CaptureProcessing, CaptureRevision, ItemSource
from backend.capture_schemas import (
    AppendInterpretationItem,
    CaptureClaimRequest,
    CreateInterpretationItem,
    CaptureCorrectionCreate,
    CaptureCreate,
    CaptureFailRequest,
    CaptureInterpretationRequest,
    CaptureProposalRequest,
    CaptureOut,
    CaptureRetryRequest,
    CaptureRevisionOut,
    CaptureVersionRequest,
    ClaimOut,
    SourceLinkRequest,
    SourceOut,
    SourceUnlinkRequest,
)
from backend.config import Settings, get_settings
from backend.db import get_session
from backend.errors import DomainError, conflict, not_found
from backend.models import Action, Category, Item, ItemRelation
from backend.schemas import ItemOut
from backend.services import (
    _place_in_container,
    append_item,
    begin_action,
    bump,
    create_item,
    finish_action,
    get_item,
    item_snapshot,
    record_revision,
    require_version,
    utcnow,
)


router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_capture(session: Session, capture_id: uuid.UUID, *, lock: bool = False) -> Capture:
    stmt = select(Capture).options(joinedload(Capture.processing)).where(Capture.id == capture_id)
    if lock:
        stmt = stmt.with_for_update(of=Capture)
    capture = session.scalar(stmt)
    if not capture:
        raise not_found("capture", capture_id)
    return capture


def require_capture_version(capture: Capture, expected: int) -> None:
    if capture.version != expected:
        raise conflict(expected, capture.version, capture.id)


def asset_ids_for_capture(session: Session, capture_id: uuid.UUID) -> list[uuid.UUID]:
    try:
        from backend.asset_models import CaptureAsset
    except ImportError:
        return []
    return list(session.scalars(select(CaptureAsset.asset_id).where(CaptureAsset.capture_id == capture_id).order_by(CaptureAsset.asset_id)).all())


def attach_assets(session: Session, capture_id: uuid.UUID, asset_ids: list[uuid.UUID]) -> None:
    if not asset_ids:
        return
    try:
        from backend.assets import attach_capture_assets
    except ImportError as exc:
        raise DomainError("service_unavailable", "Asset persistence is not installed", 503) from exc
    attach_capture_assets(session, capture_id, asset_ids)


def effective_corrections(session: Session, capture_id: uuid.UUID) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    rows = session.scalars(
        select(CaptureRevision)
        .where(CaptureRevision.capture_id == capture_id, CaptureRevision.change_type == "correction")
        .order_by(CaptureRevision.resulting_version)
    ).all()
    for row in rows:
        changes.update({key: value for key, value in row.changes.items() if key != "note"})
    return changes


def effective_note_values(session: Session, capture: Capture) -> dict[str, Any]:
    corrections = effective_corrections(session, capture.id)
    return {
        "note_text": corrections.get("note_text", capture.raw_text),
        "supplied_title": corrections.get("supplied_title", capture.source_metadata.get("supplied_title")),
        "placement_hint": corrections.get("placement_hint", capture.source_metadata.get("placement_hint")),
    }


def capture_out(session: Session, capture: Capture, action_id: uuid.UUID | None = None, include_raw: bool = True) -> dict[str, Any]:
    item_ids = list(session.scalars(select(ItemSource.item_id).where(ItemSource.capture_id == capture.id).order_by(ItemSource.item_id)).all())
    value = {
        "id": capture.id,
        "source_type": capture.source_type,
        "raw_text": capture.raw_text if include_raw else None,
        "original_description": capture.original_description,
        "original_url": capture.original_url,
        "captured_at": capture.captured_at,
        "source_date": capture.source_date,
        "source_timezone": capture.source_timezone,
        "timestamp_origin": capture.timestamp_origin,
        "metadata": capture.source_metadata,
        "corrections": effective_corrections(session, capture.id),
        "asset_ids": asset_ids_for_capture(session, capture.id),
        "resulting_item_ids": item_ids,
        "version": capture.version,
        "created_at": capture.created_at,
        "updated_at": capture.updated_at,
        "archived_at": capture.archived_at,
        "processing": capture.processing,
        "action_id": action_id,
    }
    return value


def json_capture(session: Session, capture: Capture, action_id: uuid.UUID | None = None) -> dict[str, Any]:
    return CaptureOut.model_validate(capture_out(session, capture, action_id)).model_dump(mode="json")


def add_capture_revision(session: Session, capture: Capture, action: Action, change_type: str, changes: dict[str, Any]) -> None:
    capture.updated_at = utcnow()
    session.add(
        CaptureRevision(
            capture_id=capture.id,
            action_id=action.id,
            resulting_version=capture.version,
            change_type=change_type,
            changes=changes,
        )
    )


def processing_conflict(message: str, processing: CaptureProcessing) -> DomainError:
    return DomainError(
        "processing_conflict",
        message,
        409,
        {"state": processing.state, "generation": processing.generation},
    )


def validate_generation(processing: CaptureProcessing, expected: int) -> None:
    if processing.generation != expected:
        raise DomainError(
            "processing_generation_conflict",
            "Capture processing generation changed",
            409,
            {"expected_generation": expected, "actual_generation": processing.generation},
        )


def clear_lease(processing: CaptureProcessing) -> None:
    processing.lease_token = None
    processing.lease_expires_at = None


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        if len(cursor) > 32:
            raise ValueError
        value = int(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode())
        if not 0 <= value <= 10_000_000:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise DomainError("invalid_cursor", "Pagination cursor is invalid", 422) from None


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


@router.post("/captures", response_model=CaptureOut, status_code=201)
def create_capture_endpoint(body: CaptureCreate, session: SessionDep, context: ActionContext):
    payload = body.model_dump(mode="json")
    action, replay = begin_action(session, "create_capture", payload, context[0], client_label=context[1])
    if replay:
        return replay
    capture = Capture(
        source_type=body.source_type,
        raw_text=body.raw_text,
        original_description=body.description,
        original_url=str(body.url) if body.url else None,
        captured_at=body.captured_at,
        source_date=body.source_date,
        source_timezone=body.source_timezone,
        timestamp_origin=body.timestamp_origin,
        source_metadata=body.metadata.model_dump(mode="json", exclude_none=True),
    )
    capture.processing = CaptureProcessing(state="pending", generation=1, attempt_count=0)
    session.add(capture)
    session.flush()
    attach_assets(session, capture.id, body.asset_ids)
    add_capture_revision(session, capture, action, "created", {"source_type": capture.source_type})
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.get("/captures")
def list_captures(
    session: SessionDep,
    settings: SettingsDep,
    archived: bool = False,
    state: Literal["pending", "processing", "awaiting_review", "failed", "resolved"] | None = None,
    source_type: Literal["typed", "audio", "file", "url", "import"] | None = None,
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1),
):
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    stmt = select(Capture).join(CaptureProcessing).options(joinedload(Capture.processing)).where(
        Capture.archived_at.is_not(None) if archived else Capture.archived_at.is_(None)
    )
    if state:
        stmt = stmt.where(CaptureProcessing.state == state)
    if source_type:
        stmt = stmt.where(Capture.source_type == source_type)
    if q:
        stmt = stmt.where(or_(Capture.raw_text.ilike(f"%{q}%"), Capture.original_description.ilike(f"%{q}%")))
    rows = session.scalars(stmt.order_by(Capture.created_at.desc(), Capture.id).offset(offset).limit(limit + 1)).unique().all()
    has_more = len(rows) > limit
    return {
        "items": [capture_out(session, row, include_raw=False) for row in rows[:limit]],
        "next_cursor": encode_cursor(offset + limit) if has_more else None,
    }


@router.get("/captures/{capture_id}", response_model=CaptureOut)
def read_capture(capture_id: uuid.UUID, session: SessionDep):
    return capture_out(session, get_capture(session, capture_id))


@router.post("/captures/{capture_id}/corrections", response_model=CaptureOut)
def correct_capture(capture_id: uuid.UUID, body: CaptureCorrectionCreate, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json", exclude_unset=True)}
    action, replay = begin_action(session, "correct_capture", payload, context[0], client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, body.expected_version)
    changes = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_version"})
    capture.version += 1
    if capture.source_metadata.get("processing_profile") == "note_quick_add" and set(changes) & {
        "note_text", "supplied_title", "placement_hint"
    }:
        if capture.processing.state == "resolved":
            raise processing_conflict("Resolved note captures cannot be edited", capture.processing)
        capture.processing.generation += 1
        capture.processing.state = "pending"
        capture.processing.proposal = None
        capture.processing.proposed_at = None
        capture.processing.error_code = None
        capture.processing.error_message = None
        capture.processing.queued_at = utcnow()
        clear_lease(capture.processing)
    add_capture_revision(session, capture, action, "correction", changes)
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


def lifecycle(capture_id: uuid.UUID, body: CaptureVersionRequest, archived: bool, session: Session, context: tuple[str | None, str]):
    operation = "archive_capture" if archived else "restore_capture"
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, operation, payload, context[0], client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, body.expected_version)
    if (capture.archived_at is not None) == archived:
        raise DomainError("invalid_transition", "Capture is already in the requested archive state", 409)
    capture.archived_at = utcnow() if archived else None
    capture.version += 1
    if archived and capture.processing.state == "processing":
        capture.processing.generation += 1
        capture.processing.state = "pending"
        clear_lease(capture.processing)
    add_capture_revision(session, capture, action, operation, {})
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/captures/{capture_id}/archive", response_model=CaptureOut)
def archive_capture(capture_id: uuid.UUID, body: CaptureVersionRequest, session: SessionDep, context: ActionContext):
    return lifecycle(capture_id, body, True, session, context)


@router.post("/captures/{capture_id}/restore", response_model=CaptureOut)
def restore_capture(capture_id: uuid.UUID, body: CaptureVersionRequest, session: SessionDep, context: ActionContext):
    return lifecycle(capture_id, body, False, session, context)


@router.delete("/captures/{capture_id}", status_code=204)
def delete_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    context: ActionContext,
    expected_version: int = Query(ge=1),
    confirm: bool = False,
):
    if not confirm:
        raise DomainError("confirmation_required", "Permanent deletion requires confirm=true", 422)
    payload = {"capture_id": str(capture_id), "expected_version": expected_version, "confirm": True}
    action, replay = begin_action(session, "delete_capture_permanently", payload, context[0], client_label=context[1])
    if replay:
        return Response(status_code=204)
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, expected_version)
    if capture.archived_at is None:
        raise DomainError("invalid_transition", "Only archived captures can be permanently deleted", 409)
    links = session.scalars(select(ItemSource.id).where(ItemSource.capture_id == capture.id)).all()
    if links:
        raise DomainError("linked_source_conflict", "Unlink source items before deleting this capture", 409, {"source_link_ids": [str(v) for v in links]})
    action_ids = session.scalars(select(CaptureRevision.action_id).where(CaptureRevision.capture_id == capture.id)).all()
    for prior_action in session.scalars(select(Action).where(Action.id.in_(action_ids))).all() if action_ids else []:
        prior_action.result = {"purged_capture_id": str(capture.id), "result_purged": True}
    session.delete(capture)
    action.result = {"deleted_capture_id": str(capture_id)}
    session.commit()
    return Response(status_code=204)


@router.post("/captures/{capture_id}/claim", response_model=ClaimOut)
def claim_capture(capture_id: uuid.UUID, body: CaptureClaimRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "claim_capture", payload, context[0], actor="processor", client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    processing = capture.processing
    validate_generation(processing, body.expected_generation)
    if capture.archived_at is not None or processing.state == "resolved":
        raise processing_conflict("Capture is not available for processing", processing)
    now = utcnow()
    if processing.state == "processing" and processing.lease_expires_at and processing.lease_expires_at > now:
        raise processing_conflict("Capture already has an active lease", processing)
    if processing.state not in ("pending", "processing"):
        raise processing_conflict("Retry a failed capture before claiming it", processing)
    processing.state = "processing"
    processing.lease_token = uuid.uuid4()
    processing.lease_expires_at = now + timedelta(seconds=body.lease_seconds)
    processing.started_at = now
    processing.finished_at = None
    processing.attempt_count += 1
    result = ClaimOut(
        capture_id=capture.id,
        generation=processing.generation,
        lease_token=processing.lease_token,
        lease_expires_at=processing.lease_expires_at,
    ).model_dump(mode="json")
    finish_action(action, result)
    session.commit()
    return result


@router.post("/captures/{capture_id}/fail", response_model=CaptureOut)
def fail_capture(capture_id: uuid.UUID, body: CaptureFailRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "fail_capture", payload, context[0], actor="processor", client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    processing = capture.processing
    validate_generation(processing, body.expected_generation)
    if processing.state != "processing" or processing.lease_token != body.lease_token:
        raise processing_conflict("Processor lease is stale", processing)
    if not processing.lease_expires_at or processing.lease_expires_at <= utcnow():
        raise processing_conflict("Processor lease expired", processing)
    processing.state = "failed"
    processing.error_code = body.error_code
    processing.error_message = body.error_message
    processing.transcript = body.transcript
    processing.finished_at = utcnow()
    clear_lease(processing)
    capture.version += 1
    add_capture_revision(
        session,
        capture,
        action,
        "processing_failed",
        {"generation": processing.generation, "error_code": body.error_code},
    )
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/captures/{capture_id}/retry", response_model=CaptureOut)
def retry_capture(capture_id: uuid.UUID, body: CaptureRetryRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "retry_capture", payload, context[0], client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, body.expected_version)
    validate_generation(capture.processing, body.expected_generation)
    if capture.archived_at is not None or capture.processing.state != "failed":
        raise processing_conflict("Only active failed captures can be retried", capture.processing)
    capture.version += 1
    capture.processing.generation += 1
    capture.processing.state = "pending"
    capture.processing.error_code = None
    capture.processing.error_message = None
    capture.processing.queued_at = utcnow()
    capture.processing.started_at = None
    capture.processing.finished_at = None
    clear_lease(capture.processing)
    add_capture_revision(session, capture, action, "retry", {"generation": capture.processing.generation})
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/captures/{capture_id}/proposal", response_model=CaptureOut)
def submit_capture_proposal(
    capture_id: uuid.UUID, body: CaptureProposalRequest, session: SessionDep, context: ActionContext
):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "submit_capture_proposal", payload, context[0], actor="processor", client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, body.expected_version)
    processing = capture.processing
    validate_generation(processing, body.expected_generation)
    if capture.source_metadata.get("processing_profile") != "note_quick_add":
        raise DomainError("invalid_proposal", "Only note quick-add captures accept proposals", 422)
    if processing.state != "processing" or processing.lease_token != body.lease_token:
        raise processing_conflict("Processor lease is stale", processing)
    if not processing.lease_expires_at or processing.lease_expires_at <= utcnow():
        raise processing_conflict("Processor lease expired", processing)
    proposal = body.proposal.model_dump(mode="json")
    destination_id = body.proposal.destination_id
    if body.proposal.destination_kind == "category":
        if session.get(Category, destination_id) is None:
            raise DomainError("invalid_proposal", "Proposed category is not active", 422)
    elif body.proposal.destination_kind in ("project", "folder"):
        destination = session.scalar(select(Item).where(Item.id == destination_id).with_for_update(of=Item))
        if destination is None or destination.archived_at is not None or destination.item_type != body.proposal.destination_kind:
            raise DomainError("invalid_proposal", "Proposed destination is unknown, archived, or the wrong type", 422)
        require_version(destination, body.proposal.destination_version)
    processing.proposal = {**proposal, "generation": processing.generation}
    processing.proposed_at = utcnow()
    processing.state = "awaiting_review"
    processing.error_code = None
    processing.error_message = None
    processing.finished_at = utcnow()
    clear_lease(processing)
    capture.version += 1
    add_capture_revision(session, capture, action, "proposal", {"generation": processing.generation, "proposal": processing.proposal})
    session.flush()
    result = json_capture(session, capture, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/captures/{capture_id}/interpretations")
def interpret_capture(capture_id: uuid.UUID, body: CaptureInterpretationRequest, session: SessionDep, context: ActionContext):
    payload = {"capture_id": str(capture_id), **body.model_dump(mode="json")}
    actor = "processor" if body.mode == "processor" else "user"
    action, replay = begin_action(session, "apply_capture_interpretation", payload, context[0], actor=actor, client_label=context[1])
    if replay:
        return replay
    capture = get_capture(session, capture_id, lock=True)
    require_capture_version(capture, body.expected_version)
    processing = capture.processing
    if capture.source_metadata.get("processing_profile") == "task_quick_add":
        if len(body.items) != 1 or not isinstance(body.items[0], CreateInterpretationItem) or body.items[0].item.item_type != "task":
            raise DomainError(
                "invalid_interpretation",
                "Task quick-add captures must resolve to exactly one newly created task",
                422,
            )
    if capture.source_metadata.get("processing_profile") == "note_quick_add":
        if len(body.items) != 1 or not isinstance(body.items[0], CreateInterpretationItem) or body.items[0].item.item_type != "note":
            raise DomainError("invalid_interpretation", "Note quick-add captures must resolve to exactly one newly created note", 422)
        effective = effective_note_values(session, capture)
        if body.items[0].item.content_md != effective["note_text"]:
            raise DomainError("invalid_interpretation", "Note content must match the saved capture or its latest correction", 422)
    validate_generation(processing, body.expected_generation)
    if capture.archived_at is not None or processing.state == "resolved":
        raise processing_conflict("Capture cannot be interpreted in its current state", processing)
    if body.mode == "processor":
        if processing.state != "processing" or processing.lease_token != body.lease_token:
            raise processing_conflict("Processor lease is stale", processing)
        if not processing.lease_expires_at or processing.lease_expires_at <= utcnow():
            raise processing_conflict("Processor lease expired", processing)
    # Acquire every existing-item lock (append targets and create-operation
    # containers alike) in one stable UUID order before applying the batch.
    # This keeps multi-item interpretations atomic without deadlocks.
    create_operations = [operation for operation in body.items if isinstance(operation, CreateInterpretationItem)]
    append_operations = [operation for operation in body.items if isinstance(operation, AppendInterpretationItem)]
    append_ids = {operation.item_id for operation in append_operations}
    container_ids = {operation.project_id or operation.folder_id for operation in create_operations if operation.project_id or operation.folder_id}
    lock_ids = sorted(append_ids | container_ids, key=str)
    locked_by_id: dict[uuid.UUID, Item] = {}
    if lock_ids:
        locked = session.scalars(
            select(Item).options(joinedload(Item.task)).where(Item.id.in_(lock_ids)).order_by(Item.id).with_for_update(of=Item)
        ).unique().all()
        locked_by_id = {item.id: item for item in locked}
    for operation in append_operations:
        item = locked_by_id.get(operation.item_id)
        if item is None:
            raise not_found("item", operation.item_id)
        require_version(item, operation.expected_version)
        if session.scalar(select(ItemSource.id).where(ItemSource.item_id == item.id, ItemSource.capture_id == capture.id)):
            raise DomainError("source_exists", "Existing item is already linked to this capture", 409)
    for operation in create_operations:
        container_id = operation.project_id or operation.folder_id
        if container_id is None:
            continue
        container = locked_by_id.get(container_id)
        if container is None:
            raise not_found("project" if operation.project_id else "folder", container_id)
        expected = operation.project_expected_version if operation.project_id else operation.folder_expected_version
        require_version(container, expected)
        expected_type = "project" if operation.project_id else "folder"
        if container.item_type != expected_type:
            raise DomainError("invalid_input", f"{expected_type}_id must identify a {expected_type}", 422)
    results: list[dict[str, Any]] = []
    for operation in body.items:
        if isinstance(operation, AppendInterpretationItem):
            item = append_item(session, operation.item_id, operation.expected_version, operation.content_md, action)
        else:
            item = create_item(session, operation.item.model_dump(), action, record=False)
            session.flush()
            container_id = operation.project_id or operation.folder_id
            if container_id is not None:
                container = locked_by_id[container_id]
                before_container = item_snapshot(session, container)
                _place_in_container(item, container)
                session.add(ItemRelation(from_item_id=item.id, relation="part_of", to_item_id=container.id))
                session.flush()
                bump(container)
                record_revision(session, action, container, before_container)
            record_revision(session, action, item, None)
        session.flush()
        session.add(ItemSource(item_id=item.id, capture_id=capture.id, action_id=action.id, link_kind="interpreted"))
        session.flush()
        results.append(ItemOut.model_validate(item_out(session, item, action.id)).model_dump(mode="json"))
    processing.state = "resolved"
    processing.proposal = None
    processing.transcript = body.transcript if body.transcript is not None else processing.transcript
    processing.error_code = None
    processing.error_message = None
    processing.finished_at = utcnow()
    clear_lease(processing)
    if body.mode == "manual":
        processing.generation += 1
    capture.version += 1
    add_capture_revision(
        session,
        capture,
        action,
        "interpreted",
        {"mode": body.mode, "item_ids": [str(result["id"]) for result in results], "generation": processing.generation},
    )
    session.flush()
    result = {
        "capture": json_capture(session, capture, action.id),
        "items": results,
        "action_id": str(action.id),
    }
    finish_action(action, result)
    session.commit()
    return result


@router.get("/captures/{capture_id}/history")
def capture_history(capture_id: uuid.UUID, session: SessionDep, settings: SettingsDep, cursor: str | None = None, limit: int = Query(default=50, ge=1)):
    get_capture(session, capture_id)
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    rows = session.scalars(
        select(CaptureRevision).where(CaptureRevision.capture_id == capture_id)
        .order_by(CaptureRevision.created_at.desc(), CaptureRevision.id.desc()).offset(offset).limit(limit + 1)
    ).all()
    return {
        "items": [CaptureRevisionOut.model_validate(row).model_dump(mode="json") for row in rows[:limit]],
        "next_cursor": encode_cursor(offset + limit) if len(rows) > limit else None,
    }


@router.get("/items/{item_id}/sources", response_model=list[SourceOut])
def item_sources(item_id: uuid.UUID, session: SessionDep):
    get_item(session, item_id)
    return session.scalars(select(ItemSource).where(ItemSource.item_id == item_id).order_by(ItemSource.created_at, ItemSource.id)).all()


@router.post("/items/{item_id}/sources", response_model=SourceOut, status_code=201)
def link_source(item_id: uuid.UUID, body: SourceLinkRequest, session: SessionDep, context: ActionContext):
    payload = {"item_id": str(item_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "link_item_source", payload, context[0], client_label=context[1])
    if replay:
        return replay
    item = get_item(session, item_id, lock=True)
    capture = get_capture(session, body.capture_id, lock=True)
    require_version(item, body.item_expected_version)
    require_capture_version(capture, body.capture_expected_version)
    if session.scalar(select(ItemSource.id).where(ItemSource.item_id == item.id, ItemSource.capture_id == capture.id)):
        raise DomainError("source_exists", "Item is already linked to this capture", 409)
    before = item_snapshot(session, item)
    source = ItemSource(item_id=item.id, capture_id=capture.id, action_id=action.id, link_kind="manual")
    session.add(source)
    bump(item)
    capture.version += 1
    add_capture_revision(session, capture, action, "source_linked", {"item_id": str(item.id)})
    record_revision(session, action, item, before)
    session.flush()
    result = SourceOut.model_validate(source).model_dump(mode="json")
    finish_action(action, result)
    session.commit()
    return result


@router.delete("/items/{item_id}/sources/{source_id}")
def unlink_source(item_id: uuid.UUID, source_id: uuid.UUID, body: SourceUnlinkRequest, session: SessionDep, context: ActionContext):
    payload = {"item_id": str(item_id), "source_id": str(source_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "unlink_item_source", payload, context[0], client_label=context[1])
    if replay:
        return replay
    source = session.scalar(select(ItemSource).where(ItemSource.id == source_id, ItemSource.item_id == item_id).with_for_update())
    if not source:
        raise not_found("item source", source_id)
    item = get_item(session, item_id, lock=True)
    capture = get_capture(session, source.capture_id, lock=True)
    require_version(item, body.item_expected_version)
    require_capture_version(capture, body.capture_expected_version)
    before = item_snapshot(session, item)
    session.delete(source)
    session.flush()
    bump(item)
    capture.version += 1
    add_capture_revision(session, capture, action, "source_unlinked", {"item_id": str(item.id), "source_id": str(source.id)})
    record_revision(session, action, item, before)
    result = {"deleted_source_id": str(source_id), "item_id": str(item_id), "capture_id": str(capture.id), "action_id": str(action.id)}
    finish_action(action, result)
    session.commit()
    return result
