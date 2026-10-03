from datetime import UTC, datetime
import base64
from uuid import uuid4


def post_capture(client, **overrides):
    body = {"source_type": "typed", "raw_text": "Original words", **overrides}
    response = client.post("/api/v1/captures", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_capture_preserves_original_and_timestamp_kinds(client):
    capture = post_capture(
        client,
        captured_at="2020-02-03T10:20:30+05:30",
        source_date="2020-02-03",
        source_timezone="Asia/Kolkata",
        timestamp_origin="user_supplied",
        metadata={"timestamp_precision": "date", "client_app": "test"},
    )
    assert capture["raw_text"] == "Original words"
    assert capture["created_at"] != capture["captured_at"]
    corrected = client.post(
        f"/api/v1/captures/{capture['id']}/corrections",
        json={"expected_version": 1, "description": "Corrected context", "note": "Original remains immutable"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["raw_text"] == "Original words"
    assert corrected.json()["corrections"]["description"] == "Corrected context"
    invalid = client.post("/api/v1/captures", json={"source_type": "typed", "raw_text": "x", "captured_at": "2020-01-01T00:00:00"})
    assert invalid.status_code == 422


def test_processing_failure_retry_and_stale_lease(client):
    capture = post_capture(client)
    assert capture["id"] in [entry["id"] for entry in client.get("/api/v1/inbox").json()["captures"]]
    claim = client.post(f"/api/v1/captures/{capture['id']}/claim", json={"expected_generation": 1, "lease_seconds": 300})
    assert claim.status_code == 200, claim.text
    lease = claim.json()
    failed = client.post(
        f"/api/v1/captures/{capture['id']}/fail",
        json={"expected_generation": 1, "lease_token": lease["lease_token"], "error_code": "model_unavailable", "error_message": "Ollama stopped"},
    )
    assert failed.status_code == 200 and failed.json()["processing"]["state"] == "failed"
    retry = client.post(
        f"/api/v1/captures/{capture['id']}/retry",
        json={"expected_version": 2, "expected_generation": 1},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["processing"]["generation"] == 2
    stale = client.post(
        f"/api/v1/captures/{capture['id']}/fail",
        json={"expected_generation": 1, "lease_token": lease["lease_token"], "error_code": "late", "error_message": "late worker"},
    )
    assert stale.status_code == 409
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["processing"]["state"] == "pending"


def test_manual_interpretation_is_atomic_and_fences_processor(client):
    capture = post_capture(client, raw_text="Create a task and keep this safe")
    claimed = client.post(f"/api/v1/captures/{capture['id']}/claim", json={"expected_generation": 1}).json()
    interpretation = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "task", "title": "Safe task", "due_date": "2026-09-15"}}],
        },
    )
    assert interpretation.status_code == 200, interpretation.text
    result = interpretation.json()
    item = result["items"][0]
    assert result["capture"]["processing"]["state"] == "resolved"
    assert result["capture"]["processing"]["generation"] == 2
    assert item["id"] in result["capture"]["resulting_item_ids"]
    assert capture["id"] not in [entry["id"] for entry in client.get("/api/v1/inbox").json()["captures"]]
    assert capture["id"] in client.get(f"/api/v1/items/{item['id']}").json()["source_ids"]
    late = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={"expected_version": 1, "expected_generation": 1, "mode": "processor", "lease_token": claimed["lease_token"],
              "items": [{"kind": "create", "item": {"item_type": "note", "title": "Duplicate"}}]},
    )
    assert late.status_code == 409
    assert len(client.get("/api/v1/items", params={"q": "Duplicate"}).json()["items"]) == 0


def test_interpretation_rolls_back_all_items_on_invalid_append(client):
    capture = post_capture(client)
    missing = uuid4()
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={"expected_version": 1, "expected_generation": 1, "items": [
            {"kind": "create", "item": {"item_type": "note", "title": "Must roll back"}},
            {"kind": "append", "item_id": str(missing), "expected_version": 1, "content_md": "no"},
        ]},
    )
    assert response.status_code == 404
    assert client.get("/api/v1/items", params={"q": "Must roll back"}).json()["items"] == []
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["processing"]["state"] == "pending"


def test_capture_interpretation_cannot_be_partially_undone(client):
    item = client.post("/api/v1/items", json={"item_type": "note", "title": "Existing", "content_md": "Before"}).json()
    capture = post_capture(client)
    interpreted = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "items": [{"kind": "append", "item_id": item["id"], "expected_version": 1, "content_md": "After"}],
        },
    )
    assert interpreted.status_code == 200, interpreted.text
    result = interpreted.json()
    undo = client.post(
        f"/api/v1/actions/{result['action_id']}/undo",
        json={"expected_versions": {item["id"]: result["items"][0]["version"]}},
    )
    assert undo.status_code == 409
    assert undo.json()["error"]["code"] == "undo_unavailable"
    refreshed = client.get(f"/api/v1/items/{item['id']}").json()
    assert refreshed["content_md"] == "Before\n\nAfter"
    assert capture["id"] in refreshed["source_ids"]


def test_asset_bytes_metadata_links_and_reference_aware_delete(client):
    old_time = "2019-04-05T06:07:08+00:00"
    payload = b"Traceback original attachment\n"
    uploaded = client.post(
        "/api/v1/assets",
        params={"filename": "../original note.txt", "source_modified_at": old_time},
        content=payload,
        headers={"Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert asset["original_filename"] == "../original note.txt"
    assert asset["byte_size"] == len(payload)
    assert asset["uploaded_at"] != asset["source_modified_at"]
    content = client.get(f"/api/v1/assets/{asset['id']}/content")
    assert content.status_code == 200 and content.content == payload
    assert content.headers["content-type"].startswith("application/octet-stream")
    capture = post_capture(client, source_type="file", raw_text=None, asset_ids=[asset["id"]])
    archived = client.post(f"/api/v1/assets/{asset['id']}/archive", json={"expected_version": 1}).json()
    blocked = client.delete(f"/api/v1/assets/{asset['id']}", params={"expected_version": archived["version"], "confirm": True})
    assert blocked.status_code == 409
    capture = client.post(f"/api/v1/captures/{capture['id']}/archive", json={"expected_version": 1}).json()
    # Capture owns the reference; permanent capture deletion removes only the link, not original bytes.
    deleted_capture = client.delete(f"/api/v1/captures/{capture['id']}", params={"expected_version": capture["version"], "confirm": True})
    assert deleted_capture.status_code == 204, deleted_capture.text
    deleted_asset = client.delete(f"/api/v1/assets/{asset['id']}", params={"expected_version": archived["version"], "confirm": True})
    assert deleted_asset.status_code == 200 and deleted_asset.json()["state"] == "deleted"
    assert client.get(f"/api/v1/assets/{asset['id']}").status_code == 404


def test_note_image_renders_inline_but_svg_downloads(client):
    note = client.post("/api/v1/items", json={"item_type": "note", "title": "Illustrated"}).json()
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
    uploaded = client.post("/api/v1/assets?filename=picture.png", content=png, headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 201, uploaded.text
    image = uploaded.json()
    assert image["detected_mime_type"] == "image/png"
    linked = client.post(f"/api/v1/items/{note['id']}/assets/{image['id']}", json={"expected_version": note["version"]})
    assert linked.status_code == 200, linked.text
    assert image["id"] in client.get(f"/api/v1/items/{note['id']}").json()["asset_ids"]
    content = client.get(f"/api/v1/assets/{image['id']}/content")
    assert content.content == png
    assert content.headers["content-type"].startswith("image/png")
    assert content.headers["content-disposition"].startswith("inline")
    assert content.headers["x-content-type-options"] == "nosniff"

    svg = client.post("/api/v1/assets?filename=diagram.svg", content=b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', headers={"Content-Type": "image/svg+xml"}).json()
    svg_content = client.get(f"/api/v1/assets/{svg['id']}/content")
    assert svg_content.headers["content-type"].startswith("application/octet-stream")
    assert svg_content.headers["content-disposition"].startswith("attachment")


def test_capture_delete_blocked_by_source_link(client):
    capture = post_capture(client)
    result = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={"expected_version": 1, "expected_generation": 1,
              "items": [{"kind": "create", "item": {"item_type": "note", "title": "Sourced note"}}]},
    ).json()
    archived = client.post(f"/api/v1/captures/{capture['id']}/archive", json={"expected_version": result["capture"]["version"]}).json()
    blocked = client.delete(f"/api/v1/captures/{capture['id']}", params={"expected_version": archived["version"], "confirm": True})
    assert blocked.status_code == 409
