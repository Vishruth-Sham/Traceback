"""Daily log: append-only free-text entries, disposable labels/summaries, and the end-of-day classify pass."""
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.api import ActionContext, authenticate
from backend.config import Settings, get_settings
from backend.db import get_session
from backend.errors import DomainError, not_found
from backend.log_models import DaySummary, EntryLabel, LogCategory, LogEntry
from backend.log_schemas import (
    ClassifyOut,
    ClassifyRequest,
    LogCategoryCreate,
    LogCategoryOut,
    LogCategoryPatch,
    LogDaysOut,
    LogRangeOut,
    LogEntryCreate,
    LogEntryOut,
    LogSearchOut,
)

router = APIRouter(prefix="/api/v1/log", dependencies=[Depends(authenticate)])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def logical_date(moment: datetime, settings: Settings) -> date:
    """The log day a moment belongs to: local time shifted back by `day_start_hour`."""
    local = moment.astimezone(ZoneInfo(settings.user_timezone))
    return (local - timedelta(hours=settings.day_start_hour)).date()


def _entries_out(session: Session, rows: list[LogEntry]) -> list[LogEntryOut]:
    labels: dict[uuid.UUID, list[str]] = {}
    if rows:
        for label in session.scalars(select(EntryLabel).where(EntryLabel.entry_id.in_([row.id for row in rows])).order_by(EntryLabel.label)):
            labels.setdefault(label.entry_id, []).append(label.label)
    return [
        LogEntryOut(id=row.id, logged_at=row.logged_at, log_date=row.log_date, text=row.text, origin=row.origin, labels=labels.get(row.id, []))
        for row in rows
    ]


def _active(statement):
    return statement.where(LogEntry.archived_at.is_(None))


def _origin(client_label: str) -> Literal["ui", "mcp"]:
    return "mcp" if client_label.lower().startswith("mcp") or client_label.lower().startswith("traceback-mcp") else "ui"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=LogEntryOut)
def create_entry(body: LogEntryCreate, session: SessionDep, settings: SettingsDep, context: ActionContext):
    _key, client_label = context
    if body.at is None:
        moment = datetime.now(UTC)
    elif body.at.tzinfo is None:
        moment = body.at.replace(tzinfo=ZoneInfo(settings.user_timezone))
    else:
        moment = body.at
    entry = LogEntry(logged_at=moment, log_date=logical_date(moment, settings), text=body.text, origin=_origin(client_label))
    session.add(entry)
    session.commit()
    return _entries_out(session, [entry])[0]


@router.get("/days", response_model=LogDaysOut)
def list_days(
    session: SessionDep,
    settings: SettingsDep,
    before: date | None = None,
    limit: Annotated[int, Query(ge=1, le=60)] = 14,
):
    """Days that have entries, newest first. `today` is always reported so the client can show an empty today."""
    days_query = _active(select(LogEntry.log_date).distinct())
    if before is not None:
        days_query = days_query.where(LogEntry.log_date < before)
    dates = list(session.scalars(days_query.order_by(LogEntry.log_date.desc()).limit(limit + 1)))
    more = len(dates) > limit
    dates = dates[:limit]
    result = []
    if dates:
        rows = session.scalars(
            _active(select(LogEntry)).where(LogEntry.log_date.in_(dates)).order_by(LogEntry.log_date.desc(), LogEntry.logged_at, LogEntry.id)
        ).all()
        summaries = {row.log_date: row.summary for row in session.scalars(select(DaySummary).where(DaySummary.log_date.in_(dates)))}
        entries = _entries_out(session, list(rows))
        for day in dates:
            result.append({"log_date": day, "summary": summaries.get(day), "entries": [entry for entry in entries if entry.log_date == day]})
    return LogDaysOut(today=logical_date(datetime.now(UTC), settings), days=result, next_before=dates[-1] if more else None)


MAX_RANGE_DAYS = 93


@router.get("/range", response_model=LogRangeOut)
def get_range(session: SessionDep, start: date, end: date):
    """Every day with entries between `start` and `end` inclusive (at most 93 days), oldest first, with labels and summaries."""
    if end < start:
        raise DomainError("invalid_range", "end must not be before start", 422)
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise DomainError("range_too_large", f"A range may span at most {MAX_RANGE_DAYS} days", 422)
    rows = session.scalars(
        _active(select(LogEntry)).where(LogEntry.log_date >= start, LogEntry.log_date <= end).order_by(LogEntry.log_date, LogEntry.logged_at, LogEntry.id)
    ).all()
    entries = _entries_out(session, list(rows))
    dates = sorted({entry.log_date for entry in entries})
    summaries = {row.log_date: row.summary for row in session.scalars(select(DaySummary).where(DaySummary.log_date.in_(dates)))} if dates else {}
    days = [
        {"log_date": day, "summary": summaries.get(day), "entries": [entry for entry in entries if entry.log_date == day]}
        for day in dates
    ]
    return LogRangeOut(start=start, end=end, days=days)


@router.get("/days/{day}")
def get_day(day: date, session: SessionDep):
    rows = session.scalars(_active(select(LogEntry)).where(LogEntry.log_date == day).order_by(LogEntry.logged_at, LogEntry.id)).all()
    summary = session.get(DaySummary, day)
    return {"log_date": day, "summary": summary.summary if summary else None, "entries": _entries_out(session, list(rows))}


@router.get("/search", response_model=LogSearchOut)
def search(session: SessionDep, q: Annotated[str, Query(min_length=1, max_length=200)], limit: Annotated[int, Query(ge=1, le=100)] = 50):
    pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = session.scalars(
        _active(select(LogEntry)).where(LogEntry.text.ilike(pattern, escape="\\")).order_by(LogEntry.logged_at.desc(), LogEntry.id).limit(limit)
    ).all()
    return LogSearchOut(entries=_entries_out(session, list(rows)))


# Categories are declared before `/{entry_id}` so the literal path wins.
def _category_out(row: LogCategory) -> LogCategoryOut:
    return LogCategoryOut(id=row.id, name=row.name, description=row.description)


@router.get("/categories", response_model=list[LogCategoryOut])
def list_categories(session: SessionDep):
    return [_category_out(row) for row in session.scalars(select(LogCategory).order_by(LogCategory.sort_order, LogCategory.name))]


@router.post("/categories", status_code=status.HTTP_201_CREATED, response_model=LogCategoryOut)
def create_category(body: LogCategoryCreate, session: SessionDep):
    if session.scalar(select(LogCategory.id).where(LogCategory.name == body.name)):
        raise DomainError("duplicate_category", "A category with that name already exists", 409)
    order = (session.scalar(select(func.max(LogCategory.sort_order))) or 0) + 1
    row = LogCategory(name=body.name, description=body.description.strip(), sort_order=order)
    session.add(row)
    session.commit()
    return _category_out(row)


@router.patch("/categories/{category_id}", response_model=LogCategoryOut)
def update_category(category_id: uuid.UUID, body: LogCategoryPatch, session: SessionDep):
    row = session.get(LogCategory, category_id)
    if row is None:
        raise not_found("Log category", category_id)
    if body.name is not None and body.name != row.name:
        if session.scalar(select(LogCategory.id).where(LogCategory.name == body.name)):
            raise DomainError("duplicate_category", "A category with that name already exists", 409)
        row.name = body.name
    if body.description is not None:
        row.description = body.description.strip()
    session.commit()
    return _category_out(row)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: uuid.UUID, session: SessionDep):
    row = session.get(LogCategory, category_id)
    if row is None:
        raise not_found("Log category", category_id)
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/classify", response_model=ClassifyOut)
def classify(body: ClassifyRequest, session: SessionDep, settings: SettingsDep):
    """Run the local model over one day (default: today) or every day, replacing labels and summaries."""
    from processor.errors import InterpretationError, ModelUnavailableError
    from processor.log_classifier import classify_day
    from processor.config import get_settings as processor_settings

    if body.pending_only:
        days = _pending_days(session, settings)
    elif body.all_days:
        days = list(session.scalars(_active(select(LogEntry.log_date).distinct()).order_by(LogEntry.log_date)))
    else:
        days = [body.date or logical_date(datetime.now(UTC), settings)]
    categories = [
        {"name": row.name, "description": row.description}
        for row in session.scalars(select(LogCategory).order_by(LogCategory.sort_order, LogCategory.name))
    ]
    model_name = processor_settings().ollama_model
    tz = ZoneInfo(settings.user_timezone)
    done: list[date] = []
    failed: list[date] = []
    for day in days:
        rows = session.scalars(_active(select(LogEntry)).where(LogEntry.log_date == day).order_by(LogEntry.logged_at, LogEntry.id)).all()
        if not rows:
            _clear_day(session, day, [])
            session.commit()
            done.append(day)
            continue
        entries = [{"time": row.logged_at.astimezone(tz).strftime("%H:%M"), "text": row.text} for row in rows]
        try:
            result = classify_day(entries, categories)
        except ModelUnavailableError as exc:
            if len(days) == 1 and not body.pending_only:
                raise DomainError("model_unavailable", "The local model is not reachable. Is Ollama running?", 503) from exc
            failed.append(day)
            continue
        except InterpretationError as exc:
            if len(days) == 1 and not body.pending_only:
                raise DomainError("classification_failed", "The local model did not return a usable classification", 502) from exc
            failed.append(day)
            continue
        _clear_day(session, day, [row.id for row in rows])
        for row, labels in zip(rows, result["labels"], strict=True):
            session.add_all(EntryLabel(entry_id=row.id, label=label, model=model_name) for label in labels)
        session.merge(DaySummary(log_date=day, summary=result["summary"], model=model_name))
        session.commit()
        done.append(day)
    return ClassifyOut(classified_days=done, failed_days=failed)


MAX_PENDING_DAYS = 5


def _pending_days(session: Session, settings: Settings) -> list[date]:
    """Days with entries and no summary, oldest first, capped per call.

    A day still in progress is left alone until the local clock reaches `log_auto_classify_hour`, so the scheduled
    pass does not summarise a day that is half logged. Entries added after a day was classified do not make it
    pending again; re-run it by hand.
    """
    now = datetime.now(UTC).astimezone(ZoneInfo(settings.user_timezone))
    today = logical_date(now, settings)
    candidates = _active(select(LogEntry.log_date).distinct()).where(
        LogEntry.log_date <= today,
        ~select(DaySummary.log_date).where(DaySummary.log_date == LogEntry.log_date).exists()
    )
    if now.hour < settings.log_auto_classify_hour or now.hour < settings.day_start_hour:
        candidates = candidates.where(LogEntry.log_date < today)
    return list(session.scalars(candidates.order_by(LogEntry.log_date).limit(MAX_PENDING_DAYS)))


def _clear_day(session: Session, day: date, entry_ids: list[uuid.UUID]) -> None:
    if entry_ids:
        session.execute(delete(EntryLabel).where(EntryLabel.entry_id.in_(entry_ids)))
    else:
        session.execute(delete(DaySummary).where(DaySummary.log_date == day))


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_entry(entry_id: uuid.UUID, session: SessionDep):
    """Archive (hide) an entry. Idempotent; the text stays in the database."""
    row = session.get(LogEntry, entry_id)
    if row is None:
        raise not_found("Log entry", entry_id)
    if row.archived_at is None:
        row.archived_at = datetime.now(UTC)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
