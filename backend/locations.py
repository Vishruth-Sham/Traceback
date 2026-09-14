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


@router.get("/locations")
def list_locations(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
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

    def path_for(item: Item) -> str:
        names = [item.title]
        seen = {item.id}
        parent_id = parents.get(item.id)
        while parent_id in by_id and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id[parent_id]
            names.append(parent.title)
            parent_id = parents.get(parent_id)
        names.append(category_names.get(item.category_id, "Inbox"))
        return " / ".join(reversed(names))

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
    needle = q.strip().casefold() if q else ""
    if needle:
        rows = [row for row in rows if needle in row["title"].casefold() or needle in row["path"].casefold()]
    rows.sort(key=lambda row: (row["path"].casefold(), row["kind"], row["id"]))
    offset = _offset(cursor)
    page = rows[offset : offset + limit + 1]
    return {"items": page[:limit], "next_cursor": _cursor(offset + limit) if len(page) > limit else None}
