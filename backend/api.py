import base64
import binascii
import hmac
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.orm import Session, aliased, joinedload
from sqlalchemy.exc import SQLAlchemyError

from backend.config import Settings, get_settings
from backend.db import get_session
from backend.errors import DomainError, not_found
from backend.models import Action, Category, Item, ItemRelation, ItemRevision, TaskDetail
from backend.schemas import (
    ActionOut,
    AppendRequest,
    CategoryOut,
    ItemCreateRequest,
    ItemOut,
    ItemPatch,
    MoveRequest,
    RelationCreate,
    RelationDelete,
    RelationOut,
    RelationMutationOut,
    RevisionOut,
    UndoRequest,
    VersionRequest,
)
from backend.services import (
    _place_in_container,
    append_item,
    begin_action,
    bump,
    create_item,
    create_relation,
    delete_relation,
    finish_action,
    get_item,
    item_snapshot,
    move_item,
    permanently_delete,
    record_revision,
    require_version,
    set_archived,
    transition_task,
    undo_action,
    update_item,
)


router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def authenticate(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(credential, settings.api_token):
        raise DomainError("unauthorized", "A valid local bearer token is required", 401)


Auth = Annotated[None, Depends(authenticate)]


def action_context(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)] = None,
    client_label: Annotated[str, Header(alias="X-Traceback-Client", min_length=1, max_length=100)] = "rest",
) -> tuple[str | None, str]:
    return idempotency_key, client_label


ActionContext = Annotated[tuple[str | None, str], Depends(action_context)]


def relation_out(row: ItemRelation) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_item_id": row.from_item_id,
        "relation": row.relation,
        "to_item_id": row.to_item_id,
        "created_at": row.created_at,
    }


def item_out(session: Session, item: Item, action_id: uuid.UUID | None = None, include_content: bool = True) -> dict[str, Any]:
    from backend.capture_models import ItemSource
    from backend.asset_models import ItemAsset
    relations = session.scalars(
        select(ItemRelation)
        .where(or_(ItemRelation.from_item_id == item.id, ItemRelation.to_item_id == item.id))
        .order_by(ItemRelation.created_at, ItemRelation.id)
    ).all()
    task = item.task
    overdue = None
    if task and task.status == "open" and task.due_date:
        if task.due_time and task.due_timezone:
            deadline = datetime.combine(task.due_date, task.due_time, tzinfo=ZoneInfo(task.due_timezone))
            overdue = datetime.now(UTC) > deadline.astimezone(UTC)
        else:
            overdue = datetime.now(ZoneInfo(get_settings().user_timezone)).date() > task.due_date
    return {
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "content_md": item.content_md if include_content else "",
        "category_id": item.category_id,
        "placement_state": item.placement_state,
        "attributes": item.attributes,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "archived_at": item.archived_at,
        "inbox_entered_at": item.inbox_entered_at,
        "last_user_action_at": item.last_user_action_at,
        "status": task.status if task else None,
        "due_date": task.due_date if task else None,
        "due_time": task.due_time if task else None,
        "due_timezone": task.due_timezone if task else None,
        "completed_at": task.completed_at if task else None,
        "overdue": overdue,
        "relations": [relation_out(row) for row in relations],
        "action_id": action_id,
        "source_ids": list(session.scalars(select(ItemSource.capture_id).where(ItemSource.item_id == item.id))),
        "asset_ids": list(session.scalars(select(ItemAsset.asset_id).where(ItemAsset.item_id == item.id))),
    }


def json_item(session: Session, item: Item, action_id: uuid.UUID | None = None) -> dict[str, Any]:
    return ItemOut.model_validate(item_out(session, item, action_id)).model_dump(mode="json")


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        if len(cursor) > 32:
            raise ValueError
        value = int(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode())
        if value < 0 or value > 10_000_000:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise DomainError("invalid_cursor", "Pagination cursor is invalid", 422) from None


def paginated(rows: list[Any], offset: int, limit: int, mapper) -> dict[str, Any]:
    has_more = len(rows) > limit
    values = rows[:limit]
    return {"items": [mapper(row) for row in values], "next_cursor": encode_cursor(offset + limit) if has_more else None}


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", dependencies=[Depends(authenticate)])
def ready(session: SessionDep) -> dict[str, str]:
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    expected_revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    try:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError as exc:
        raise DomainError("schema_not_ready", "PostgreSQL migrations have not been applied", 503) from exc
    if revision != expected_revision:
        raise DomainError(
            "schema_not_ready",
            "PostgreSQL migrations are not current",
            503,
            {"expected_revision": expected_revision, "actual_revision": revision},
        )
    return {"status": "ready"}


@router.get("/categories", response_model=list[CategoryOut], dependencies=[Depends(authenticate)])
def categories(session: SessionDep):
    return session.scalars(select(Category).order_by(Category.sort_order)).all()


@router.get("/items", dependencies=[Depends(authenticate)])
def list_items(
    session: SessionDep,
    settings: SettingsDep,
    item_type: Literal["note", "task", "project", "folder"] | None = None,
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    top_level: bool = False,
    inbox: bool | None = None,
    archived: bool = False,
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1),
):
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    stmt = select(Item).options(joinedload(Item.task)).where(Item.archived_at.is_not(None) if archived else Item.archived_at.is_(None))
    if item_type:
        stmt = stmt.where(Item.item_type == item_type)
    if category_id:
        stmt = stmt.where(Item.category_id == category_id)
    if inbox is not None:
        stmt = stmt.where(Item.placement_state == ("inbox" if inbox else "classified"))
    if project_id:
        stmt = stmt.join(ItemRelation, and_(ItemRelation.from_item_id == Item.id, ItemRelation.relation == "part_of")).where(ItemRelation.to_item_id == project_id)
    if parent_id:
        stmt = stmt.join(ItemRelation, and_(ItemRelation.from_item_id == Item.id, ItemRelation.relation == "part_of")).where(ItemRelation.to_item_id == parent_id)
    if top_level:
        active_container = aliased(Item)
        contained = (
            select(ItemRelation.from_item_id)
            .join(active_container, active_container.id == ItemRelation.to_item_id)
            .where(ItemRelation.relation == "part_of", active_container.archived_at.is_(None))
        )
        stmt = stmt.where(Item.id.not_in(contained))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Item.title.ilike(pattern), Item.content_md.ilike(pattern)))
    rows = session.scalars(stmt.order_by(Item.updated_at.desc(), Item.id).offset(offset).limit(limit + 1)).unique().all()
    return paginated(rows, offset, limit, lambda row: item_out(session, row, include_content=False))


@router.get("/inbox", dependencies=[Depends(authenticate)])
def inbox(session: SessionDep, settings: SettingsDep, cursor: str | None = None, limit: int = Query(default=50, ge=1)):
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    rows = session.scalars(
        select(Item).options(joinedload(Item.task))
        # Tasks are never shown as unclassified/awaiting-filing: Tasks is
        # its own flat cross-category view regardless of category_id, so an
        # uncategorized task sitting at placement_state="inbox" internally
        # is not something Inbox should surface for manual classification.
        .where(Item.placement_state == "inbox", Item.item_type != "task", Item.archived_at.is_(None))
        .order_by(Item.inbox_entered_at.desc(), Item.id).offset(offset).limit(limit + 1)
    ).unique().all()
    result = paginated(rows, offset, limit, lambda row: item_out(session, row, include_content=False))
    # Until a capture resolves, Inbox exposes the durable processing record.
    # Resolved captures disappear here because their resulting Inbox items are
    # already listed above, preventing duplicate cards for one capture.
    from backend.capture_models import Capture, CaptureProcessing
    from backend.captures import capture_out
    capture_rows = session.scalars(
        select(Capture).join(CaptureProcessing).options(joinedload(Capture.processing))
        .where(Capture.archived_at.is_(None), CaptureProcessing.state != "resolved")
        .order_by(Capture.created_at.desc(), Capture.id).limit(limit + 1)
    ).unique().all()
    result["captures"] = [capture_out(session, row) for row in capture_rows[:limit]]
    result["captures_truncated"] = len(capture_rows) > limit
    return result


@router.get("/items/{item_id}", response_model=ItemOut, dependencies=[Depends(authenticate)])
def read_item(item_id: uuid.UUID, session: SessionDep):
    return item_out(session, get_item(session, item_id))


@router.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(authenticate)])
def post_item(body: ItemCreateRequest, session: SessionDep, context: ActionContext):
    payload = body.model_dump(mode="json")
    action, replay = begin_action(session, "create_item", payload, context[0], client_label=context[1])
    if replay:
        return replay
    container_id = body.project_id or body.folder_id
    container = None
    if container_id is not None:
        container = get_item(session, container_id, lock=True)
        expected = body.project_expected_version if body.project_id else body.folder_expected_version
        require_version(container, expected)
        expected_type = "project" if body.project_id else "folder"
        if container.item_type != expected_type:
            raise DomainError("invalid_input", f"{expected_type}_id must identify a {expected_type}", 422)
    item_data = body.model_dump(exclude={"project_id", "project_expected_version", "folder_id", "folder_expected_version"})
    item = create_item(session, item_data, action, record=False)
    if container is not None:
        before_container = item_snapshot(session, container)
        _place_in_container(item, container)
        session.add(ItemRelation(from_item_id=item.id, relation="part_of", to_item_id=container.id))
        session.flush()
        bump(container)
        record_revision(session, action, container, before_container)
    record_revision(session, action, item, None)
    session.flush()
    result = json_item(session, item, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.patch("/items/{item_id}", response_model=ItemOut, dependencies=[Depends(authenticate)])
def patch_item(item_id: uuid.UUID, body: ItemPatch, session: SessionDep, context: ActionContext):
    payload = {"item_id": str(item_id), **body.model_dump(mode="json", exclude_unset=True)}
    action, replay = begin_action(session, "update_item", payload, context[0], client_label=context[1])
    if replay:
        return replay
    data = body.model_dump()
    item = update_item(session, item_id, data, body.model_fields_set, action)
    session.flush()
    result = json_item(session, item, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/items/{item_id}/append", response_model=ItemOut, dependencies=[Depends(authenticate)])
def append(item_id: uuid.UUID, body: AppendRequest, session: SessionDep, context: ActionContext):
    payload = {"item_id": str(item_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "append_item", payload, context[0], client_label=context[1])
    if replay:
        return replay
    item = append_item(session, item_id, body.expected_version, body.content_md, action)
    session.flush()
    result = json_item(session, item, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/items/{item_id}/move", response_model=ItemOut, dependencies=[Depends(authenticate)])
def move(item_id: uuid.UUID, body: MoveRequest, session: SessionDep, context: ActionContext):
    payload = {"item_id": str(item_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "move_item", payload, context[0], client_label=context[1])
    if replay:
        return replay
    item = move_item(session, item_id, body.model_dump(), action)
    session.flush()
    result = json_item(session, item, action.id)
    finish_action(action, result)
    session.commit()
    return result


def versioned_transition(operation: str, item_id: uuid.UUID, body: VersionRequest, session: Session, context: tuple[str | None, str], mutation):
    payload = {"item_id": str(item_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, operation, payload, context[0], client_label=context[1])
    if replay:
        return replay
    item = mutation(session, item_id, body.expected_version, action)
    session.flush()
    result = json_item(session, item, action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.post("/items/{item_id}/archive", response_model=ItemOut, dependencies=[Depends(authenticate)])
def archive(item_id: uuid.UUID, body: VersionRequest, session: SessionDep, context: ActionContext):
    return versioned_transition("archive_item", item_id, body, session, context, lambda s, i, v, a: set_archived(s, i, v, True, a))


@router.post("/items/{item_id}/restore", response_model=ItemOut, dependencies=[Depends(authenticate)])
def restore(item_id: uuid.UUID, body: VersionRequest, session: SessionDep, context: ActionContext):
    return versioned_transition("restore_item", item_id, body, session, context, lambda s, i, v, a: set_archived(s, i, v, False, a))


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(authenticate)])
def delete_item(
    item_id: uuid.UUID,
    session: SessionDep,
    context: ActionContext,
    expected_version: int = Query(ge=1),
    confirm: bool = False,
):
    if not confirm:
        raise DomainError("confirmation_required", "Permanent deletion requires confirm=true", 422)
    payload = {"item_id": str(item_id), "expected_version": expected_version, "confirm": True}
    action, replay = begin_action(session, "delete_item_permanently", payload, context[0], client_label=context[1])
    if replay:
        return Response(status_code=204)
    permanently_delete(session, item_id, expected_version, action)
    session.commit()
    return Response(status_code=204)


@router.get("/tasks", dependencies=[Depends(authenticate)])
def tasks(
    session: SessionDep,
    settings: SettingsDep,
    task_status: Literal["open", "completed"] = Query(default="open", alias="status"),
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1),
):
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    stmt = select(Item).join(TaskDetail).options(joinedload(Item.task)).where(Item.archived_at.is_(None), TaskDetail.status == task_status)
    if category_id:
        stmt = stmt.where(Item.category_id == category_id)
    if project_id:
        stmt = stmt.join(ItemRelation, and_(ItemRelation.from_item_id == Item.id, ItemRelation.relation == "part_of")).where(ItemRelation.to_item_id == project_id)
    if task_status == "open":
        stmt = stmt.order_by(TaskDetail.due_date.asc().nulls_last(), TaskDetail.due_time.asc().nulls_last(), Item.created_at, Item.id)
    else:
        stmt = stmt.order_by(TaskDetail.completed_at.desc(), Item.id)
    rows = session.scalars(stmt.offset(offset).limit(limit + 1)).unique().all()
    return paginated(rows, offset, limit, lambda row: item_out(session, row, include_content=False))


@router.post("/tasks/{item_id}/complete", response_model=ItemOut, dependencies=[Depends(authenticate)])
def complete(item_id: uuid.UUID, body: VersionRequest, session: SessionDep, context: ActionContext):
    return versioned_transition("complete_task", item_id, body, session, context, lambda s, i, v, a: transition_task(s, i, v, True, a))


@router.post("/tasks/{item_id}/reopen", response_model=ItemOut, dependencies=[Depends(authenticate)])
def reopen(item_id: uuid.UUID, body: VersionRequest, session: SessionDep, context: ActionContext):
    return versioned_transition("reopen_task", item_id, body, session, context, lambda s, i, v, a: transition_task(s, i, v, False, a))


@router.post("/relations", response_model=RelationMutationOut, status_code=201, dependencies=[Depends(authenticate)])
def link(body: RelationCreate, session: SessionDep, context: ActionContext):
    payload = body.model_dump(mode="json")
    action, replay = begin_action(session, "create_relation", payload, context[0], client_label=context[1])
    if replay:
        return replay
    relation = create_relation(session, body.model_dump(), action)
    session.flush()
    result = RelationOut.model_validate(relation).model_dump(mode="json")
    result["action_id"] = str(action.id)
    finish_action(action, result)
    session.commit()
    return result


@router.delete("/relations/{relation_id}", dependencies=[Depends(authenticate)])
def unlink(relation_id: uuid.UUID, body: RelationDelete, session: SessionDep, context: ActionContext):
    payload = {"relation_id": str(relation_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "delete_relation", payload, context[0], client_label=context[1])
    if replay:
        return replay
    source, target = delete_relation(session, relation_id, body.from_expected_version, body.to_expected_version, action)
    result = {"deleted_relation_id": str(relation_id), "from_item_id": str(source), "to_item_id": str(target), "action_id": str(action.id)}
    finish_action(action, result)
    session.commit()
    return result


@router.get("/items/{item_id}/history", dependencies=[Depends(authenticate)])
def history(item_id: uuid.UUID, session: SessionDep, settings: SettingsDep, cursor: str | None = None, limit: int = Query(default=50, ge=1)):
    if not session.get(Item, item_id):
        raise not_found("item", item_id)
    limit = min(limit, settings.max_page_size)
    offset = decode_cursor(cursor)
    rows = session.scalars(
        select(ItemRevision).where(ItemRevision.item_id == item_id).order_by(ItemRevision.created_at.desc(), ItemRevision.id.desc()).offset(offset).limit(limit + 1)
    ).all()
    return paginated(rows, offset, limit, lambda row: RevisionOut.model_validate(row, from_attributes=True).model_dump(mode="json"))


@router.post("/actions/{action_id}/undo", dependencies=[Depends(authenticate)])
def undo(action_id: uuid.UUID, body: UndoRequest, session: SessionDep, context: ActionContext):
    payload = {"action_id": str(action_id), **body.model_dump(mode="json")}
    action, replay = begin_action(session, "undo_action", payload, context[0], client_label=context[1])
    if replay:
        return replay
    items = undo_action(session, action_id, body.expected_versions, action)
    session.flush()
    result = {"action_id": str(action.id), "items": [json_item(session, item, action.id) for item in items]}
    finish_action(action, result)
    session.commit()
    return result
