"""Use a fresh PostgreSQL database for each test session; never touch app tables."""
import os
import tempfile
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session")
def client():
    source = os.getenv("TRACEBACK_TEST_ADMIN_URL") or dotenv_values(".env").get("TRACEBACK_DATABASE_URL")
    if not source:
        pytest.fail("Run python3 scripts/local_db.py init or set TRACEBACK_TEST_ADMIN_URL to a local PostgreSQL admin URL.")
    url = make_url(source)
    if url.get_backend_name() != "postgresql" or url.host not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("Tests require an explicit loopback PostgreSQL URL.")
    database = "traceback_test_" + uuid4().hex
    admin_url = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "TRACEBACK_DATABASE_URL", "TRACEBACK_API_TOKEN", "TRACEBACK_ASSET_DIR")}
    asset_directory = tempfile.TemporaryDirectory(prefix="traceback-test-assets-")
    os.environ["TRACEBACK_ASSET_DIR"] = asset_directory.name
    test_url = url.set(drivername="postgresql+psycopg", database=database).render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = test_url
    os.environ["TRACEBACK_DATABASE_URL"] = test_url
    os.environ["TRACEBACK_API_TOKEN"] = "traceback-integration-test-token-only"
    try:
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")
        # Verify reversible fresh initialization before populating acceptance data.
        command.downgrade(Config("alembic.ini"), "base")
        command.upgrade(Config("alembic.ini"), "head")
        from backend.main import app
        from fastapi.testclient import TestClient
        with TestClient(app, headers={"Authorization": "Bearer traceback-integration-test-token-only"}) as api:
            yield api
    finally:
        from backend.db import engine
        engine.dispose()
        asset_directory.cleanup()
        # This exact UUID-named database was created by this fixture above.
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def drain_claimable_captures(client) -> None:
    """Archive every claimable capture left by earlier tests in the shared session database.

    `claim-next` is oldest-first (with aging), unlike the retired newest-first runner query, so a
    test that expects its own capture to be processed must start from an empty queue.
    """
    for state in ("pending", "processing"):
        cursor = None
        while True:
            page = client.get("/api/v1/captures", params={"state": state, "limit": 100, **({"cursor": cursor} if cursor else {})}).json()
            for capture in page["items"]:
                client.post(f"/api/v1/captures/{capture['id']}/archive", json={"expected_version": capture["version"]})
            cursor = page.get("next_cursor")
            if not cursor:
                break
