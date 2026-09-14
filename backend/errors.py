from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def not_found(resource: str, resource_id: object) -> DomainError:
    return DomainError("not_found", f"{resource} was not found", 404, {"id": str(resource_id)})


def conflict(expected: int, actual: int, item_id: object) -> DomainError:
    return DomainError(
        "version_conflict",
        "The item changed since it was read",
        409,
        {"id": str(item_id), "expected_version": expected, "actual_version": actual},
    )
