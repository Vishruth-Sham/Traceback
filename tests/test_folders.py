"""Filesystem-style nested folders: item_type='folder' + part_of, unlimited depth.

Real PostgreSQL, real HTTP (the `client` fixture). Covers docs/folder-hierarchy-
backend-spec.md §7's acceptance list: create/read a folder, nesting 2-3 levels
deep, listing children by parent_id, moving an item into a folder with
category inheritance, cycle rejection, non-empty-folder delete protection,
non-cascading archive, and category_id + top_level root listing.
"""
from uuid import uuid4


def create(client, kind="note", **fields):
    response = client.post("/api/v1/items", json={"item_type": kind, "title": str(uuid4()), **fields})
    assert response.status_code == 201, response.text
    return response.json()


def link_part_of(client, child, parent):
    response = client.post(
        "/api/v1/relations",
        json={
            "from_item_id": child["id"],
            "from_expected_version": child["version"],
            "relation": "part_of",
            "to_item_id": parent["id"],
            "to_expected_version": parent["version"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_read_a_folder(client):
    folder = create(client, "folder", title="Distributed Systems")
    assert folder["item_type"] == "folder"
    assert folder["placement_state"] == "inbox"
    assert folder["category_id"] is None

    fetched = client.get(f"/api/v1/items/{folder['id']}").json()
    assert fetched["id"] == folder["id"]
    assert fetched["item_type"] == "folder"


def test_folder_cannot_carry_task_deadline_fields(client):
    response = client.post("/api/v1/items", json={"item_type": "folder", "title": "x", "due_date": "2026-10-01"})
    assert response.status_code == 422


def test_nest_folders_multiple_levels_and_list_children_by_parent_id(client):
    learning = create(client, "folder", title="Learning root")
    root = client.post(f"/api/v1/items/{learning['id']}/move", json={"expected_version": learning["version"], "category_id": _learning_category(client)}).json()

    level1 = create(client, "folder", title="Distributed systems")
    level2 = create(client, "folder", title="Consensus")
    note = create(client, "note", title="Raft summary")

    link_part_of(client, level1, root)
    level1 = client.get(f"/api/v1/items/{level1['id']}").json()
    link_part_of(client, level2, level1)
    level2 = client.get(f"/api/v1/items/{level2['id']}").json()
    link_part_of(client, note, level2)

    root_children = client.get(f"/api/v1/items?parent_id={root['id']}").json()["items"]
    assert [c["id"] for c in root_children] == [level1["id"]]

    level1_children = client.get(f"/api/v1/items?parent_id={level1['id']}").json()["items"]
    assert [c["id"] for c in level1_children] == [level2["id"]]

    level2_children = client.get(f"/api/v1/items?parent_id={level2['id']}").json()["items"]
    assert [c["id"] for c in level2_children] == [note["id"]]


def test_move_item_into_folder_via_move_endpoint_inherits_category(client):
    learning_category = _learning_category(client)
    folder = create(client, "folder", title="Books to read")
    folder = client.post(f"/api/v1/items/{folder['id']}/move", json={"expected_version": folder["version"], "category_id": learning_category}).json()

    note = create(client, "note", title="Untitled note")
    assert note["placement_state"] == "inbox"

    moved = client.post(
        f"/api/v1/items/{note['id']}/move",
        json={"expected_version": note["version"], "folder_id": folder["id"], "folder_expected_version": folder["version"]},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["placement_state"] == "classified"
    assert body["category_id"] == learning_category
    assert any(r["relation"] == "part_of" and r["to_item_id"] == folder["id"] for r in body["relations"])

    # The folder itself is bumped/revised as the "other side" of the relation.
    refreshed_folder = client.get(f"/api/v1/items/{folder['id']}").json()
    assert refreshed_folder["version"] == folder["version"] + 1


def test_move_into_an_unclassified_folder_keeps_the_item_in_inbox(client):
    """Regression test: a folder still sitting in Inbox (no category_id yet)
    has category_id=None; naively forcing placement_state='classified' on
    an item moved into it would violate ck_items_placement_category
    (classified requires a non-null category_id). The item must inherit
    the folder's actual state, Inbox included."""
    folder = create(client, "folder", title="Uncategorized folder")
    assert folder["category_id"] is None
    assert folder["placement_state"] == "inbox"

    note = create(client, "note")
    moved = client.post(
        f"/api/v1/items/{note['id']}/move",
        json={"expected_version": note["version"], "folder_id": folder["id"], "folder_expected_version": folder["version"]},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["category_id"] is None
    assert body["placement_state"] == "inbox"
    assert body["inbox_entered_at"] is not None
    assert any(r["relation"] == "part_of" and r["to_item_id"] == folder["id"] for r in body["relations"])


def test_move_into_folder_requires_folder_expected_version(client):
    folder = create(client, "folder")
    note = create(client, "note")
    response = client.post(f"/api/v1/items/{note['id']}/move", json={"expected_version": note["version"], "folder_id": folder["id"]})
    assert response.status_code == 422


def test_move_destinations_are_mutually_exclusive_with_folder(client):
    folder = create(client, "folder")
    note = create(client, "note")
    response = client.post(
        f"/api/v1/items/{note['id']}/move",
        json={
            "expected_version": note["version"],
            "folder_id": folder["id"],
            "folder_expected_version": folder["version"],
            "inbox": True,
        },
    )
    assert response.status_code == 422


def test_folder_cannot_contain_itself_via_move(client):
    folder = create(client, "folder")
    response = client.post(
        f"/api/v1/items/{folder['id']}/move",
        json={"expected_version": folder["version"], "folder_id": folder["id"], "folder_expected_version": folder["version"]},
    )
    assert response.status_code == 422


def test_part_of_can_target_a_folder_not_only_a_project(client):
    folder = create(client, "folder")
    note = create(client, "note")
    result = link_part_of(client, note, folder)
    assert result["relation"] == "part_of"
    assert result["to_item_id"] == folder["id"]


def test_linking_part_of_to_a_folder_via_relations_inherits_category_just_like_move(client):
    """POST /relations must behave identically to POST /move for category
    inheritance -- an item's category should never depend on which of the
    two routes was used to nest it."""
    learning_category = _learning_category(client)
    folder = create(client, "folder", title="Learning root", category_id=learning_category)
    note = create(client, "note")
    assert note["placement_state"] == "inbox"

    link_part_of(client, note, folder)
    refreshed = client.get(f"/api/v1/items/{note['id']}").json()
    assert refreshed["category_id"] == learning_category
    assert refreshed["placement_state"] == "classified"


def test_linking_part_of_to_an_unclassified_folder_via_relations_keeps_inbox(client):
    folder = create(client, "folder", title="Uncategorized folder")
    note = create(client, "note")

    link_part_of(client, note, folder)
    refreshed = client.get(f"/api/v1/items/{note['id']}").json()
    assert refreshed["category_id"] is None
    assert refreshed["placement_state"] == "inbox"
    assert refreshed["inbox_entered_at"] is not None


def test_linking_part_of_to_a_project_via_relations_also_sets_projects_category(client):
    project = create(client, "project")
    note = create(client, "note")

    link_part_of(client, note, project)
    refreshed = client.get(f"/api/v1/items/{note['id']}").json()
    projects_category = next(c["id"] for c in client.get("/api/v1/categories").json() if c["slug"] == "projects")
    assert refreshed["category_id"] == projects_category
    assert refreshed["placement_state"] == "classified"


def test_part_of_rejects_a_non_project_non_folder_target(client):
    note = create(client, "note")
    other_note = create(client, "note")
    response = client.post(
        "/api/v1/relations",
        json={
            "from_item_id": note["id"],
            "from_expected_version": note["version"],
            "relation": "part_of",
            "to_item_id": other_note["id"],
            "to_expected_version": other_note["version"],
        },
    )
    assert response.status_code == 422


def test_direct_cycle_via_relations_is_rejected(client):
    a = create(client, "folder", title="A")
    b = create(client, "folder", title="B")
    link_part_of(client, a, b)  # a part_of b
    a = client.get(f"/api/v1/items/{a['id']}").json()
    b = client.get(f"/api/v1/items/{b['id']}").json()

    cyclical = client.post(
        "/api/v1/relations",
        json={
            "from_item_id": b["id"],
            "from_expected_version": b["version"],
            "relation": "part_of",
            "to_item_id": a["id"],
            "to_expected_version": a["version"],
        },
    )
    assert cyclical.status_code == 422
    assert "cannot" in cyclical.json()["error"]["message"].lower() or "itself" in cyclical.json()["error"]["message"].lower()


def test_deep_cycle_via_relations_is_rejected(client):
    a = create(client, "folder", title="A")
    b = create(client, "folder", title="B")
    c = create(client, "folder", title="C")
    link_part_of(client, b, a)  # b part_of a
    b = client.get(f"/api/v1/items/{b['id']}").json()
    link_part_of(client, c, b)  # c part_of b  =>  chain: c -> b -> a
    a = client.get(f"/api/v1/items/{a['id']}").json()
    c = client.get(f"/api/v1/items/{c['id']}").json()

    cyclical = client.post(
        "/api/v1/relations",
        json={
            "from_item_id": a["id"],
            "from_expected_version": a["version"],
            "relation": "part_of",
            "to_item_id": c["id"],
            "to_expected_version": c["version"],
        },
    )
    assert cyclical.status_code == 422


def test_deep_cycle_via_move_is_rejected(client):
    a = create(client, "folder", title="A")
    b = create(client, "folder", title="B")
    link_part_of(client, b, a)  # b part_of a
    a = client.get(f"/api/v1/items/{a['id']}").json()
    b = client.get(f"/api/v1/items/{b['id']}").json()

    cyclical = client.post(
        f"/api/v1/items/{a['id']}/move",
        json={"expected_version": a["version"], "folder_id": b["id"], "folder_expected_version": b["version"]},
    )
    assert cyclical.status_code == 422


def test_permanently_deleting_a_non_empty_folder_is_blocked(client):
    folder = create(client, "folder")
    note = create(client, "note")
    link_part_of(client, note, folder)
    archived_folder = client.get(f"/api/v1/items/{folder['id']}").json()
    archived = client.post(f"/api/v1/items/{folder['id']}/archive", json={"expected_version": archived_folder["version"]}).json()

    blocked = client.delete(f"/api/v1/items/{folder['id']}", params={"expected_version": archived["version"], "confirm": True})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "linked_item_conflict"


def test_archiving_a_folder_does_not_cascade_to_children(client):
    folder = create(client, "folder")
    note = create(client, "note")
    link_part_of(client, note, folder)
    folder = client.get(f"/api/v1/items/{folder['id']}").json()

    archived = client.post(f"/api/v1/items/{folder['id']}/archive", json={"expected_version": folder["version"]}).json()
    assert archived["archived_at"] is not None

    refreshed_note = client.get(f"/api/v1/items/{note['id']}").json()
    assert refreshed_note["archived_at"] is None

    still_listed = client.get(f"/api/v1/items?parent_id={folder['id']}").json()["items"]
    assert [item["id"] for item in still_listed] == [note["id"]]


def _learning_category(client) -> str:
    categories = client.get("/api/v1/categories").json()
    return next(c["id"] for c in categories if c["slug"] == "learning")


def test_top_level_filters_to_uncontained_items_in_a_category(client):
    learning_category = _learning_category(client)
    root_folder = create(client, "folder", title="Learning root", category_id=learning_category)
    child = create(client, "note", title="Child note")
    link_part_of(client, child, root_folder)
    unrelated_root_note = create(client, "note", title="Unrelated top-level note", category_id=learning_category)

    top_level = client.get(f"/api/v1/items?category_id={learning_category}&top_level=true").json()["items"]
    top_level_ids = {item["id"] for item in top_level}
    assert root_folder["id"] in top_level_ids
    assert unrelated_root_note["id"] in top_level_ids
    assert child["id"] not in top_level_ids


def test_item_can_have_only_one_part_of_parent_and_move_replaces_it(client):
    first = create(client, "folder", title="First")
    second = create(client, "folder", title="Second")
    note = create(client, "note", title="One home")
    link_part_of(client, note, first)
    note = client.get(f"/api/v1/items/{note['id']}").json()
    second = client.get(f"/api/v1/items/{second['id']}").json()

    duplicate = client.post(
        "/api/v1/relations",
        json={
            "from_item_id": note["id"],
            "from_expected_version": note["version"],
            "relation": "part_of",
            "to_item_id": second["id"],
            "to_expected_version": second["version"],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "already_contained"

    moved = client.post(
        f"/api/v1/items/{note['id']}/move",
        json={
            "expected_version": note["version"],
            "folder_id": second["id"],
            "folder_expected_version": second["version"],
        },
    )
    assert moved.status_code == 200, moved.text
    parents = [r["to_item_id"] for r in moved.json()["relations"] if r["relation"] == "part_of"]
    assert parents == [second["id"]]


def test_move_to_category_removes_folder_parent(client):
    learning = _learning_category(client)
    folder = create(client, "folder")
    note = create(client, "note")
    link_part_of(client, note, folder)
    note = client.get(f"/api/v1/items/{note['id']}").json()

    moved = client.post(
        f"/api/v1/items/{note['id']}/move",
        json={"expected_version": note["version"], "category_id": learning},
    )
    assert moved.status_code == 200, moved.text
    assert not any(r["relation"] == "part_of" for r in moved.json()["relations"])


def test_moving_folder_propagates_placement_to_descendants(client):
    learning = _learning_category(client)
    folder = create(client, "folder")
    child = create(client, "folder")
    note = create(client, "note")
    link_part_of(client, child, folder)
    child = client.get(f"/api/v1/items/{child['id']}").json()
    link_part_of(client, note, child)
    folder = client.get(f"/api/v1/items/{folder['id']}").json()

    moved = client.post(
        f"/api/v1/items/{folder['id']}/move",
        json={"expected_version": folder["version"], "category_id": learning},
    )
    assert moved.status_code == 200, moved.text
    assert client.get(f"/api/v1/items/{child['id']}").json()["category_id"] == learning
    assert client.get(f"/api/v1/items/{note['id']}").json()["category_id"] == learning


def test_active_child_of_archived_folder_surfaces_at_category_root(client):
    learning = _learning_category(client)
    folder = create(client, "folder", category_id=learning)
    child = create(client, "note")
    link_part_of(client, child, folder)
    folder = client.get(f"/api/v1/items/{folder['id']}").json()
    client.post(f"/api/v1/items/{folder['id']}/archive", json={"expected_version": folder["version"]})

    roots = client.get(f"/api/v1/items?category_id={learning}&top_level=true").json()["items"]
    assert child["id"] in {item["id"] for item in roots}


def test_create_item_inside_folder_is_atomic(client):
    learning = _learning_category(client)
    folder = create(client, "folder", category_id=learning)
    response = client.post(
        "/api/v1/items",
        json={
            "item_type": "note",
            "title": "Created in place",
            "folder_id": folder["id"],
            "folder_expected_version": folder["version"],
        },
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["category_id"] == learning
    assert any(r["relation"] == "part_of" and r["to_item_id"] == folder["id"] for r in item["relations"])
