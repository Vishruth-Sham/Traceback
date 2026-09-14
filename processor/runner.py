"""REST-only capture processing runner.

Claims one pending capture from the backend over authenticated loopback
REST, transcribes audio (typed captures skip Whisper), calls `interpret`,
and submits the resulting proposal as one atomic interpretation using the
exact claimed generation/lease. On any adapter or backend failure while the
lease is still valid, it reports the capture failed instead of leaving it
stuck. It never imports backend/database modules and never treats any
value as a filesystem path except the private temporary file it creates
itself to hold downloaded asset bytes.

CLI: `python -m processor.runner` runs once and exits; configure the API URL
and token through environment variables (see `RunnerConfig`), never as
command-line arguments (to avoid leaking the token in process listings).
"""

import argparse
import ipaddress
import json
import logging
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from processor.config import ProcessorSettings, get_settings
from processor.errors import InterpretationError, ModelUnavailableError, ProcessorError, TranscriptionError
from processor.interpretation import interpret, interpret_note_location
from processor.transcription import transcribe

logger = logging.getLogger("processor.runner")

_SUPPORTED_SOURCE_TYPES = {"typed", "audio"}


class RunnerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEBACK_PROCESSOR_", env_file=".env", extra="ignore")

    api_base_url: str = "http://127.0.0.1:8000"
    api_token: str = Field(min_length=1, validation_alias=AliasChoices("API_TOKEN", "TRACEBACK_API_TOKEN"))
    request_timeout_s: float = Field(default=30.0, gt=0)
    lease_seconds: int = Field(default=300, ge=30, le=900)
    client_label: str = "processor"

    @field_validator("api_base_url")
    @classmethod
    def api_must_be_loopback(cls, value: str) -> str:
        parsed = urlparse(value)
        host = parsed.hostname
        try:
            loopback = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or not loopback or parsed.username or parsed.password:
            raise ValueError("backend API URL must be plain HTTP on a loopback address")
        return value


class RestError(ProcessorError):
    """Raised for a non-2xx REST response; carries the parsed error body when available."""

    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"REST call failed with status {status}: {_redact_error_body(body)}")


def _redact_error_body(body: Any) -> Any:
    # Structured domain errors are safe to surface (code/message/details); never echo
    # raw capture/transcript content that might be nested in an unrelated payload shape.
    if isinstance(body, dict) and {"code", "message"} <= body.keys():
        return {k: body[k] for k in ("code", "message", "details") if k in body}
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        if {"code", "message"} <= error.keys():
            return {k: error[k] for k in ("code", "message", "details") if k in error}
    return "<non-domain-error response withheld from logs>"


class RestClient:
    def __init__(self, config: RunnerConfig):
        self._base_url = config.api_base_url.rstrip("/")
        self._token = config.api_token
        self._timeout = config.request_timeout_s
        self._client_label = config.client_label

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-Traceback-Client": self._client_label,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(self, method: str, path: str, *, json_body: dict | None = None, idempotency_key: str | None = None) -> Any:
        url = self._base_url + path
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request = urllib.request.Request(url=url, data=data, headers=self._headers(idempotency_key), method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = None
            raise RestError(exc.code, body) from exc
        except TimeoutError as exc:
            # A read timeout (as opposed to a connect timeout, which urllib
            # wraps in URLError) raises a bare TimeoutError/socket.timeout
            # that would otherwise escape uncaught here, past run_once's
            # ProcessorError handling, and leave the capture stuck
            # "processing" under its lease instead of reported failed.
            raise ModelUnavailableError(f"timed out waiting for backend API at {self._base_url}") from exc
        except urllib.error.URLError as exc:
            raise ModelUnavailableError(f"could not reach backend API at {self._base_url}: {exc}") from exc
        if not raw:
            return None
        return json.loads(raw)

    def list_categories(self) -> list[dict]:
        return self._request("GET", "/api/v1/categories")

    def list_projects(self, limit: int = 50) -> list[dict]:
        result = self._request("GET", f"/api/v1/items?item_type=project&archived=false&limit={limit}")
        return result["items"]

    def list_folders(self, limit: int = 50) -> list[dict]:
        result = self._request("GET", f"/api/v1/items?item_type=folder&archived=false&limit={limit}")
        return result["items"]

    def list_locations(self) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        while True:
            suffix = f"&cursor={cursor}" if cursor else ""
            result = self._request("GET", f"/api/v1/locations?limit=200{suffix}")
            items.extend(result["items"])
            cursor = result.get("next_cursor")
            if not cursor:
                return items

    def list_pending_captures(self, limit: int = 1) -> list[dict]:
        result = self._request("GET", f"/api/v1/captures?state=pending&limit={limit}")
        return result["items"]

    def get_capture(self, capture_id: str) -> dict:
        return self._request("GET", f"/api/v1/captures/{capture_id}")

    def claim_capture(self, capture_id: str, *, expected_generation: int, lease_seconds: int) -> dict:
        return self._request(
            "POST",
            f"/api/v1/captures/{capture_id}/claim",
            json_body={"expected_generation": expected_generation, "lease_seconds": lease_seconds},
        )

    def fail_capture(
        self, capture_id: str, *, expected_generation: int, lease_token: str, error_code: str, error_message: str, transcript: str | None = None
    ) -> dict:
        body = {
            "expected_generation": expected_generation,
            "lease_token": lease_token,
            "error_code": error_code,
            "error_message": error_message,
        }
        if transcript is not None:
            body["transcript"] = transcript
        return self._request("POST", f"/api/v1/captures/{capture_id}/fail", json_body=body)

    def submit_interpretation(
        self,
        capture_id: str,
        *,
        expected_version: int,
        expected_generation: int,
        lease_token: str,
        operations: list[dict],
        transcript: str | None = None,
    ) -> dict:
        body = {
            "expected_version": expected_version,
            "expected_generation": expected_generation,
            "mode": "processor",
            "lease_token": lease_token,
            "items": operations,
        }
        if transcript is not None:
            body["transcript"] = transcript
        return self._request("POST", f"/api/v1/captures/{capture_id}/interpretations", json_body=body)

    def submit_proposal(self, capture_id: str, *, expected_version: int, expected_generation: int, lease_token: str, proposal: dict) -> dict:
        return self._request(
            "POST",
            f"/api/v1/captures/{capture_id}/proposal",
            json_body={
                "expected_version": expected_version,
                "expected_generation": expected_generation,
                "lease_token": lease_token,
                "proposal": proposal,
            },
        )

    def download_asset_content(self, asset_id: str, destination: Path) -> None:
        url = self._base_url + f"/api/v1/assets/{asset_id}/content"
        request = urllib.request.Request(url=url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                with open(destination, "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
        except urllib.error.HTTPError as exc:
            raise RestError(exc.code, None) from exc
        except TimeoutError as exc:
            raise ModelUnavailableError(f"timed out downloading asset {asset_id} from {self._base_url}") from exc
        except urllib.error.URLError as exc:
            raise ModelUnavailableError(f"could not reach backend API at {self._base_url}: {exc}") from exc


def _lease_still_valid(lease_expires_at: str) -> bool:
    expires = datetime.fromisoformat(lease_expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def _proposal_context(capture: dict, categories: list[dict], projects: list[dict], folders: list[dict]) -> dict[str, Any]:
    return {
        "captured_at": capture.get("captured_at"),
        "source_timezone": capture.get("source_timezone"),
        "source_date": capture.get("source_date"),
        "processing_profile": (capture.get("metadata") or {}).get("processing_profile", "general"),
        "categories": [{"id": c["id"], "slug": c["slug"], "name": c["name"]} for c in categories],
        "projects": [{"id": p["id"], "title": p["title"]} for p in projects],
        "folders": [{"id": f["id"], "title": f["title"]} for f in folders],
    }


def _build_create_operation(item: dict, *, projects_by_id: dict[str, dict], folders_by_id: dict[str, dict]) -> dict:
    """Split one proposed item into a `{kind, item, project_id?, folder_id?}` interpretation
    operation, looking up the chosen container's current version (the model only knows its
    id, never its version). A container the model named that has since disappeared from our
    freshly-fetched list falls back to unplaced (Inbox) rather than submitting a stale/guessed
    version, since `interpret()` already validated the id against that same list.
    """
    project_id = item.get("project_id")
    folder_id = item.get("folder_id")
    fields = {k: item[k] for k in ("item_type", "title", "content_md", "due_date", "due_time", "due_timezone") if k in item}
    operation: dict[str, Any] = {"kind": "create", "item": {**fields, "category_id": item.get("category_id")}}
    if project_id and project_id in projects_by_id:
        operation["item"]["category_id"] = None
        operation["project_id"] = project_id
        operation["project_expected_version"] = projects_by_id[project_id]["version"]
    elif folder_id and folder_id in folders_by_id:
        operation["item"]["category_id"] = None
        operation["folder_id"] = folder_id
        operation["folder_expected_version"] = folders_by_id[folder_id]["version"]
    return operation


def _best_effort_fail(
    rest: RestClient, capture_id: str, *, expected_generation: int, lease_token: str, lease_expires_at: str, error_code: str, error_message: str, transcript: str | None
) -> None:
    if not _lease_still_valid(lease_expires_at):
        logger.warning("capture %s: lease already expired, skipping /fail report (%s)", capture_id, error_code)
        return
    try:
        rest.fail_capture(
            capture_id,
            expected_generation=expected_generation,
            lease_token=lease_token,
            error_code=error_code,
            error_message=error_message,
            transcript=transcript,
        )
        logger.info("capture %s: reported failed (%s)", capture_id, error_code)
    except ProcessorError as exc:
        # The lease/generation may already be stale (e.g. a concurrent manual resolution);
        # nothing more this runner can safely do.
        logger.warning("capture %s: could not report failure (%s): %s", capture_id, error_code, exc)


def run_once(*, rest: RestClient, config: RunnerConfig, processor_settings: ProcessorSettings | None = None) -> dict[str, Any] | None:
    """Process at most one pending capture. Returns a small status dict, or None if idle."""
    processor_settings = processor_settings or get_settings()

    pending = rest.list_pending_captures(limit=1)
    if not pending:
        logger.info("no pending captures")
        return None

    summary = pending[0]
    capture_id = summary["id"]
    categories = rest.list_categories()
    projects = rest.list_projects()
    folders = rest.list_folders()

    try:
        claim = rest.claim_capture(
            capture_id, expected_generation=summary["processing"]["generation"], lease_seconds=config.lease_seconds
        )
    except RestError as exc:
        logger.info("capture %s: could not claim (%s)", capture_id, exc)
        return {"capture_id": capture_id, "status": "claim_conflict"}
    except ModelUnavailableError as exc:
        # No lease was ever acquired, so the capture is untouched (still
        # "pending"); report a clean status instead of letting this escape
        # main() as an unhandled crash.
        logger.warning("capture %s: backend unavailable during claim (%s)", capture_id, exc)
        return {"capture_id": capture_id, "status": "backend_unavailable"}

    lease_token = str(claim["lease_token"])
    generation = claim["generation"]
    lease_expires_at = claim["lease_expires_at"]
    transcript: str | None = None

    try:
        capture = rest.get_capture(capture_id)
        source_type = capture["source_type"]
        if source_type == "typed":
            text = capture["raw_text"]
            if not text or not text.strip():
                raise ProcessorError("typed capture has no raw_text")
        elif source_type == "audio":
            asset_ids = capture["asset_ids"]
            if not asset_ids:
                raise ProcessorError("audio capture has no attached asset")
            with tempfile.TemporaryDirectory(prefix="traceback-processor-audio-") as tmp_dir:
                audio_path = Path(tmp_dir) / "capture-audio"
                rest.download_asset_content(str(asset_ids[0]), audio_path)
                transcript = transcribe(audio_path, settings=processor_settings)
            text = transcript
        else:
            raise ProcessorError(f"unsupported source_type for processor runner: {source_type}")

        context = _proposal_context(capture, categories, projects, folders)
        if context["processing_profile"] == "note_quick_add":
            locations = rest.list_locations()
            corrections = capture.get("corrections") or {}
            context.update(
                locations=locations,
                supplied_title=corrections.get("supplied_title", (capture.get("metadata") or {}).get("supplied_title")),
                placement_hint=corrections.get("placement_hint", (capture.get("metadata") or {}).get("placement_hint")),
            )
            text = corrections.get("note_text", text)
            proposal = interpret_note_location(text, context, settings=processor_settings)
            rest.submit_proposal(
                capture_id,
                expected_version=capture["version"],
                expected_generation=generation,
                lease_token=lease_token,
                proposal=proposal,
            )
            logger.info("capture %s: submitted note proposal", capture_id)
            return {"capture_id": capture_id, "status": "awaiting_review", "item_count": 0}
        proposal = interpret(text, context, settings=processor_settings)
        items = proposal["items"]
        projects_by_id = {p["id"]: p for p in projects}
        folders_by_id = {f["id"]: f for f in folders}
        operations = [_build_create_operation(item, projects_by_id=projects_by_id, folders_by_id=folders_by_id) for item in items]

        rest.submit_interpretation(
            capture_id,
            expected_version=capture["version"],
            expected_generation=generation,
            lease_token=lease_token,
            operations=operations,
            transcript=transcript,
        )
        logger.info("capture %s: interpreted into %d item(s)", capture_id, len(items))
        return {"capture_id": capture_id, "status": "interpreted", "item_count": len(items)}

    except (TranscriptionError, ModelUnavailableError, InterpretationError, ProcessorError, RestError) as exc:
        error_code = type(exc).__name__
        logger.error("capture %s: processing failed (%s)", capture_id, error_code)
        _best_effort_fail(
            rest,
            capture_id,
            expected_generation=generation,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            error_code=error_code,
            error_message=str(exc)[:2000],
            transcript=transcript,
        )
        return {"capture_id": capture_id, "status": "failed", "error_code": error_code}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()  # no arguments accepted; configuration is env-only

    config = RunnerConfig()
    rest = RestClient(config)
    result = run_once(rest=rest, config=config)
    print(json.dumps(result or {"status": "idle"}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
