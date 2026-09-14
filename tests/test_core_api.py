"""Acceptance tests against the real PostgreSQL API (no SQLite substitute)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4


def create(client, kind="note", **fields):
    response = client.post("/api/v1/items", json={"item_type": kind, "title": str(uuid4()), **fields})
    assert response.status_code == 201, response.text
    return response.json()


def mutate(client, item, operation, **fields):
    response = client.post(f"/api/v1/items/{item['id']}/{operation}", json={"expected_version": item["version"], **fields})
    assert response.status_code == 200, response.text
    return response.json()


def test_categories_and_canonical_task_lifecycle(client):
    categories = client.get("/api/v1/categories").json()
    if isinstance(categories, dict):
        categories = categories["items"]
    assert [c["name"] for c in categories] == ["Health & Food", "Personal Growth", "Books", "Learning", "Projects", "Other"]
    task = create(client, "task", title="Read database chapter")
    assert task["placement_state"] == "inbox"
    assert task["category_id"] is None
    assert task["due_date"] is None
    completed = client.post(f"/api/v1/tasks/{task['id']}/complete", json={"expected_version": task["version"]}).json()
    assert completed["id"] == task["id"]
    assert completed["status"] == "completed" and completed["completed_at"]
    assert task["id"] not in [x["id"] for x in client.get("/api/v1/tasks").json()["items"]]
    assert task["id"] in [x["id"] for x in client.get("/api/v1/tasks?status=completed").json()["items"]]
    archived = mutate(client, completed, "archive")
    restored = mutate(client, archived, "restore")
    assert restored["status"] == "completed"
    assert restored["completed_at"] == completed["completed_at"]
    reopened = client.post(f"/api/v1/tasks/{task['id']}/reopen", json={"expected_version": restored["version"]}).json()
    assert reopened["status"] == "open" and reopened["completed_at"] is None


def test_patch_validation_and_stale_write(client):
    item = create(client, title="Original", content_md="Keep me")
    url = f"/api/v1/items/{item['id']}"
    changed = client.patch(url, json={"expected_version": 1, "title": "Edited"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["content_md"] == "Keep me"
    stale = client.patch(url, json={"expected_version": 1, "title": "Stale automation"})
    assert stale.status_code == 409
    assert client.get(url).json()["title"] == "Edited"
    for patch in ({"title": None}, {"type": "task"}, {"planned_date": "2026-10-01"}, {"title": "   "}):
        response = client.patch(url, json={"expected_version": 2, **patch})
        assert response.status_code == 422, response.text


def test_concurrent_edits_have_one_winner(client):
    item = create(client)
    def edit(title):
        return client.patch(f"/api/v1/items/{item['id']}", json={"expected_version": 1, "title": title}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ["First", "Second"])) == [200, 409]
    assert client.get(f"/api/v1/items/{item['id']}").json()["version"] == 2


def test_deadline_order_and_clear(client):
    today = date.today()
    undated = create(client, "task")
    future = create(client, "task", due_date=str(today + timedelta(days=2)))
    date_only = create(client, "task", due_date=str(today - timedelta(days=1)))
    timed = create(client, "task", due_date=str(today - timedelta(days=1)), due_time="10:00:00", due_timezone="Asia/Kolkata")
    ids = [x["id"] for x in client.get("/api/v1/tasks").json()["items"]]
    assert ids.index(timed["id"]) < ids.index(date_only["id"]) < ids.index(future["id"]) < ids.index(undated["id"])
    cleared = client.patch(f"/api/v1/items/{future['id']}", json={"expected_version": 1, "due_date": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["due_date"] is None
    for fields in ({"due_time": "10:00"}, {"due_date": "bad"}, {"due_date": str(today), "due_timezone": "Invalid/Zone"}):
        response = client.post("/api/v1/items", json={"item_type": "task", "title": "Invalid deadline", **fields})
        assert response.status_code == 422, response.text


def test_idempotent_create_and_changed_payload_conflict(client):
    headers = {"Idempotency-Key": str(uuid4())}
    body = {"item_type": "note", "title": "One creation"}
    first = client.post("/api/v1/items", json=body, headers=headers)
    second = client.post("/api/v1/items", json=body, headers=headers)
    assert first.status_code == 201 and second.status_code in (200, 201)
    assert first.json() == second.json()
    conflict = client.post("/api/v1/items", json={**body, "title": "Changed"}, headers=headers)
    assert conflict.status_code == 409


def test_archive_before_delete_and_no_content_history(client):
    item = create(client, content_md="Private text to remove")
    url = f"/api/v1/items/{item['id']}"
    assert client.delete(url, params={"expected_version": 1, "confirm": True}).status_code == 409
    item = mutate(client, item, "archive")
    assert client.delete(url, params={"expected_version": item["version"], "confirm": False}).status_code in (409, 422)
    deleted = client.delete(url, params={"expected_version": item["version"], "confirm": True})
    assert deleted.status_code in (200, 204), deleted.text
    assert client.get(url).status_code == 404
    assert client.get(url + "/history").status_code == 404


def test_project_links_versions_and_non_cascading_archive(client):
    project = create(client, "project")
    task = create(client, "task", due_date="2027-01-02")
    moved = mutate(client, task, "move", project_id=project["id"], project_expected_version=project["version"])
    assert moved["id"] == task["id"] and moved["due_date"] == "2027-01-02"
    assert moved["placement_state"] == "classified"
    listed = client.get("/api/v1/items", params={"project_id": project["id"]}).json()["items"]
    assert [x["id"] for x in listed] == [task["id"]]
    project = client.get(f"/api/v1/items/{project['id']}").json()
    project = mutate(client, project, "archive")
    assert task["id"] in [x["id"] for x in client.get("/api/v1/tasks").json()["items"]]
    deletion = client.delete(f"/api/v1/items/{project['id']}", params={"expected_version": project["version"], "confirm": True})
    assert deletion.status_code == 409
    relation = moved["relations"][0]
    stale = client.request("DELETE", f"/api/v1/relations/{relation['id']}", json={"from_expected_version": 1, "to_expected_version": project["version"]})
    assert stale.status_code == 409
    assert client.get(f"/api/v1/items/{task['id']}").json()["relations"]
    removed = client.request("DELETE", f"/api/v1/relations/{relation['id']}", json={"from_expected_version": moved["version"], "to_expected_version": project["version"]})
    assert removed.status_code == 200, removed.text
    project = client.get(f"/api/v1/items/{project['id']}").json()
    assert client.delete(f"/api/v1/items/{project['id']}", params={"expected_version": project["version"], "confirm": True}).status_code == 204
    assert client.get(f"/api/v1/items/{task['id']}").status_code == 200


def test_undo_conflicts_with_later_edits(client):
    item = create(client, title="Original")
    url = f"/api/v1/items/{item['id']}"
    edit = client.patch(url, json={"expected_version": 1, "title": "First"}).json()
    undone = client.post(f"/api/v1/actions/{edit['action_id']}/undo", json={"expected_versions": {item["id"]: 2}})
    assert undone.status_code == 200, undone.text
    assert client.get(url).json()["title"] == "Original"
    second = client.patch(url, json={"expected_version": 3, "title": "Second"}).json()
    client.patch(url, json={"expected_version": 4, "title": "New manual decision"})
    stale = client.post(f"/api/v1/actions/{second['action_id']}/undo", json={"expected_versions": {item["id"]: 5}})
    assert stale.status_code == 409, stale.text
    assert client.get(url).json()["title"] == "New manual decision"


def test_partial_deadline_edit_and_relation_validation(client):
    task = create(client, "task", due_date="2027-02-03")
    changed = client.patch(f"/api/v1/items/{task['id']}", json={"expected_version": 1, "due_time": "14:30:00", "due_timezone": "Asia/Kolkata"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["due_date"] == "2027-02-03"
    note = create(client)
    invalid = client.post("/api/v1/relations", json={"from_item_id": task["id"], "from_expected_version": 2, "to_item_id": note["id"], "to_expected_version": 1, "relation": "part_of"})
    assert invalid.status_code == 422, invalid.text
    assert client.get(f"/api/v1/items/{task['id']}").json()["version"] == 2


def test_auth_and_pagination(client):
    create(client)
    create(client)
    assert client.get("/api/v1/items", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/v1/health/live", headers={"Authorization": ""}).status_code == 200
    page = client.get("/api/v1/items?limit=1").json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = client.get("/api/v1/items", params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    for cursor in ("-1", "LTE", "!", "a"):
        response = client.get("/api/v1/items", params={"cursor": cursor})
        assert response.status_code == 422, response.text


def test_move_undo_restores_both_items_and_link(client):
    project = create(client, "project")
    task = create(client, "task")
    moved = mutate(client, task, "move", project_id=project["id"], project_expected_version=1)
    undone = client.post(f"/api/v1/actions/{moved['action_id']}/undo", json={"expected_versions": {task["id"]: 2, project["id"]: 2}})
    assert undone.status_code == 200, undone.text
    restored = client.get(f"/api/v1/items/{task['id']}").json()
    assert restored["placement_state"] == "inbox" and restored["relations"] == []
    assert client.get(f"/api/v1/items/{project['id']}").json()["relations"] == []


def test_uncategorized_tasks_never_appear_in_inbox(client):
    """An uncategorized task is internally placement_state="inbox" (it has
    no category), but Tasks is its own flat cross-category view regardless
    of category — Inbox is for items awaiting manual classification, which
    a task never needs. Regression test for a real UI report: tasks were
    cluttering the Inbox page alongside genuinely unclassified notes."""
    task = create(client, "task", title="Uncategorized task")
    assert task["placement_state"] == "inbox"
    note = create(client, "note", title="Uncategorized note")
    assert note["placement_state"] == "inbox"

    inbox_items = client.get("/api/v1/inbox").json()["items"]
    inbox_ids = {item["id"] for item in inbox_items}
    assert task["id"] not in inbox_ids
    assert note["id"] in inbox_ids
