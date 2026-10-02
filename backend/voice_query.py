"""Read-only voice query resolution: DB reads only, never a mutation path.

Classification is deterministic (`backend.voice_policy.query`); this module executes the
matching read against the same tables the equivalent REST endpoints (`/tasks`, `/inbox`,
`/items`) use, and formats the outcome for the voice command panel. Nothing here ever
creates, updates, archives, or deletes an `Item`.
"""
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.api import item_out
from backend.capture_models import Capture, CaptureProcessing
from backend.locations import breadcrumbs_for, build_catalog, container_index, direct_parents_for
from backend.models import Category, Item, ItemRelation, TaskDetail
from backend.voice_policy.query import QueryClassification, classify_query, clean_query_phrase
from backend.voice_policy.text import normalize

_MAX_MATCHES = 10


def _late_text(due_date: date | None, today: date) -> str | None:
    if due_date is None:
        return None
    delta = (today - due_date).days
    if delta > 0:
        return f"{delta}d late"
    if delta == 0:
        return "Due today"
    return due_date.strftime("Due %a")


def _route_for(
    item: Item,
    *,
    by_id: dict[uuid.UUID, Item],
    parents: dict[uuid.UUID, uuid.UUID],
    category_slugs: dict[uuid.UUID | None, str],
    direct_parent_id: uuid.UUID | None,
) -> str:
    if item.item_type == "project":
        return f"/projects/{item.id}"
    if item.item_type == "task":
        return f"/tasks?open={item.id}"
    # A folder has no view of its own: "open" lands on the page that lists it, without the detail panel.
    panel = "" if item.item_type == "folder" else f"?open={item.id}"
    if item.item_type == "note":
        return f"/notes/{item.id}"
    seen = {item.id}
    parent_id = direct_parent_id
    while parent_id in by_id and parent_id not in seen:
        parent = by_id[parent_id]
        if parent.item_type == "project":
            return f"/projects/{parent.id}{panel}"
        seen.add(parent_id)
        parent_id = parents.get(parent_id)
    if item.item_type == "folder":
        slug = category_slugs.get(item.category_id)
        return f"/category/{slug}" if slug else "/inbox"
    slug = category_slugs.get(item.category_id)
    return f"/category/{slug}?open={item.id}" if slug else f"/inbox?open={item.id}"


def _match_batch(session: Session, items: list[Item], *, metas: dict[uuid.UUID, str | None] | None = None) -> list[dict[str, Any]]:
    if not items:
        return []
    by_id, parents, category_names = container_index(session)
    category_rows = session.execute(select(Category.id, Category.slug)).all()
    category_slugs = {row[0]: row[1] for row in category_rows}
    direct_parents = direct_parents_for(session, [item.id for item in items])
    paths = breadcrumbs_for(session, items)
    metas = metas or {}
    return [
        {
            "id": str(item.id),
            "item_type": item.item_type,
            "title": item.title,
            "path": paths.get(item.id),
            "meta": metas.get(item.id),
            "route": _route_for(
                item, by_id=by_id, parents=parents, category_slugs=category_slugs, direct_parent_id=direct_parents.get(item.id)
            ),
        }
        for item in items
    ]


def _resolve_overdue_tasks(session: Session, today: date) -> dict[str, Any]:
    rows = session.scalars(
        select(Item)
        .join(TaskDetail)
        .options(joinedload(Item.task))
        .where(Item.archived_at.is_(None), TaskDetail.status == "open")
        .order_by(TaskDetail.due_date.asc().nulls_last(), Item.created_at)
    ).unique().all()
    overdue = [row for row in rows if item_out(session, row, include_content=False)["overdue"]][:_MAX_MATCHES]
    metas = {row.id: _late_text(row.task.due_date, today) for row in overdue}
    matches = _match_batch(session, overdue, metas=metas)
    note = None if matches else "No tasks are overdue right now."
    return {"kind": "result", "label": "Overdue tasks", "matches": matches, "note": note, "footer_action": {"label": "Open Tasks", "route": "/tasks"} if matches else None}


def _resolve_all_tasks(session: Session) -> dict[str, Any]:
    rows = session.scalars(
        select(Item)
        .join(TaskDetail)
        .options(joinedload(Item.task))
        .where(Item.archived_at.is_(None), TaskDetail.status == "open")
        .order_by(TaskDetail.due_date.asc().nulls_last(), Item.created_at)
        .limit(_MAX_MATCHES)
    ).unique().all()
    matches = _match_batch(session, list(rows))
    note = None if matches else "You have no open tasks."
    return {"kind": "result", "label": "Open tasks", "matches": matches, "note": note, "footer_action": {"label": "Open Tasks", "route": "/tasks"} if matches else None}


# Fixed pages that voice can open or list. `listable` pages reuse an existing resolver; the rest only navigate.
_PAGES = (
    {"key": "inbox", "title": "Inbox", "route": "/inbox", "aliases": {"inbox", "in box"}, "listable": True},
    {"key": "tasks", "title": "Tasks", "route": "/tasks", "aliases": {"tasks", "task", "task list", "todos", "to dos", "todo"}, "listable": True},
    {"key": "projects", "title": "Projects", "route": "/projects", "aliases": {"projects", "project"}, "listable": True},
    {"key": "archive", "title": "Archive", "route": "/archive", "aliases": {"archive", "archived"}, "listable": False},
)
_SCOPE_LEAD = re.compile(r"^(?:(?:everything|all|my|the|every)\s+)+(?:in\s+)?|^in\s+")
_SCOPE_TRAIL = re.compile(r"\s+(?:page|tab|list|category|section)$")


def _scope_needle(phrase: str) -> str:
    """Bare name of what the speaker pointed at: "all the projects" -> "projects"."""
    text = _SCOPE_TRAIL.sub("", _SCOPE_LEAD.sub("", normalize(phrase)))
    return text.strip()


def _page_hits(needle: str) -> list[dict[str, Any]]:
    return [page for page in _PAGES if needle in page["aliases"]]


def _page_match(page: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"page:{page['key']}", "item_type": "page", "title": page["title"], "path": "Pages", "meta": None, "route": page["route"]}


def _category_hits(session: Session, needle: str) -> tuple[list[Category], list[Category]]:
    """(exact, partial) category matches by normalized name or slug."""
    exact: list[Category] = []
    partial: list[Category] = []
    for category in session.scalars(select(Category).order_by(Category.sort_order, Category.id)):
        name = normalize(category.name)
        if needle in (name, normalize(category.slug)):
            exact.append(category)
        elif len(needle) >= 4 and needle in name.split():
            partial.append(category)
    return exact, partial


def _category_match(category: Category) -> dict[str, Any]:
    return {"id": str(category.id), "item_type": "category", "title": category.name, "path": "Categories", "meta": None, "route": f"/category/{category.slug}"}


def _children_of(session: Session, container: Item | Category) -> tuple[list[Item], int]:
    """Direct children of a category (top-level items) or a folder/project (`part_of` it)."""
    if isinstance(container, Category):
        has_parent = select(ItemRelation.id).where(ItemRelation.relation == "part_of", ItemRelation.from_item_id == Item.id).exists()
        condition = (Item.category_id == container.id) & ~has_parent
        query = select(Item).where(Item.archived_at.is_(None), condition)
    else:
        query = (
            select(Item)
            .join(ItemRelation, ItemRelation.from_item_id == Item.id)
            .where(Item.archived_at.is_(None), ItemRelation.relation == "part_of", ItemRelation.to_item_id == container.id)
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = case((Item.item_type.in_(("folder", "project")), 0), else_=1)
    rows = session.scalars(query.options(joinedload(Item.task)).order_by(order, Item.title, Item.id).limit(_MAX_MATCHES)).unique().all()
    return list(rows), total


def _list_container(session: Session, container: Item | Category, today: date) -> dict[str, Any]:
    children, total = _children_of(session, container)
    metas = {
        row.id: (_late_text(row.task.due_date, today) if row.item_type == "task" and row.task else row.item_type.capitalize())
        for row in children
    }
    matches = _match_batch(session, children, metas=metas)
    if isinstance(container, Category):
        title, route = container.name, f"/category/{container.slug}"
    else:
        title, route = container.title, _match_batch(session, [container])[0]["route"]
    note = f"{title} is empty." if not matches else (f"Showing {len(matches)} of {total}." if total > len(matches) else None)
    return {"kind": "result", "label": f"In {title}", "matches": matches, "note": note, "footer_action": {"label": f"Open {title}", "route": route}}


def _resolve_list_contents(session: Session, phrase: str, today: date) -> dict[str, Any]:
    """"Show all projects", "what's in Learning", "what's in filmmaking": list a page's or container's items."""
    needle = _scope_needle(phrase)
    parts = needle.rsplit(" in ", 1)
    leaf, parent_needle = parts[0].strip(), (parts[1].strip() if len(parts) == 2 else None)
    pages = _page_hits(leaf) if parent_needle is None else []
    if len(pages) == 1:
        page = pages[0]
        if page["key"] == "inbox":
            return _resolve_inbox_summary(session)
        if page["key"] == "tasks":
            return _resolve_all_tasks(session)
        if page["key"] == "projects":
            rows = session.scalars(
                select(Item).where(Item.item_type == "project", Item.archived_at.is_(None)).order_by(Item.title, Item.id).limit(_MAX_MATCHES)
            ).all()
            matches = _match_batch(session, list(rows))
            note = None if matches else "You have no projects."
            return {"kind": "result", "label": "Projects", "matches": matches, "note": note, "footer_action": {"label": "Open Projects", "route": page["route"]}}
        return {"kind": "confirm", "confirm": _page_match(page)}  # Archive has no item list to read out.
    containers: list[Item | Category] = []
    exact_categories: list[Category] = []
    if parent_needle is None:
        exact_categories, partial = _category_hits(session, leaf)
        containers.extend(exact_categories or partial)
    catalog_ids = [
        uuid.UUID(row["id"])
        for row in build_catalog(session)
        if row["kind"] in ("folder", "project")
        and leaf in normalize(row["title"])
        and (parent_needle is None or parent_needle in normalize(row["path"]))
    ]
    if catalog_ids:
        containers.extend(session.scalars(select(Item).where(Item.id.in_(catalog_ids)).order_by(Item.title, Item.id)).all())
    if not containers:
        return {"kind": "no_results", "note": f'Nothing named "{phrase}" was found. Try rephrasing.'}
    # A category named exactly wins over folders that merely contain the word, unless a folder is named exactly the same.
    if len(exact_categories) == 1 and not any(isinstance(c, Item) and normalize(c.title) == leaf for c in containers):
        return _list_container(session, exact_categories[0], today)
    if len(containers) == 1:
        return _list_container(session, containers[0], today)
    matches = [_category_match(c) if isinstance(c, Category) else _match_batch(session, [c])[0] for c in containers]
    return {"kind": "ambiguous", "label": f"I found {len(matches)} places named {phrase}", "matches": matches, "note": "Select one — Traceback never guesses."}


def _resolve_inbox_summary(session: Session) -> dict[str, Any]:
    rows = session.scalars(
        select(Item)
        .where(Item.placement_state == "inbox", Item.item_type != "task", Item.archived_at.is_(None))
        .order_by(Item.inbox_entered_at.desc(), Item.id)
        .limit(_MAX_MATCHES)
    ).all()
    pending_captures = session.scalar(
        select(func.count()).select_from(Capture).join(CaptureProcessing).where(Capture.archived_at.is_(None), CaptureProcessing.state != "resolved")
    ) or 0
    metas = {row.id: ("Unclassified note" if row.item_type == "note" else row.item_type.capitalize()) for row in rows}
    matches = _match_batch(session, list(rows), metas=metas)
    note = None
    if pending_captures:
        note = f"{pending_captures} capture{'s' if pending_captures != 1 else ''} still processing."
    if not matches and not pending_captures:
        note = "Inbox is empty."
    return {"kind": "result", "label": "Inbox", "matches": matches, "note": note, "footer_action": {"label": "Open Inbox", "route": "/inbox"} if matches else None}


def _resolve_search(session: Session, phrase: str) -> dict[str, Any]:
    pattern = f"%{phrase}%"
    rows = session.scalars(
        select(Item)
        .options(joinedload(Item.task))
        .where(Item.archived_at.is_(None), or_(Item.title.ilike(pattern), Item.content_md.ilike(pattern)))
        .order_by(Item.updated_at.desc(), Item.id)
        .limit(_MAX_MATCHES)
    ).unique().all()
    if not rows:
        return {"kind": "no_results", "note": 'No matches found. Try rephrasing, or say "show all tasks".'}
    matches = _match_batch(session, list(rows))
    return {"kind": "result", "label": f'Results for “{phrase}”', "matches": matches, "note": None, "footer_action": None, "numbered": True}


def _resolve_navigate(session: Session, phrase: str) -> dict[str, Any]:
    # Natural navigation often names both the item and its parent: "filmmaking in
    # Learning". Match the leaf against the title and the qualifier against its
    # canonical breadcrumb instead of treating the whole utterance as one title.
    scoped = _scope_needle(phrase)
    parts = phrase.rsplit(" in ", 1)
    item_phrase = parts[0].strip()
    parent_phrase = parts[1].strip() if len(parts) == 2 else None
    needle = item_phrase.casefold()
    parent_needle = parent_phrase.casefold() if parent_phrase else None

    # A fixed page or a category named exactly wins over looser title matches, so "open learning"
    # goes to the Learning page and not to a note that merely mentions it.
    page_and_category: list[dict[str, Any]] = []
    if parent_needle is None:
        exact_categories, partial_categories = _category_hits(session, scoped)
        pages = _page_hits(scoped)
        # The Projects category and the Projects page are the same destination: the page wins.
        page_and_category = [_page_match(p) for p in pages] + [_category_match(c) for c in exact_categories if not pages]
        looser = [_category_match(c) for c in partial_categories]
    else:
        looser = []
    catalog_hits = [
        row
        for row in build_catalog(session)
        if row["kind"] != "category"
        and needle in row["title"].casefold()
        and (parent_needle is None or parent_needle in row["path"].casefold())
    ]
    item_hits = session.scalars(
        select(Item)
        .where(Item.archived_at.is_(None), Item.item_type.in_(("note", "task")), Item.title.ilike(f"%{item_phrase}%"))
        .order_by(Item.title)
        .limit(_MAX_MATCHES)
    ).all()
    if parent_needle:
        paths = breadcrumbs_for(session, list(item_hits))
        item_hits = [item for item in item_hits if parent_needle in paths.get(item.id, "").casefold()]
    candidate_ids = {uuid.UUID(row["id"]) for row in catalog_hits} | {row.id for row in item_hits}
    candidates = (
        session.scalars(select(Item).options(joinedload(Item.task)).where(Item.id.in_(candidate_ids))).unique().all() if candidate_ids else []
    )
    item_matches = _match_batch(session, list(candidates))
    exact_item = any(match["title"].casefold() == needle for match in item_matches)
    if len(page_and_category) == 1 and not exact_item:
        return {"kind": "confirm", "confirm": page_and_category[0]}
    matches = page_and_category + item_matches + looser
    if not matches:
        return {"kind": "no_results", "note": f'No item named "{phrase}" was found. Try rephrasing.'}
    if len(matches) == 1:
        return {"kind": "confirm", "confirm": matches[0]}
    noun = {"project": "projects", "folder": "folders", "note": "notes", "task": "tasks", "page": "pages", "category": "categories"}
    kinds = {match["item_type"] for match in matches}
    kind_label = noun.get(next(iter(kinds))) if len(kinds) == 1 else "items"
    return {
        "kind": "ambiguous",
        "label": f"I found {len(matches)} {kind_label} named {phrase}",
        "matches": matches,
        "note": "Select one — Traceback never guesses.",
        "numbered": True,
    }


def _resolve_followup(session: Session, index: int, contextual_capture_id: uuid.UUID | None) -> dict[str, Any]:
    unavailable = {"kind": "no_results", "query_text": None, "note": "That selection isn't available anymore. Try again."}
    if contextual_capture_id is None:
        return unavailable
    referenced = session.get(Capture, contextual_capture_id)
    if referenced is None or referenced.archived_at is not None:
        return unavailable
    processing = referenced.processing
    if processing is None or processing.state != "resolved" or not processing.query_result:
        return unavailable
    stored = processing.query_result
    candidates = stored.get("matches") if stored.get("numbered") else None
    if not candidates or not (1 <= index <= len(candidates)):
        return unavailable
    chosen = candidates[index - 1]
    item = session.get(Item, uuid.UUID(chosen["id"]))
    if item is None or item.archived_at is not None:
        return {"kind": "no_results", "query_text": None, "note": "That item is no longer available."}
    matches = _match_batch(session, [item])
    return {"kind": "confirm", "confirm": matches[0]}


def resolve(
    session: Session, capture: Capture, transcript: str, *, kind: str | None = None, phrase: str | None = None
) -> dict[str, Any] | None:
    """Resolve a read-only query and return the result payload to store.

    `kind`/`phrase` come from the processor's Qwen classification; the lexicon is only a
    fallback when they are omitted. Returns None when this is not a query (or a phrase-taking
    kind has no usable phrase), so the caller can fall through to the create flow.
    """
    metadata = capture.source_metadata or {}
    contextual_capture_id = metadata.get("contextual_capture_id")
    if kind is not None:
        classification = QueryClassification(kind=kind, phrase=clean_query_phrase(phrase) or None)
        if kind in ("search", "navigate", "list_contents") and not classification.phrase:
            return None
    else:
        classification = classify_query(transcript, has_followup_context=bool(contextual_capture_id))

    if classification.kind == "not_a_query":
        return None
    if classification.kind == "all_tasks":
        result = _resolve_all_tasks(session)
    elif classification.kind == "list_contents":
        result = _resolve_list_contents(session, classification.phrase or "", date.today())
    elif classification.kind == "overdue_tasks":
        result = _resolve_overdue_tasks(session, date.today())
    elif classification.kind == "inbox_summary":
        result = _resolve_inbox_summary(session)
    elif classification.kind == "search":
        result = _resolve_search(session, classification.phrase or "")
    elif classification.kind == "navigate":
        result = _resolve_navigate(session, classification.phrase or "")
    elif classification.kind == "followup_select":
        result = _resolve_followup(
            session, classification.index or 0, uuid.UUID(contextual_capture_id) if contextual_capture_id else None
        )
    else:
        return None
    result.setdefault("query_text", transcript)
    return result
