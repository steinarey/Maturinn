"""Tests run against a real Postgres (pg_trgm and text search can't be faked).

Uses the docker-compose db by default, in its own schema `maturinn_test`,
which is dropped and re-migrated once per test run. Each test runs inside a
transaction that is rolled back.
"""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", "postgresql://maturinn:maturinn@localhost:5433/maturinn")
os.environ["DB_SCHEMA"] = os.environ.get("TEST_DB_SCHEMA", "maturinn_test")
os.environ["PHOTOS_DIR"] = tempfile.mkdtemp(prefix="maturinn-photos-")
os.environ["WORKER_ENABLED"] = "false"
os.environ["AUTH_ENABLED"] = "false"  # test_auth.py turns it on
# Never reach a real LLM provider from tests, whatever .env says.
# Same for Home Assistant (shopping list); tests that need it set fake values and fake the network.
for _k in ("PROVIDER", "LLM", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
           "HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN", "HOME_ASSISTANT_TODO"):
    os.environ[_k] = ""

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_session  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    schema = get_settings().db_schema
    assert schema != "maturinn", "refusing to run tests in the app schema"
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    command.upgrade(Config("alembic.ini"), "head")
    return eng


@pytest.fixture
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def client(session):
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
