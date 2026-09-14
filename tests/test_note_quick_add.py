"""PostgreSQL-backed note quick-add review and acceptance contract."""


def create_note_capture(client, **metadata):
    response = client.post(
        "/api/v1/captures",
        json={
            "source_type": "typed",
            "raw_text": "# Exact body\n\nKeep **this** markdown.",
            "captured_at": "2026-09-15T10:30:00+05:30",
            "source_timezone": "Asia/Kolkata",
            "timestamp_origin": "client_supplied",
            "metadata": {"processing_profile": "note_quick_add", "supplied_title": "My title", "placement_hint": "learning", **metadata},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_proposal_is_reviewed_without_creating_item_then_accepts_exact_note(client):
    capture = create_note_capture(client)
    category = next(category for category in client.get("/api/v1/categories").json() if category["slug"] == "learning")
    claim = client.post(
        f"/api/v1/captures/{capture['id']}/claim",
        json={"expected_generation": 1, "lease_seconds": 300},
    ).json()
    proposed = client.post(
        f"/api/v1/captures/{capture['id']}/proposal",
        json={
            "expected_version": capture["version"],
            "expected_generation": 1,
            "lease_token": claim["lease_token"],
            "proposal": {
                "title": "My title",
                "destination_kind": "category",
                "destination_id": category["id"],
                "explanation": "The placement hint names learning.",
                "confidence": "high",
            },
        },
    )
    assert proposed.status_code == 200, proposed.text
    review = proposed.json()
    assert review["processing"]["state"] == "awaiting_review"
    assert review["processing"]["proposal"]["destination_id"] == category["id"]
    assert review["resulting_item_ids"] == []

    accepted = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={
            "expected_version": review["version"],
            "expected_generation": review["processing"]["generation"],
            "mode": "manual",
            "items": [{"kind": "create", "item": {"item_type": "note", "title": "My title", "content_md": "# Exact body\n\nKeep **this** markdown.", "category_id": category["id"]}}],
        },
    )
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["capture"]["processing"]["state"] == "resolved"
    assert result["items"][0]["content_md"] == "# Exact body\n\nKeep **this** markdown."
    assert result["capture"]["resulting_item_ids"] == [result["items"][0]["id"]]


def test_note_proposal_rejects_unknown_location_and_interpretation_rewrite(client):
    capture = create_note_capture(client)
    claim = client.post(f"/api/v1/captures/{capture['id']}/claim", json={"expected_generation": 1}).json()
    invalid = client.post(
        f"/api/v1/captures/{capture['id']}/proposal",
        json={"expected_version": capture["version"], "expected_generation": 1, "lease_token": claim["lease_token"], "proposal": {"title": "My title", "destination_kind": "folder", "destination_id": "11111111-1111-1111-1111-111111111111", "destination_version": 1, "explanation": "No."}},
    )
    assert invalid.status_code == 422
    rewritten = client.post(
        f"/api/v1/captures/{capture['id']}/interpretations",
        json={"expected_version": capture["version"], "expected_generation": 1, "mode": "manual", "items": [{"kind": "create", "item": {"item_type": "note", "title": "Changed", "content_md": "model rewrite", "category_id": None}}]},
    )
    assert rewritten.status_code == 422


def test_note_correction_preserves_original_and_fences_old_proposal(client):
    capture = create_note_capture(client)
    corrected = client.post(
        f"/api/v1/captures/{capture['id']}/corrections",
        json={"expected_version": capture["version"], "note_text": "Corrected body", "supplied_title": "Corrected title", "placement_hint": "Other"},
    )
    assert corrected.status_code == 200, corrected.text
    value = corrected.json()
    assert value["raw_text"].startswith("# Exact body")
    assert value["corrections"]["note_text"] == "Corrected body"
    assert value["processing"]["generation"] == 2
    assert value["processing"]["proposal"] is None


def test_location_catalog_has_current_breadcrumbs_and_no_today(client):
    response = client.get("/api/v1/locations?limit=200")
    assert response.status_code == 200, response.text
    paths = [location["path"] for location in response.json()["items"]]
    assert "Other" in paths
    assert all("Today" not in path and "Everyday Life" not in path for path in paths)
