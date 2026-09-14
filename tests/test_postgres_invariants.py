"""Database constraint and deletion checks run only in the owned test database."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_postgres_rejects_invalid_placement_and_missing_task_details(client):
    from backend.db import engine
    assert engine.dialect.name == "postgresql"
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO items(id,item_type,title,content_md,placement_state,attributes,version)
                VALUES (:id,'note','Invalid','','classified','{}',1)
            """), {"id": uuid4()})
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO items(id,item_type,title,content_md,placement_state,attributes,version)
                VALUES (:id,'task','Missing task detail','','inbox','{}',1)
            """), {"id": uuid4()})


def test_permanent_delete_purges_snapshots_and_replay_content(client):
    from backend.db import engine
    marker = "erasure-check-" + uuid4().hex
    item = client.post("/api/v1/items", json={"item_type": "note", "title": marker}, headers={"Idempotency-Key": str(uuid4())}).json()
    archived = client.post(f"/api/v1/items/{item['id']}/archive", json={"expected_version": 1}).json()
    response = client.delete(f"/api/v1/items/{item['id']}", params={"expected_version": archived["version"], "confirm": True})
    assert response.status_code == 204, response.text
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM item_revisions WHERE item_id=:id"), {"id": item["id"]}) == 0
        assert connection.scalar(text("SELECT count(*) FROM actions WHERE result::text LIKE :marker"), {"marker": "%" + marker + "%"}) == 0


def test_concurrent_idempotent_create(client):
    from concurrent.futures import ThreadPoolExecutor
    key = str(uuid4())
    def create(_):
        return client.post("/api/v1/items", json={"item_type": "note", "title": "Concurrent retry"}, headers={"Idempotency-Key": key})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert results[0].json()["id"] == results[1].json()["id"]
