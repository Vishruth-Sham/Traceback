"""insert_note_image: path safety, placement, ordering, and partial failure (fake REST client, real files)."""

import json
import os
import uuid

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from traceback_mcp import config
from traceback_mcp.rest_client import RestError
from traceback_mcp.runtime import set_client
from traceback_mcp.server import LOCAL_ONLY_TOOLS, build_server
from traceback_mcp.tools import assets

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
NOTE_ID = uuid.uuid4()


class FakeClient:
    def __init__(self, content="First paragraph.\n\nSecond paragraph.\n\nThird.", item_type="note", fail=None):
        self.note = {"id": str(NOTE_ID), "item_type": item_type, "version": 3, "content_md": content}
        self.fail = fail or {}
        self.calls = []
        self.uploaded = None

    def _maybe_fail(self, step):
        if step in self.fail:
            raise self.fail[step]

    def get_item(self, item_id):
        self.calls.append("get_item")
        return dict(self.note)

    def upload_asset(self, stream, *, size, filename, content_type):
        self.calls.append("upload")
        self._maybe_fail("upload")
        self.uploaded = (stream.read(), size, filename, content_type)
        return {"id": "asset-1", "version": 1}

    def link_item_asset(self, item_id, asset_id, body):
        self.calls.append("link")
        self._maybe_fail("link")
        assert body == {"expected_version": 3}
        return {"id": item_id, "version": 4}

    def update_item(self, item_id, body, *, idempotency_key):
        self.calls.append("update")
        self._maybe_fail("update")
        assert body["expected_version"] == 4
        self.updated = body["content_md"]
        return {"id": item_id, "version": 5}

    def unlink_item_asset(self, item_id, asset_id, body):
        self.calls.append("unlink")
        return {}

    def archive_asset(self, asset_id, body):
        self.calls.append("archive")
        return {}


@pytest.fixture
def images(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("TRACEBACK_API_TOKEN", "t")
    monkeypatch.setenv("TRACEBACK_MCP_IMAGE_IMPORT_DIRS", str(allowed))
    config.get_settings.cache_clear()
    yield allowed
    config.get_settings.cache_clear()
    set_client(None)


def use(client):
    set_client(client)
    return client


def error_code(excinfo):
    return json.loads(str(excinfo.value))["code"]


def put(directory, name="pic.png", data=PNG):
    path = directory / name
    path.write_bytes(data)
    return str(path)


def test_appends_by_default_and_streams_bytes(images):
    fake = use(FakeClient())
    result = assets.insert_note_image(NOTE_ID, put(images), 3)
    assert result == {"note_id": str(NOTE_ID), "version": 5, "asset_id": "asset-1",
                      "markdown": "![pic.png](/api/v1/assets/asset-1/content)"}
    assert fake.updated.endswith("Third.\n\n![pic.png](/api/v1/assets/asset-1/content)\n")
    assert fake.uploaded == (PNG, len(PNG), "pic.png", "image/png")
    assert fake.calls == ["get_item", "upload", "link", "update"]


def test_after_text_inserts_after_that_paragraph_and_escapes_alt(images):
    fake = use(FakeClient())
    assets.insert_note_image(NOTE_ID, put(images), 3, alt_text="a [b]\\c", after_text="First")
    assert fake.updated == "First paragraph.\n\n![a  b  c](/api/v1/assets/asset-1/content)\n\nSecond paragraph.\n\nThird."


@pytest.mark.parametrize("after_text,code", [("paragraph", "ambiguous_placement"), ("missing", "placement_not_found")])
def test_placement_errors_happen_before_upload(images, after_text, code):
    fake = use(FakeClient())
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3, after_text=after_text)
    assert error_code(exc) == code
    assert "upload" not in fake.calls


def test_stale_version_and_non_note_rejected_before_upload(images):
    fake = use(FakeClient())
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 2)
    assert error_code(exc) == "version_conflict"
    use(FakeClient(item_type="task"))
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3)
    assert error_code(exc) == "invalid_input"
    assert "upload" not in fake.calls


def test_refuses_when_no_directory_configured(images, monkeypatch):
    monkeypatch.setenv("TRACEBACK_MCP_IMAGE_IMPORT_DIRS", "")
    config.get_settings.cache_clear()
    use(FakeClient())
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3)
    assert error_code(exc) == "image_import_not_configured"


@pytest.mark.parametrize("make", ["outside", "traversal", "symlink_file", "symlink_dir", "relative", "directory", "empty", "big", "text", "fifo"])
def test_unsafe_or_invalid_files_are_rejected_without_upload(images, tmp_path, make):
    fake = use(FakeClient())
    outside = tmp_path / "outside"
    outside.mkdir()
    real = put(images)
    if make == "outside":
        path = put(outside)
    elif make == "traversal":
        path = str(images / ".." / "outside" / "x.png")
        put(outside, "x.png")
    elif make == "symlink_file":
        path = str(images / "link.png")
        os.symlink(put(outside), path)
    elif make == "symlink_dir":
        os.symlink(outside, images / "sub")
        put(outside, "in.png")
        path = str(images / "sub" / "in.png")
    elif make == "relative":
        path = "pic.png"
    elif make == "directory":
        (images / "d").mkdir()
        path = str(images / "d")
    elif make == "empty":
        path = put(images, "e.png", b"")
    elif make == "big":
        path = put(images, "big.png", PNG + b"\x00" * (20 * 1024 * 1024))
    elif make == "text":
        path = put(images, "fake.png", b"<svg></svg>")
    elif make == "fifo":
        path = str(images / "pipe.png")
        os.mkfifo(path)
    assert real
    with pytest.raises(ToolError):
        assets.insert_note_image(NOTE_ID, path, 3)
    assert "upload" not in fake.calls


@pytest.mark.parametrize("name,data,mime", [
    ("a.bin", b"\xff\xd8\xff\xe0" + b"0" * 12, "image/jpeg"),
    ("b.png", b"GIF89a" + b"0" * 12, "image/gif"),
    ("c.jpg", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    ("d.png", b"\x00\x00\x00\x1cftypavif" + b"0" * 12, "image/avif"),
])
def test_type_comes_from_content_not_extension(images, name, data, mime):
    fake = use(FakeClient())
    assets.insert_note_image(NOTE_ID, put(images, name, data), 3)
    assert fake.uploaded[3] == mime


def test_replacement_by_symlink_after_validation_is_not_followed(images, tmp_path, monkeypatch):
    from traceback_mcp import image_files

    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG)
    path = put(images)
    original = image_files._relative_to_allowed

    def swap(p, allowed):
        result = original(p, allowed)
        os.unlink(path)
        os.symlink(secret, path)
        return result

    monkeypatch.setattr(image_files, "_relative_to_allowed", swap)
    use(FakeClient())
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, path, 3)
    assert error_code(exc) == "invalid_image_path"


def test_link_conflict_archives_orphan_asset(images):
    fake = use(FakeClient(fail={"link": RestError(409, "version_conflict", "stale", {})}))
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3)
    body = json.loads(str(exc.value))
    assert body["code"] == "partial_failure"
    assert body["details"]["cause"]["code"] == "version_conflict"
    assert body["details"] | {"archived": True} == body["details"]
    assert fake.calls[-1] == "archive" and "update" not in fake.calls


def test_patch_failure_unlinks_and_archives(images):
    fake = use(FakeClient(fail={"update": RestError(409, "version_conflict", "stale", {})}))
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3)
    details = json.loads(str(exc.value))["details"]
    assert details["failed_step"] == "update_note" and details["linked"] is False and details["archived"] is True
    assert fake.calls[-2:] == ["unlink", "archive"]


def test_upload_failure_propagates_as_structured_error(images):
    use(FakeClient(fail={"upload": RestError(413, "upload_too_large", "big", {})}))
    with pytest.raises(ToolError) as exc:
        assets.insert_note_image(NOTE_ID, put(images), 3)
    assert error_code(exc) == "upload_too_large"


def test_registered_locally_and_absent_from_remote_catalog(images):
    import asyncio

    local = {t.name for t in asyncio.run(build_server().list_tools())}
    remote = {t.name for t in asyncio.run(build_server(local=False).list_tools())}
    assert LOCAL_ONLY_TOOLS == {"insert_note_image"}
    assert "insert_note_image" in local and "insert_note_image" not in remote
    assert remote == local - LOCAL_ONLY_TOOLS
