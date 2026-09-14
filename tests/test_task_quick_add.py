"""Backend coverage for the free-text Tasks quick-add feature.

Exercises the parts of the pipeline that live in the backend: capture
persistence/provenance, atomic interpretation with project/folder placement,
idempotent retry, duplicate prevention, and stale-generation/manual-edit
conflicts. The processor's own parsing (relative dates, project/folder
resolution against context) is covered in tests/test_processor_interpretation.py;
this file assumes a caller (the processor or a manual UI resolution) submits
an already-structured proposal and checks the backend applies it correctly.
"""
from uuid import uuid4


def post_capture(client, **overrides):
    body = {"source_type": "typed", "raw_text": "Email Sarah Friday afternoon about the apartment move", **overrides}
    response = client.post("/api/v1/captures", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def claim(client, capture_id, generation=1):
    response = client.post(f"/api/v1/captures/{capture_id}/claim", json={"expected_generation": generation})
    assert response.status_code == 200, response.text
    return response.json()


def test_typed_capture_preserves_exact_submitted_text_and_provenance(client):
    text = "Email Sarah Friday afternoon about the apartment move"
    capture = post_capture(client, raw_text=text)
    assert capture["raw_text"] == text
    assert capture["processing"]["state"] == "pending"
    assert capture["created_at"]  # server receipt timestamp recorded immediately
    # Visible in Inbox while unresolved, so the input is never silently lost.
    assert capture["id"] in [entry["id"] for entry in client.get("/api/v1/inbox").json()["captures"]]


def test_task_quick_add_frontend_request_shape_is_accepted(client):
    """Regression test for a real outage: `frontend/src/components/TaskQuickAdd.tsx`
    posts `captured_at`/`source_timezone`/`timestamp_origin: "client_supplied"` plus
    `metadata: {"processing_profile": "task_quick_add"}` on every submission. A stale
    server process running code from before `processing_profile` existed on
    `CaptureMetadata` (a `StrictModel`, `extra="forbid"`) rejected every one of these
    requests with 422 `extra_forbidden` — the real root cause of "quick-add doesn't
    reliably become a task" was that mismatch, not prompt/model quality. This posts
    the exact literal shape the frontend sends so a future field rename/removal on
    either side breaks this test immediately instead of silently breaking prod again.
    """
    response = client.post(
        "/api/v1/captures",
        json={
            "source_type": "typed",
            "raw_text": "Email Sarah Friday afternoon about the apartment move",
            "captured_at": "2026-09-14T09:00:00Z",
            "source_timezone": "Asia/Kolkata",
            "timestamp_origin": "client_supplied",
            "metadata": {"processing_profile": "task_quick_add"},
        },
        headers={"Idempotency-Key": "frontend-shape-regression"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["metadata"]["processing_profile"] == "task_quick_add"
    assert body["source_timezone"] == "Asia/Kolkata"
    assert body["timestamp_origin"] == "client_supplied"


def test_task_quick_add_profile_requires_exactly_one_new_task(client):
    capture = post_capture(client, metadata={"processing_profile": "task_quick_add"})
    wrong_type = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "note", "title": "Not a task"}}],
        },
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["error"]["code"] == "invalid_interpretation"

    multiple = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "manual",
            "items": [
                {"kind": "create", "item": {"item_type": "task", "title": "First"}},
                {"kind": "create", "item": {"item_type": "task", "title": "Second"}},
            ],
        },
    )
    assert multiple.status_code == 422
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["resulting_item_ids"] == []


def test_interpretation_places_task_in_project_atomically(client):
    project = client.post("/api/v1/items", json={"item_type": "project", "title": "Apartment Move"}).json()
    capture = post_capture(client)
    claimed = claim(client, capture["id"])
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claimed["lease_token"],
            "items": [
                {
                    "kind": "create",
                    "item": {"item_type": "task", "title": "Email Sarah about the move", "due_date": "2026-09-18"},
                    "project_id": project["id"],
                    "project_expected_version": project["version"],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()["items"][0]
    assert task["category_id"] == client.get("/api/v1/categories").json()[4]["id"]  # Projects category
    assert any(r["relation"] == "part_of" and r["to_item_id"] == project["id"] for r in task["relations"])
    assert capture["id"] in task["source_ids"]
    # The project itself was bumped/versioned by the containment, atomically with the task creation.
    refreshed_project = client.get(f"/api/v1/items/{project['id']}").json()
    assert refreshed_project["version"] == project["version"] + 1


def test_interpretation_places_task_in_folder_and_inherits_category(client):
    categories = client.get("/api/v1/categories").json()
    learning = next(c for c in categories if c["slug"] == "learning")
    folder = client.post(
        "/api/v1/items", json={"item_type": "folder", "title": "Reading list", "category_id": learning["id"]}
    ).json()
    capture = post_capture(client, raw_text="Read the second chapter this weekend")
    claimed = claim(client, capture["id"])
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claimed["lease_token"],
            "items": [
                {
                    "kind": "create",
                    "item": {"item_type": "task", "title": "Read second chapter"},
                    "folder_id": folder["id"],
                    "folder_expected_version": folder["version"],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()["items"][0]
    assert task["category_id"] == learning["id"]
    assert task["placement_state"] == "classified"


def test_interpretation_rejects_category_id_alongside_container(client):
    project = client.post("/api/v1/items", json={"item_type": "project", "title": "P"}).json()
    categories = client.get("/api/v1/categories").json()
    capture = post_capture(client)
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "items": [
                {
                    "kind": "create",
                    "item": {"item_type": "task", "title": "Bad", "category_id": categories[0]["id"]},
                    "project_id": project["id"],
                    "project_expected_version": project["version"],
                }
            ],
        },
    )
    assert response.status_code == 422


def test_interpretation_container_wrong_type_rejected(client):
    note = client.post("/api/v1/items", json={"item_type": "note", "title": "Not a project"}).json()
    capture = post_capture(client)
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "items": [
                {
                    "kind": "create",
                    "item": {"item_type": "task", "title": "x"},
                    "project_id": note["id"],
                    "project_expected_version": note["version"],
                }
            ],
        },
    )
    assert response.status_code == 422
    fresh = client.get(f"/api/v1/captures/{capture['id']}").json()
    assert fresh["resulting_item_ids"] == []
    assert fresh["processing"]["state"] == "pending"


def test_interpretation_stale_container_version_conflicts_without_partial_write(client):
    project = client.post("/api/v1/items", json={"item_type": "project", "title": "P2"}).json()
    # Bump the project so our captured version is now stale.
    client.patch(f"/api/v1/items/{project['id']}", json={"expected_version": 1, "title": "P2 renamed"})
    capture = post_capture(client)
    response = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "items": [
                {
                    "kind": "create",
                    "item": {"item_type": "task", "title": "Should not exist"},
                    "project_id": project["id"],
                    "project_expected_version": 1,
                }
            ],
        },
    )
    assert response.status_code == 409
    fresh = client.get(f"/api/v1/captures/{capture['id']}").json()
    assert fresh["resulting_item_ids"] == []
    assert fresh["processing"]["state"] == "pending"


def test_idempotent_retry_same_key_and_payload_returns_same_result(client):
    capture = post_capture(client)
    claimed = claim(client, capture["id"])
    body = {
        "expected_version": 1,
        "expected_generation": 1,
        "mode": "processor",
        "lease_token": claimed["lease_token"],
        "items": [{"kind": "create", "item": {"item_type": "task", "title": "Idempotent task"}}],
    }
    headers = {"Idempotency-Key": "quick-add-" + capture["id"]}
    first = client.post(f"/api/v1/captures/{capture['id']}/interpretations", json=body, headers=headers)
    second = client.post(f"/api/v1/captures/{capture['id']}/interpretations", json=body, headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    # Exactly one task was created, not two.
    assert len(first.json()["items"]) == 1
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["resulting_item_ids"] == [first.json()["items"][0]["id"]]


def test_stale_generation_after_manual_resolution_is_rejected_not_overwritten(client):
    capture = post_capture(client)
    claimed = claim(client, capture["id"])
    # The user manually resolves the capture first (e.g. through the UI) while a
    # processor still holds a lease from an earlier claim.
    manual = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "task", "title": "Manually written task"}}],
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["capture"]["processing"]["generation"] == 2
    manual_item_id = manual.json()["items"][0]["id"]

    # The delayed processor's interpretation, still carrying the old generation/lease, must conflict.
    stale = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 2,
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claimed["lease_token"],
            "items": [{"kind": "create", "item": {"item_type": "task", "title": "Stale duplicate task"}}],
        },
    )
    assert stale.status_code == 409
    # Exactly the manual task remains linked to this capture; no duplicate was created.
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["resulting_item_ids"] == [manual_item_id]


def test_manual_edit_after_claim_conflicts_a_later_processor_submission(client):
    capture = post_capture(client)
    claimed = claim(client, capture["id"])
    # A manual edit to something unrelated bumps... nothing relevant here; instead simulate a
    # manual archive/restore of the capture itself, which is a version bump a stale processor
    # interpretation must respect.
    archived = client.post(f"/api/v1/captures/{capture['id']}/archive", json={"expected_version": 1})
    assert archived.status_code == 200
    restored = client.post(f"/api/v1/captures/{capture['id']}/restore", json={"expected_version": 2})
    assert restored.status_code == 200
    assert restored.json()["version"] == 3

    stale = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 1,
            "expected_generation": 1,
            "mode": "processor",
            "lease_token": claimed["lease_token"],
            "items": [{"kind": "create", "item": {"item_type": "task", "title": "Should conflict"}}],
        },
    )
    assert stale.status_code == 409
    assert client.get(f"/api/v1/captures/{capture['id']}").json()["resulting_item_ids"] == []


def test_failed_interpretation_keeps_input_visible_for_retry(client):
    text = "Something the model could not parse"
    capture = post_capture(client, raw_text=text)
    claimed = claim(client, capture["id"])
    failed = client.post(
        f"/api/v1/captures/{capture['id']}/fail",
        json={
            "expected_generation": 1,
            "lease_token": claimed["lease_token"],
            "error_code": "InterpretationError",
            "error_message": "model did not return a schema-valid proposal",
        },
    )
    assert failed.status_code == 200
    assert failed.json()["processing"]["state"] == "failed"
    # Still visible/retryable in Inbox; original text never lost.
    inbox = client.get("/api/v1/inbox").json()
    assert capture["id"] in [entry["id"] for entry in inbox["captures"]]
    fresh = client.get(f"/api/v1/captures/{capture['id']}").json()
    assert fresh["raw_text"] == text
    retried = client.post(f"/api/v1/captures/{capture['id']}/retry", json={"expected_version": 2, "expected_generation": 1})
    assert retried.status_code == 200
    assert retried.json()["processing"]["state"] == "pending"
    assert retried.json()["processing"]["generation"] == 2


def test_manual_resolution_of_failed_capture_creates_exactly_one_task(client):
    text = "Ambiguous capture text"
    capture = post_capture(client, raw_text=text)
    claimed = claim(client, capture["id"])
    client.post(
        f"/api/v1/captures/{capture['id']}/fail",
        json={
            "expected_generation": 1,
            "lease_token": claimed["lease_token"],
            "error_code": "InterpretationError",
            "error_message": "ambiguous",
        },
    )
    # Manual resolution (the UI's structured fallback path) applies directly, no model involved.
    manual = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": 2,
            "expected_generation": 1,
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "task", "title": text}}],
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["capture"]["processing"]["state"] == "resolved"
    assert len(manual.json()["items"]) == 1
    assert client.get("/api/v1/inbox").json()["captures"] == [] or capture["id"] not in [
        e["id"] for e in client.get("/api/v1/inbox").json()["captures"]
    ]
