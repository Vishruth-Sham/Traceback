"""A thin authenticated HTTP client for the Traceback loopback REST API.

Stdlib-only (mirrors `processor.runner.RestClient`) so the adapter carries
no extra runtime dependency. This module never imports backend/database
code and never opens a socket to anything but the configured loopback
`api_base_url`. Errors distinguish a structured domain error (from the
REST error envelope) from a generic HTTP failure, a connection timeout,
and the backend being unreachable entirely; a successful response whose
body is not valid JSON is also reported as a structured error rather than
letting a raw `json.JSONDecodeError` escape as an unhandled adapter crash.
"""

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

from traceback_mcp.config import McpSettings


class RestError(Exception):
    """A structured or generic HTTP failure returned by the REST API."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any]):
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")


class BackendUnavailableError(Exception):
    """The backend could not be reached at all (connection refused/timeout/DNS)."""


class RestClient:
    def __init__(self, settings: McpSettings):
        self._base_url = settings.api_base_url.rstrip("/")
        self._token = settings.api_token
        self._timeout = settings.request_timeout_s
        self._client_label = settings.client_label

    def _headers(self, idempotency_key: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-Traceback-Client": self._client_label,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        url = self._base_url + path
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                url += "?" + urlencode(filtered, doseq=True)
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request = urllib.request.Request(url=url, data=data, headers=self._headers(idempotency_key), method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            raise _rest_error_from_body(status, raw) from exc
        except TimeoutError as exc:
            # A read timeout (as opposed to a connect timeout, which urllib
            # wraps in URLError) raises a bare TimeoutError/socket.timeout
            # that would otherwise propagate uncaught.
            raise BackendUnavailableError(
                f"timed out waiting for the Traceback API at {self._base_url} (limit {self._timeout}s)"
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendUnavailableError(
                f"could not reach the Traceback API at {self._base_url}: {exc.reason}"
            ) from exc
        if status == 204 or not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            # A 2xx/204-adjacent response whose body is not valid JSON is a
            # backend contract violation, not something to leak raw bytes
            # from into a ToolError message.
            raise RestError(
                status, "invalid_response", "The Traceback API returned a response that was not valid JSON", {}
            ) from exc

    # --- categories / items / tasks -------------------------------------------------

    def list_categories(self) -> list[dict]:
        return self.request("GET", "/api/v1/categories")

    def list_items(self, **params: Any) -> dict:
        return self.request("GET", "/api/v1/items", query=params)

    def get_item(self, item_id: str) -> dict:
        return self.request("GET", f"/api/v1/items/{item_id}")

    def create_item(self, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", "/api/v1/items", json_body=body, idempotency_key=idempotency_key)

    def update_item(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("PATCH", f"/api/v1/items/{item_id}", json_body=body, idempotency_key=idempotency_key)

    def append_item(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/append", json_body=body, idempotency_key=idempotency_key)

    def move_item(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/move", json_body=body, idempotency_key=idempotency_key)

    def archive_item(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/archive", json_body=body, idempotency_key=idempotency_key)

    def restore_item(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/restore", json_body=body, idempotency_key=idempotency_key)

    def delete_item(self, item_id: str, *, expected_version: int, confirm: bool, idempotency_key: str | None) -> None:
        return self.request(
            "DELETE",
            f"/api/v1/items/{item_id}",
            query={"expected_version": expected_version, "confirm": confirm},
            idempotency_key=idempotency_key,
        )

    def list_inbox(self, **params: Any) -> dict:
        return self.request("GET", "/api/v1/inbox", query=params)

    def get_item_history(self, item_id: str, **params: Any) -> dict:
        return self.request("GET", f"/api/v1/items/{item_id}/history", query=params)

    def undo_action(self, action_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/actions/{action_id}/undo", json_body=body, idempotency_key=idempotency_key)

    # --- tasks ------------------------------------------------------------------------

    def list_tasks(self, **params: Any) -> dict:
        return self.request("GET", "/api/v1/tasks", query=params)

    def complete_task(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/tasks/{item_id}/complete", json_body=body, idempotency_key=idempotency_key)

    def reopen_task(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/tasks/{item_id}/reopen", json_body=body, idempotency_key=idempotency_key)

    # --- relations ----------------------------------------------------------------------

    def create_relation(self, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", "/api/v1/relations", json_body=body, idempotency_key=idempotency_key)

    def delete_relation(self, relation_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("DELETE", f"/api/v1/relations/{relation_id}", json_body=body, idempotency_key=idempotency_key)

    # --- captures -----------------------------------------------------------------------

    def create_capture(self, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", "/api/v1/captures", json_body=body, idempotency_key=idempotency_key)

    def list_captures(self, **params: Any) -> dict:
        return self.request("GET", "/api/v1/captures", query=params)

    def get_capture(self, capture_id: str) -> dict:
        return self.request("GET", f"/api/v1/captures/{capture_id}")

    def correct_capture(self, capture_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/captures/{capture_id}/corrections", json_body=body, idempotency_key=idempotency_key)

    def archive_capture(self, capture_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/captures/{capture_id}/archive", json_body=body, idempotency_key=idempotency_key)

    def restore_capture(self, capture_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/captures/{capture_id}/restore", json_body=body, idempotency_key=idempotency_key)

    def delete_capture(self, capture_id: str, *, expected_version: int, confirm: bool, idempotency_key: str | None) -> None:
        return self.request(
            "DELETE",
            f"/api/v1/captures/{capture_id}",
            query={"expected_version": expected_version, "confirm": confirm},
            idempotency_key=idempotency_key,
        )

    def retry_capture(self, capture_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/captures/{capture_id}/retry", json_body=body, idempotency_key=idempotency_key)

    def apply_capture_interpretation(self, capture_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request(
            "POST", f"/api/v1/captures/{capture_id}/interpretations", json_body=body, idempotency_key=idempotency_key
        )

    def get_item_sources(self, item_id: str) -> list[dict]:
        return self.request("GET", f"/api/v1/items/{item_id}/sources")

    def link_item_source(self, item_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/sources", json_body=body, idempotency_key=idempotency_key)

    def unlink_item_source(self, item_id: str, source_id: str, body: dict, *, idempotency_key: str | None) -> dict:
        return self.request(
            "DELETE", f"/api/v1/items/{item_id}/sources/{source_id}", json_body=body, idempotency_key=idempotency_key
        )

    # --- assets (metadata only; no raw bytes ever flow through this client) -----------

    def get_asset(self, asset_id: str) -> dict:
        return self.request("GET", f"/api/v1/assets/{asset_id}")

    def archive_asset(self, asset_id: str, body: dict) -> dict:
        return self.request("POST", f"/api/v1/assets/{asset_id}/archive", json_body=body)

    def restore_asset(self, asset_id: str, body: dict) -> dict:
        return self.request("POST", f"/api/v1/assets/{asset_id}/restore", json_body=body)

    def delete_asset(self, asset_id: str, *, expected_version: int, confirm: bool) -> dict:
        return self.request(
            "DELETE", f"/api/v1/assets/{asset_id}", query={"expected_version": expected_version, "confirm": confirm}
        )

    def link_item_asset(self, item_id: str, asset_id: str, body: dict) -> dict:
        return self.request("POST", f"/api/v1/items/{item_id}/assets/{asset_id}", json_body=body)

    def unlink_item_asset(self, item_id: str, asset_id: str, body: dict) -> dict:
        return self.request("DELETE", f"/api/v1/items/{item_id}/assets/{asset_id}", json_body=body)


def _rest_error_from_body(status: int, raw: bytes) -> RestError:
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and "code" in error and "message" in error:
        return RestError(status, str(error["code"]), str(error["message"]), error.get("details") or {})
    # Do not leak an unrelated/unstructured response body to the model.
    return RestError(status, "http_error", f"Request failed with status {status}", {})
