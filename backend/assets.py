"""Opaque, reference-aware local assets. Original bytes and observed metadata are immutable."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import AwareDatetime
from sqlalchemy import select

from backend.api import SessionDep, SettingsDep, authenticate
from backend.asset_models import Asset, CaptureAsset, ItemAsset
from backend.config import get_settings
from backend.errors import DomainError, not_found
from backend.schemas import VersionRequest
from backend.services import begin_action, bump, finish_action, get_item, record_revision, require_version, item_snapshot, utcnow

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])


def asset_path(asset: Asset) -> Path:
    # All keys are generated UUIDs, never filenames supplied by a client.
    if asset.storage_key != str(asset.id):
        raise DomainError("invalid_storage_key", "Invalid stored asset key", 500)
    return get_settings().asset_dir.resolve() / asset.storage_key


def get_asset(session, asset_id, *, lock=False):
    statement = select(Asset).where(Asset.id == asset_id)
    if lock:
        statement = statement.with_for_update()
    asset = session.scalar(statement)
    if asset is None:
        raise not_found("asset", asset_id)
    return asset


def asset_out(asset):
    return {column.name: getattr(asset, column.name) for column in Asset.__table__.columns if column.name not in {"storage_key", "cleanup_error"}}


def attach_capture_assets(session, capture_id, asset_ids):
    for asset_id in sorted(set(asset_ids)):
        asset = get_asset(session, asset_id, lock=True)
        if asset.upload_state != "ready" or asset.archived_at:
            raise DomainError("invalid_transition", "Only active, ready assets can be attached", 409)
        session.add(CaptureAsset(capture_id=capture_id, asset_id=asset_id))


@router.post("/assets", status_code=201)
async def upload(request: Request, session: SessionDep, settings: SettingsDep,
                 filename: str = Query(min_length=1, max_length=255),
                 source_created_at: AwareDatetime | None = None,
                 source_modified_at: AwareDatetime | None = None):
    if any(c in filename for c in ("\x00", "\r", "\n")):
        raise DomainError("invalid_input", "Filename contains invalid characters", 422)
    declared = request.headers.get("content-type", "application/octet-stream")
    if len(declared) > 255:
        raise DomainError("invalid_input", "Content type is too long", 422)
    directory = settings.asset_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    asset_id = uuid.uuid4()
    destination = directory / str(asset_id)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            size = 0
            digest = hashlib.sha256()
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise DomainError("upload_too_large", "Upload exceeds the configured size limit", 413)
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            detected = subprocess.run(["/usr/bin/file", "--brief", "--mime-type", str(temporary)], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            detected = "application/octet-stream"
        os.replace(temporary, destination)
        temporary = None
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        asset = Asset(id=asset_id, storage_key=str(asset_id), original_filename=filename,
                      extension=Path(filename).suffix[:32], declared_mime_type=declared,
                      detected_mime_type=detected, byte_size=size, sha256=digest.hexdigest(),
                      source_created_at=source_created_at, source_modified_at=source_modified_at,
                      timestamp_origin="client_supplied" if source_created_at or source_modified_at else None)
        session.add(asset)
        session.commit()
        return asset_out(asset)
    except BaseException:
        session.rollback()
        # Only paths uniquely created for this request are eligible for removal.
        if temporary:
            temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


@router.get("/assets/{asset_id}")
def read_asset(asset_id: uuid.UUID, session: SessionDep):
    asset = get_asset(session, asset_id)
    result = asset_out(asset)
    result["capture_ids"] = list(session.scalars(select(CaptureAsset.capture_id).where(CaptureAsset.asset_id == asset_id)))
    result["item_ids"] = list(session.scalars(select(ItemAsset.item_id).where(ItemAsset.asset_id == asset_id)))
    return result


@router.get("/assets/{asset_id}/content")
def content(asset_id: uuid.UUID, session: SessionDep):
    asset = get_asset(session, asset_id)
    if asset.upload_state != "ready":
        raise DomainError("invalid_transition", "Asset content is unavailable", 409)
    path = asset_path(asset)
    if not path.is_file():
        raise DomainError("asset_unavailable", "Original asset bytes are missing", 503)
    # Only formats that browsers decode as images may be displayed inline.
    # In particular, SVG and HTML must remain downloads on this authenticated origin.
    inline_images = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"}
    is_image = asset.detected_mime_type in inline_images
    return FileResponse(
        path,
        media_type=asset.detected_mime_type if is_image else "application/octet-stream",
        filename=Path(asset.original_filename).name,
        content_disposition_type="inline" if is_image else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.post("/assets/{asset_id}/archive")
def archive(asset_id: uuid.UUID, body: VersionRequest, session: SessionDep):
    asset = get_asset(session, asset_id, lock=True)
    require_version(asset, body.expected_version)
    if asset.archived_at:
        raise DomainError("invalid_transition", "Asset is already archived", 409)
    asset.archived_at = utcnow()
    asset.version += 1
    session.commit()
    return asset_out(asset)


@router.post("/assets/{asset_id}/restore")
def restore(asset_id: uuid.UUID, body: VersionRequest, session: SessionDep):
    asset = get_asset(session, asset_id, lock=True)
    require_version(asset, body.expected_version)
    if not asset.archived_at or asset.upload_state != "ready":
        raise DomainError("invalid_transition", "Only archived original assets can be restored", 409)
    asset.archived_at = None
    asset.version += 1
    session.commit()
    return asset_out(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: uuid.UUID, session: SessionDep, expected_version: int = Query(ge=1), confirm: bool = False):
    asset = get_asset(session, asset_id, lock=True)
    require_version(asset, expected_version)
    if not confirm or not asset.archived_at:
        raise DomainError("invalid_transition", "Archive and explicitly confirm before deleting", 409)
    if session.scalar(select(CaptureAsset.asset_id).where(CaptureAsset.asset_id == asset_id).limit(1)) or session.scalar(select(ItemAsset.asset_id).where(ItemAsset.asset_id == asset_id).limit(1)):
        raise DomainError("linked_asset_conflict", "Asset is still referenced by captures or items", 409)
    asset.upload_state = "cleanup_pending"
    session.commit()
    # Pending state fences new links; retry this same explicit deletion if cleanup fails.
    asset = get_asset(session, asset_id, lock=True)
    try:
        asset_path(asset).unlink(missing_ok=True)
    except OSError:
        asset.cleanup_error = "Could not remove original bytes; retry deletion"
        session.commit()
        return {"id": asset_id, "state": "cleanup_pending"}
    session.delete(asset)
    session.commit()
    return {"id": asset_id, "state": "deleted"}


@router.post("/items/{item_id}/assets/{asset_id}")
def link_asset(item_id: uuid.UUID, asset_id: uuid.UUID, body: VersionRequest, session: SessionDep):
    item = get_item(session, item_id, lock=True)
    require_version(item, body.expected_version)
    asset = get_asset(session, asset_id, lock=True)
    if asset.upload_state != "ready" or asset.archived_at:
        raise DomainError("invalid_transition", "Only active assets can be linked", 409)
    if session.get(ItemAsset, (item_id, asset_id)):
        raise DomainError("link_exists", "Asset is already linked", 409)
    action, _ = begin_action(session, "link_asset", {"item_id": str(item_id), "asset_id": str(asset_id)}, None)
    before = item_snapshot(session, item)
    session.add(ItemAsset(item_id=item_id, asset_id=asset_id))
    bump(item)
    record_revision(session, action, item, before)
    finish_action(action, {"id": str(item_id), "version": item.version, "action_id": str(action.id)})
    session.commit()
    return {"id": item_id, "version": item.version, "action_id": action.id}


@router.delete("/items/{item_id}/assets/{asset_id}")
def unlink_asset(item_id: uuid.UUID, asset_id: uuid.UUID, body: VersionRequest, session: SessionDep):
    item = get_item(session, item_id, lock=True)
    require_version(item, body.expected_version)
    link = session.get(ItemAsset, (item_id, asset_id))
    if not link:
        raise not_found("asset link", asset_id)
    action, _ = begin_action(session, "unlink_asset", {"item_id": str(item_id), "asset_id": str(asset_id)}, None)
    before = item_snapshot(session, item)
    session.delete(link)
    bump(item)
    record_revision(session, action, item, before)
    finish_action(action, {"id": str(item_id), "version": item.version, "action_id": str(action.id)})
    session.commit()
    return {"id": item_id, "version": item.version, "action_id": action.id}
