import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session, joinedload

from backend.errors import DomainError, conflict, not_found
from backend.models import CATEGORY_IDS, Action, Category, Item, ItemRelation, ItemRevision, TaskDetail


def utcnow() -> datetime:
    return datetime.now(UTC)


def request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def begin_action(
    session: Session,
    operation: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
    actor: str = "user",
    client_label: str = "rest",
) -> tuple[Action, dict[str, Any] | None]:
    digest = request_hash(payload)
    if idempotency_key:
        lock_name = f"{actor}:{client_label}:{operation}:{idempotency_key}"
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"), {"lock_name": lock_name})
        existing = session.scalar(
            select(Action).where(
                Action.actor == actor,
                Action.client_label == client_label,
                Action.operation == operation,
                Action.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.body_hash != digest:
                raise DomainError("idempotency_conflict", "Idempotency key was already used with a different request", 409)
            if existing.result and existing.result.get("result_purged"):
                raise DomainError("idempotency_result_unavailable", "The prior result was purged with a permanently deleted item", 409)
            if existing.result is None:
                raise DomainError("request_in_progress", "The idempotent request has not completed", 409)
            return existing, existing.result
    action = Action(
        actor=actor,
        client_label=client_label,
        operation=operation,
        idempotency_key=idempotency_key,
        body_hash=digest,
    )
    session.add(action)
    session.flush()
    return action, None


def finish_action(action: Action, result: dict[str, Any]) -> None:
    action.result = result


def get_item(session: Session, item_id: uuid.UUID, *, lock: bool = False) -> Item:
    stmt = select(Item).options(joinedload(Item.task)).where(Item.id == item_id)
    if lock:
        stmt = stmt.with_for_update(of=Item)
    item = session.scalar(stmt)
    if not item:
        raise not_found("item", item_id)
    return item


def require_version(item: Item, expected: int) -> None:
    if item.version != expected:
        raise conflict(expected, item.version, item.id)


def require_category(session: Session, category_id: uuid.UUID) -> Category:
    category = session.get(Category, category_id)
    if not category:
        raise not_found("category", category_id)
    return category


def relation_dict(relation: ItemRelation) -> dict[str, Any]:
    return {
        "id": str(relation.id),
        "from_item_id": str(relation.from_item_id),
        "relation": relation.relation,
        "to_item_id": str(relation.to_item_id),
        "created_at": relation.created_at.isoformat() if relation.created_at else None,
    }


def item_snapshot(session: Session, item: Item) -> dict[str, Any]:
    from backend.capture_models import ItemSource
    from backend.asset_models import ItemAsset
    task = item.task
    relations = session.scalars(
        select(ItemRelation)
        .where(or_(ItemRelation.from_item_id == item.id, ItemRelation.to_item_id == item.id))
        .order_by(ItemRelation.id)
    ).all()
    return {
        "id": str(item.id),
        "item_type": item.item_type,
        "title": item.title,
        "content_md": item.content_md,
        "category_id": str(item.category_id) if item.category_id else None,
        "placement_state": item.placement_state,
        "attributes": item.attributes,
        "version": item.version,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "inbox_entered_at": item.inbox_entered_at.isoformat() if item.inbox_entered_at else None,
        "last_user_action_at": item.last_user_action_at.isoformat(),
        "task": None if task is None else {
            "status": task.status,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "due_time": task.due_time.isoformat() if task.due_time else None,
            "due_timezone": task.due_timezone,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        },
        "relations": [relation_dict(r) for r in relations],
        "source_ids": [str(value) for value in session.scalars(select(ItemSource.capture_id).where(ItemSource.item_id == item.id).order_by(ItemSource.capture_id))],
        "asset_ids": [str(value) for value in session.scalars(select(ItemAsset.asset_id).where(ItemAsset.item_id == item.id).order_by(ItemAsset.asset_id))],
    }


def record_revision(session: Session, action: Action, item: Item, before: dict[str, Any] | None) -> None:
    session.flush()
    session.add(
        ItemRevision(
            action_id=action.id,
            item_id=item.id,
            resulting_version=item.version,
            before_snapshot=before,
            after_snapshot=item_snapshot(session, item),
        )
    )


def bump(item: Item) -> None:
    now = utcnow()
    item.version += 1
    item.updated_at = now
    item.last_user_action_at = now


def create_item(session: Session, data: dict[str, Any], action: Action, *, record: bool = True) -> Item:
    category_id = data.get("category_id")
    if category_id:
        require_category(session, category_id)
    item = Item(
        item_type=data["item_type"],
        title=data["title"],
        content_md=data.get("content_md", ""),
        category_id=category_id,
        placement_state="classified" if category_id else "inbox",
        inbox_entered_at=None if category_id else utcnow(),
        attributes=data.get("attributes", {}),
    )
    session.add(item)
    session.flush()
    if item.item_type == "task":
        item.task = TaskDetail(
            status="open",
            due_date=data.get("due_date"),
            due_time=data.get("due_time"),
            due_timezone=data.get("due_timezone"),
        )
        session.flush()
    if record:
        record_revision(session, action, item, None)
    return item


def update_item(session: Session, item_id: uuid.UUID, data: dict[str, Any], fields: set[str], action: Action) -> Item:
    item = get_item(session, item_id, lock=True)
    require_version(item, data["expected_version"])
    before = item_snapshot(session, item)
    for field in ("title", "content_md", "attributes"):
        if field in fields:
            value = data.get(field)
            if value is None:
                raise DomainError("invalid_input", f"{field} cannot be null", 422)
            setattr(item, field, value)
    if "category_id" in fields:
        _remove_existing_container(session, item, action)
        category_id = data.get("category_id")
        if category_id:
            require_category(session, category_id)
            item.category_id = category_id
            item.placement_state = "classified"
            item.inbox_entered_at = None
        else:
            item.category_id = None
            item.placement_state = "inbox"
            item.inbox_entered_at = utcnow()
    deadline_fields = {"due_date", "due_time", "due_timezone"}
    if fields & deadline_fields:
        if item.item_type != "task" or item.task is None:
            raise DomainError("invalid_input", "Deadline fields are only valid for tasks", 422)
        merged = {
            "due_date": data.get("due_date") if "due_date" in fields else item.task.due_date,
            "due_time": data.get("due_time") if "due_time" in fields else item.task.due_time,
            "due_timezone": data.get("due_timezone") if "due_timezone" in fields else item.task.due_timezone,
        }
        if merged["due_date"] is None and (merged["due_time"] is not None or merged["due_timezone"] is not None):
            raise DomainError("invalid_input", "Clearing due_date also requires clearing due_time and due_timezone", 422)
        if (merged["due_time"] is None) != (merged["due_timezone"] is None):
            raise DomainError("invalid_input", "due_time and due_timezone must be set or cleared together", 422)
        if merged["due_time"] is not None:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                zone = ZoneInfo(merged["due_timezone"])
            except ZoneInfoNotFoundError as exc:
                raise DomainError("invalid_input", "due_timezone must be an IANA timezone", 422) from exc
            if merged["due_time"].tzinfo is not None:
                raise DomainError("invalid_input", "due_time must be a local wall time without an offset", 422)
            local = datetime.combine(merged["due_date"], merged["due_time"])
            valid = any(
                local.replace(tzinfo=zone, fold=fold).astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local
                for fold in (0, 1)
            )
            if not valid:
                raise DomainError("invalid_input", "due_time does not exist in due_timezone on due_date", 422)
        for field, value in merged.items():
            setattr(item.task, field, value)
    bump(item)
    record_revision(session, action, item, before)
    if "category_id" in fields and item.item_type in ("folder", "project"):
        _propagate_folder_placement(session, item, action)
    return item


def append_item(session: Session, item_id: uuid.UUID, expected_version: int, content: str, action: Action) -> Item:
    item = get_item(session, item_id, lock=True)
    require_version(item, expected_version)
    before = item_snapshot(session, item)
    item.content_md = f"{item.content_md}\n\n{content}" if item.content_md else content
    bump(item)
    record_revision(session, action, item, before)
    return item


def transition_task(session: Session, item_id: uuid.UUID, expected_version: int, completed: bool, action: Action) -> Item:
    item = get_item(session, item_id, lock=True)
    require_version(item, expected_version)
    if item.item_type != "task" or not item.task:
        raise DomainError("invalid_transition", "Only tasks can be completed or reopened", 409)
    desired = "completed" if completed else "open"
    if item.task.status == desired:
        raise DomainError("invalid_transition", f"Task is already {desired}", 409)
    before = item_snapshot(session, item)
    item.task.status = desired
    item.task.completed_at = utcnow() if completed else None
    bump(item)
    record_revision(session, action, item, before)
    return item


def set_archived(session: Session, item_id: uuid.UUID, expected_version: int, archived: bool, action: Action) -> Item:
    item = get_item(session, item_id, lock=True)
    require_version(item, expected_version)
    if (item.archived_at is not None) == archived:
        raise DomainError("invalid_transition", "Item is already in the requested archive state", 409)
    before = item_snapshot(session, item)
    item.archived_at = utcnow() if archived else None
    if not archived and item.placement_state == "inbox":
        item.inbox_entered_at = utcnow()
    bump(item)
    record_revision(session, action, item, before)
    return item


def _would_create_cycle(session: Session, source_id: uuid.UUID, folder_id: uuid.UUID) -> bool:
    """Would linking `source_id part_of folder_id` close a loop?

    Walks `folder_id`'s own outgoing `part_of` chain (its parent, its
    parent's parent, ...); if `source_id` appears anywhere in that chain,
    `source_id` is already an ancestor of `folder_id`, so containing
    `source_id` inside `folder_id` would make `source_id` contain itself
    transitively.
    """
    pending = [folder_id]
    seen: set[uuid.UUID] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        if current == source_id:
            return True
        seen.add(current)
        pending.extend(
            session.scalars(
                select(ItemRelation.to_item_id).where(
                    ItemRelation.from_item_id == current,
                    ItemRelation.relation == "part_of",
                )
            ).all()
        )
    return False


def _propagate_folder_placement(session: Session, folder: Item, action: Action) -> None:
    """Keep stored category/Inbox placement coherent for a folder subtree."""
    pending = [folder.id]
    seen = {folder.id}
    descendants: list[Item] = []
    while pending:
        parent_ids = pending
        pending = []
        child_ids = session.scalars(
            select(ItemRelation.from_item_id).where(
                ItemRelation.relation == "part_of",
                ItemRelation.to_item_id.in_(parent_ids),
            )
        ).all()
        new_ids = sorted((value for value in child_ids if value not in seen), key=str)
        if not new_ids:
            continue
        seen.update(new_ids)
        pending.extend(new_ids)
        descendants.extend(
            session.scalars(
                select(Item)
                .options(joinedload(Item.task))
                .where(Item.id.in_(new_ids))
                .order_by(Item.id)
                .with_for_update(of=Item)
            ).unique().all()
        )
    for descendant in descendants:
        before = item_snapshot(session, descendant)
        descendant.category_id = folder.category_id
        descendant.placement_state = folder.placement_state
        descendant.inbox_entered_at = folder.inbox_entered_at if folder.placement_state == "inbox" else None
        bump(descendant)
        record_revision(session, action, descendant, before)


def _remove_existing_container(
    session: Session,
    item: Item,
    action: Action,
    *,
    keep_container_id: uuid.UUID | None = None,
) -> bool:
    """Remove an item's old filesystem parent and revise affected containers."""
    relations = session.scalars(
        select(ItemRelation)
        .where(ItemRelation.from_item_id == item.id, ItemRelation.relation == "part_of")
        .order_by(ItemRelation.id)
        .with_for_update()
    ).all()
    removed = [relation for relation in relations if relation.to_item_id != keep_container_id]
    if not removed:
        return False
    parent_ids = sorted({relation.to_item_id for relation in removed}, key=str)
    parents = session.scalars(
        select(Item)
        .options(joinedload(Item.task))
        .where(Item.id.in_(parent_ids))
        .order_by(Item.id)
        .with_for_update(of=Item)
    ).unique().all()
    before_parents = {parent.id: item_snapshot(session, parent) for parent in parents}
    for relation in removed:
        session.delete(relation)
    session.flush()
    for parent in parents:
        bump(parent)
        record_revision(session, action, parent, before_parents[parent.id])
    return True


def _place_in_container(item: Item, container: Item) -> None:
    """Sync `item`'s category/placement to reflect that it is now `part_of`
    `container` (a project or folder) — used identically whether that
    containment was just created through `/relations` or through `/move`,
    so an item's category never depends on which of the two routes was
    used to nest it. A project always means the Projects category. A
    folder's containment inherits whatever category the folder itself
    currently has, including staying in Inbox if the folder is itself
    still unclassified (an item cannot be "classified" with a null
    category_id).
    """
    if container.item_type == "project":
        item.category_id = CATEGORY_IDS["projects"]
        item.placement_state = "classified"
        item.inbox_entered_at = None
    else:
        item.category_id = container.category_id
        if container.category_id is not None:
            item.placement_state = "classified"
            item.inbox_entered_at = None
        else:
            item.placement_state = "inbox"
            if item.inbox_entered_at is None:
                item.inbox_entered_at = utcnow()


def create_relation(session: Session, data: dict[str, Any], action: Action) -> ItemRelation:
    if data["from_item_id"] == data["to_item_id"]:
        raise DomainError("invalid_input", "An item cannot relate to itself", 422)
    items = session.scalars(
        select(Item).options(joinedload(Item.task)).where(Item.id.in_([data["from_item_id"], data["to_item_id"]])).order_by(Item.id).with_for_update(of=Item)
    ).unique().all()
    by_id = {item.id: item for item in items}
    for key in ("from_item_id", "to_item_id"):
        if data[key] not in by_id:
            raise not_found("item", data[key])
    source, target = by_id[data["from_item_id"]], by_id[data["to_item_id"]]
    require_version(source, data["from_expected_version"])
    require_version(target, data["to_expected_version"])
    if data["relation"] == "part_of" and target.item_type not in ("project", "folder"):
        raise DomainError("invalid_input", "part_of must target a project or a folder", 422)
    if data["relation"] == "part_of" and source.item_type in ("folder", "project") and _would_create_cycle(session, source.id, target.id):
        raise DomainError("invalid_input", "This would make a container contain itself", 422)
    if data["relation"] == "part_of":
        current_parent = session.scalar(
            select(ItemRelation.to_item_id).where(
                ItemRelation.from_item_id == source.id,
                ItemRelation.relation == "part_of",
            )
        )
        if current_parent is not None and current_parent != target.id:
            raise DomainError(
                "already_contained",
                "Item already belongs to a folder or project; use move to replace its container",
                409,
                {"current_container_id": str(current_parent)},
            )
    exists = session.scalar(select(ItemRelation.id).where(ItemRelation.from_item_id == source.id, ItemRelation.relation == data["relation"], ItemRelation.to_item_id == target.id))
    if exists:
        raise DomainError("relation_exists", "The relationship already exists", 409, {"relation_id": str(exists)})
    before_source, before_target = item_snapshot(session, source), item_snapshot(session, target)
    if data["relation"] == "part_of":
        _place_in_container(source, target)
    relation = ItemRelation(from_item_id=source.id, relation=data["relation"], to_item_id=target.id)
    session.add(relation)
    session.flush()
    bump(source)
    bump(target)
    record_revision(session, action, source, before_source)
    record_revision(session, action, target, before_target)
    if data["relation"] == "part_of" and source.item_type in ("folder", "project"):
        _propagate_folder_placement(session, source, action)
    return relation


def delete_relation(session: Session, relation_id: uuid.UUID, from_expected: int, to_expected: int, action: Action) -> tuple[uuid.UUID, uuid.UUID]:
    relation = session.scalar(select(ItemRelation).where(ItemRelation.id == relation_id).with_for_update())
    if not relation:
        raise not_found("relation", relation_id)
    items = session.scalars(
        select(Item).options(joinedload(Item.task)).where(Item.id.in_([relation.from_item_id, relation.to_item_id])).order_by(Item.id).with_for_update(of=Item)
    ).unique().all()
    by_id = {item.id: item for item in items}
    source, target = by_id[relation.from_item_id], by_id[relation.to_item_id]
    require_version(source, from_expected)
    require_version(target, to_expected)
    before_source, before_target = item_snapshot(session, source), item_snapshot(session, target)
    session.delete(relation)
    session.flush()
    bump(source)
    bump(target)
    record_revision(session, action, source, before_source)
    record_revision(session, action, target, before_target)
    return source.id, target.id


def move_item(session: Session, item_id: uuid.UUID, data: dict[str, Any], action: Action) -> Item:
    item = get_item(session, item_id, lock=True)
    require_version(item, data["expected_version"])
    before = item_snapshot(session, item)
    if data.get("inbox"):
        _remove_existing_container(session, item, action)
        item.category_id = None
        item.placement_state = "inbox"
        item.inbox_entered_at = utcnow()
    elif data.get("category_id"):
        require_category(session, data["category_id"])
        _remove_existing_container(session, item, action)
        item.category_id = data["category_id"]
        item.placement_state = "classified"
        item.inbox_entered_at = None
    elif data.get("project_id"):
        project = get_item(session, data["project_id"], lock=True)
        require_version(project, data["project_expected_version"])
        if project.item_type != "project":
            raise DomainError("invalid_input", "project_id must identify a project", 422)
        if project.id == item.id:
            raise DomainError("invalid_input", "A project cannot contain itself", 422)
        if item.item_type in ("folder", "project") and _would_create_cycle(session, item.id, project.id):
            raise DomainError("invalid_input", "This would make a container contain itself", 422)
        before_project = item_snapshot(session, project)
        changed_parent = _remove_existing_container(session, item, action, keep_container_id=project.id)
        _place_in_container(item, project)
        existing = session.scalar(select(ItemRelation).where(ItemRelation.from_item_id == item.id, ItemRelation.relation == "part_of", ItemRelation.to_item_id == project.id))
        if not existing:
            session.add(ItemRelation(from_item_id=item.id, relation="part_of", to_item_id=project.id))
            session.flush()
        if not existing or changed_parent:
            bump(project)
            record_revision(session, action, project, before_project)
    else:
        folder = get_item(session, data["folder_id"], lock=True)
        require_version(folder, data["folder_expected_version"])
        if folder.item_type != "folder":
            raise DomainError("invalid_input", "folder_id must identify a folder", 422)
        if folder.id == item.id:
            raise DomainError("invalid_input", "A folder cannot contain itself", 422)
        if item.item_type in ("folder", "project") and _would_create_cycle(session, item.id, folder.id):
            raise DomainError("invalid_input", "This would make a container contain itself", 422)
        before_folder = item_snapshot(session, folder)
        changed_parent = _remove_existing_container(session, item, action, keep_container_id=folder.id)
        _place_in_container(item, folder)
        existing = session.scalar(select(ItemRelation).where(ItemRelation.from_item_id == item.id, ItemRelation.relation == "part_of", ItemRelation.to_item_id == folder.id))
        if not existing:
            session.add(ItemRelation(from_item_id=item.id, relation="part_of", to_item_id=folder.id))
            session.flush()
        if not existing or changed_parent:
            bump(folder)
            record_revision(session, action, folder, before_folder)
    bump(item)
    record_revision(session, action, item, before)
    if item.item_type in ("folder", "project"):
        _propagate_folder_placement(session, item, action)
    return item


def permanently_delete(session: Session, item_id: uuid.UUID, expected_version: int, action: Action) -> None:
    item = get_item(session, item_id, lock=True)
    require_version(item, expected_version)
    if item.archived_at is None:
        raise DomainError("invalid_transition", "Only archived items can be permanently deleted", 409)
    links = session.scalars(select(ItemRelation.id).where(or_(ItemRelation.from_item_id == item.id, ItemRelation.to_item_id == item.id))).all()
    if links:
        raise DomainError("linked_item_conflict", "Unlink the item before permanently deleting it", 409, {"relation_ids": [str(value) for value in links]})
    prior_action_ids = session.scalars(select(ItemRevision.action_id).where(ItemRevision.item_id == item.id)).all()
    if prior_action_ids:
        prior_actions = session.scalars(select(Action).where(Action.id.in_(prior_action_ids))).all()
        for prior_action in prior_actions:
            prior_action.result = {"purged_item_id": str(item.id), "result_purged": True}
    session.delete(item)
    action.result = {"deleted_id": str(item_id)}


def restore_snapshot(session: Session, item: Item, snapshot: dict[str, Any]) -> None:
    from backend.capture_models import Capture, ItemSource
    from backend.asset_models import Asset, ItemAsset
    # A source/asset deleted permanently cannot be recreated by undo.
    for model, target_model, key, target_key in (
        (ItemSource, Capture, "source_ids", "capture_id"),
        (ItemAsset, Asset, "asset_ids", "asset_id"),
    ):
        if key not in snapshot:
            continue
        desired = {uuid.UUID(value) for value in snapshot[key]}
        existing = session.scalars(select(model).where(model.item_id == item.id)).all()
        present = {getattr(link, target_key) for link in existing}
        for target_id in sorted(desired - present):
            target = session.scalar(select(target_model).where(target_model.id == target_id).with_for_update())
            if target is None or (key == "asset_ids" and target.upload_state != "ready"):
                raise DomainError("undo_unavailable", "An original source or asset is no longer available", 409)
            session.add(model(item_id=item.id, **{target_key: target_id}))
        for link in existing:
            if getattr(link, target_key) not in desired:
                session.delete(link)
    item.title = snapshot["title"]
    item.content_md = snapshot["content_md"]
    item.category_id = uuid.UUID(snapshot["category_id"]) if snapshot["category_id"] else None
    item.placement_state = snapshot["placement_state"]
    item.attributes = snapshot["attributes"]
    item.archived_at = datetime.fromisoformat(snapshot["archived_at"]) if snapshot["archived_at"] else None
    item.inbox_entered_at = datetime.fromisoformat(snapshot["inbox_entered_at"]) if snapshot["inbox_entered_at"] else None
    task = snapshot.get("task")
    if task and item.task:
        from datetime import date, time
        item.task.status = task["status"]
        item.task.due_date = date.fromisoformat(task["due_date"]) if task["due_date"] else None
        item.task.due_time = time.fromisoformat(task["due_time"]) if task["due_time"] else None
        item.task.due_timezone = task["due_timezone"]
        item.task.completed_at = datetime.fromisoformat(task["completed_at"]) if task["completed_at"] else None


def undo_action(session: Session, original_id: uuid.UUID, expected_versions: dict[uuid.UUID, int], undo: Action) -> list[Item]:
    original = session.scalar(select(Action).where(Action.id == original_id).with_for_update())
    if not original:
        raise not_found("action", original_id)
    if original.undone_by_action_id:
        raise DomainError("invalid_transition", "Action has already been undone", 409)
    if original.result and original.result.get("result_purged"):
        raise DomainError("undo_unavailable", "This grouped action is no longer fully undoable", 409)
    # Capture actions also mutate processing/generation/source state. The generic
    # item-snapshot undo cannot reverse that half atomically, so refuse instead of
    # leaving the capture and its resulting/source links inconsistent.
    from backend.capture_models import CaptureRevision

    if session.scalar(select(CaptureRevision.id).where(CaptureRevision.action_id == original.id).limit(1)):
        raise DomainError("undo_unavailable", "Capture actions cannot yet be undone through the item action endpoint", 409)
    revisions = session.scalars(select(ItemRevision).where(ItemRevision.action_id == original.id).order_by(ItemRevision.item_id)).all()
    if not revisions or any(revision.before_snapshot is None for revision in revisions):
        raise DomainError("undo_unavailable", "This action cannot be undone", 409)
    if set(expected_versions) != {revision.item_id for revision in revisions}:
        raise DomainError("invalid_input", "expected_versions must cover every item changed by the action", 422)
    items: list[Item] = []
    before_undo: dict[uuid.UUID, dict[str, Any]] = {}
    for revision in revisions:
        item = get_item(session, revision.item_id, lock=True)
        require_version(item, expected_versions[item.id])
        if item.version != revision.resulting_version:
            raise DomainError(
                "version_conflict",
                "The action cannot be undone after a later edit",
                409,
                {"id": str(item.id), "action_resulting_version": revision.resulting_version, "actual_version": item.version},
            )
        before_undo[item.id] = item_snapshot(session, item)
        restore_snapshot(session, item, revision.before_snapshot or {})
        bump(item)
        items.append(item)
    affected_ids = [item.id for item in items]
    current_relations = session.scalars(
        select(ItemRelation).where(or_(ItemRelation.from_item_id.in_(affected_ids), ItemRelation.to_item_id.in_(affected_ids)))
    ).all()
    for relation in current_relations:
        session.delete(relation)
    session.flush()
    desired_relations: dict[uuid.UUID, dict[str, Any]] = {}
    for revision in revisions:
        for relation in (revision.before_snapshot or {}).get("relations", []):
            desired_relations[uuid.UUID(relation["id"])] = relation
    for relation_id, relation in desired_relations.items():
        session.add(
            ItemRelation(
                id=relation_id,
                from_item_id=uuid.UUID(relation["from_item_id"]),
                relation=relation["relation"],
                to_item_id=uuid.UUID(relation["to_item_id"]),
                created_at=datetime.fromisoformat(relation["created_at"]) if relation.get("created_at") else utcnow(),
            )
        )
    session.flush()
    for item in items:
        record_revision(session, undo, item, before_undo[item.id])
    original.undone_by_action_id = undo.id
    return items
