"""Task list/complete/reopen tools."""

import uuid
from typing import Literal

from traceback_mcp.errors import guarded
from traceback_mcp.runtime import get_client
from traceback_mcp.tools.common import bounded_limit


@guarded
def list_tasks(
    status: Literal["open", "completed"] = "open",
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> dict:
    """List tasks. Open tasks sort by due date (overdue first, undated last); completed by latest completion."""
    return get_client().list_tasks(
        status=status,
        category_id=str(category_id) if category_id is not None else None,
        project_id=str(project_id) if project_id is not None else None,
        cursor=cursor,
        limit=bounded_limit(limit),
    )


@guarded
def complete_task(item_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Mark a task completed, setting `completed_at`. Reversible with `reopen_task`."""
    return get_client().complete_task(str(item_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)


@guarded
def reopen_task(item_id: uuid.UUID, expected_version: int, idempotency_key: str | None = None) -> dict:
    """Reopen a completed task, clearing `completed_at`."""
    return get_client().reopen_task(str(item_id), {"expected_version": expected_version}, idempotency_key=idempotency_key)
