"""Canonical, read-only destination catalog shared by UI and processor."""
import base64
import binascii
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import authenticate
from backend.db import get_session
from backend.errors import DomainError
from backend.models import Category, Item, ItemRelation

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])
SessionDep = Annotated[Session, Depends(get_session)]


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode())
        if value < 0:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise DomainError("invalid_cursor", "Pagination cursor is invalid", 422) from None


def _cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode()).decode().rstrip("=")


def container_index(session: Session) -> tuple[dict[uuid.UUID, Item], dict[uuid.UUID, uuid.UUID], dict[uuid.UUID | None, str]]:
    """Shared lookup tables for walking any item's `part_of` chain up to its category."""
    categories = session.scalars(select(Category).order_by(Category.sort_order, Category.id)).all()
    containers = session.scalars(
        select(Item).where(Item.item_type.in_(("project", "folder")), Item.archived_at.is_(None)).order_by(Item.id)
    ).all()
    by_id = {item.id: item for item in containers}
    parents = dict(
        session.execute(
            select(ItemRelation.from_item_id, ItemRelation.to_item_id).where(
                ItemRelation.relation == "part_of", ItemRelation.from_item_id.in_(by_id)
            )
        ).all()
    )
    category_names = {category.id: category.name for category in categories}
    return by_id, parents, category_names


def path_for_item(
    item: Item,
    *,
    by_id: dict[uuid.UUID, Item],
    parents: dict[uuid.UUID, uuid.UUID],
    category_names: dict[uuid.UUID | None, str],
    direct_parent_id: uuid.UUID | None = None,
) -> str:
    """Breadcrumb for `item`, whether it is itself a container or a leaf note/task."""
    names = [item.title]
    seen = {item.id}
    parent_id = direct_parent_id if direct_parent_id is not None else parents.get(item.id)
    while parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        names.append(parent.title)
        parent_id = parents.get(parent_id)
    names.append(category_names.get(item.category_id, "Inbox"))
    return " / ".join(reversed(names))


def direct_parents_for(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Each item's own immediate `part_of` parent, if any."""
    if not item_ids:
        return {}
    return dict(
        session.execute(
            select(ItemRelation.from_item_id, ItemRelation.to_item_id).where(
                ItemRelation.relation == "part_of", ItemRelation.from_item_id.in_(item_ids)
            )
        ).all()
    )


def breadcrumbs_for(session: Session, items: list[Item]) -> dict[uuid.UUID, str]:
    """Batch breadcrumb paths for arbitrary items (notes, tasks, projects, folders alike)."""
    if not items:
        return {}
    by_id, parents, category_names = container_index(session)
    direct_parents = direct_parents_for(session, [item.id for item in items])
    return {
        item.id: path_for_item(
            item, by_id=by_id, parents=parents, category_names=category_names, direct_parent_id=direct_parents.get(item.id)
        )
        for item in items
    }


def build_catalog(session: Session) -> list[dict]:
    """Canonical category/project/folder catalog with breadcrumb paths, sorted by path."""
    by_id, parents, category_names = container_index(session)
    categories = session.scalars(select(Category).order_by(Category.sort_order, Category.id)).all()
    containers = list(by_id.values())

    def path_for(item: Item) -> str:
        return path_for_item(item, by_id=by_id, parents=parents, category_names=category_names)

    rows = [
        {
            "kind": "category",
            "id": str(category.id),
            "title": category.name,
            "path": category.name,
            "category_id": str(category.id),
            "version": None,
        }
        for category in categories
    ]
    rows.extend(
        {
            "kind": item.item_type,
            "id": str(item.id),
            "title": item.title,
            "path": path_for(item),
            "category_id": str(item.category_id) if item.category_id else None,
            "version": item.version,
        }
        for item in containers
    )
    rows.sort(key=lambda row: (row["path"].casefold(), row["kind"], row["id"]))
    return rows


@router.get("/locations")
def list_locations(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = build_catalog(session)
    needle = q.strip().casefold() if q else ""
    if needle:
        rows = [row for row in rows if needle in row["title"].casefold() or needle in row["path"].casefold()]
    offset = _offset(cursor)
    page = rows[offset : offset + limit + 1]
    return {"items": page[:limit], "next_cursor": _cursor(offset + limit) if len(page) > limit else None}
