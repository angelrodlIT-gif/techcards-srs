import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app, get_clock
from app.models import Base


@pytest.fixture
def db_engine():
    url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    options = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    engine = create_engine(url, **(options if url.startswith("sqlite") else {}))
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    # TEST_DATABASE_URL must point at a disposable database, never production.
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_engine):
    def override_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def set_clock(client):
    current = {"now": None}

    def _set(value):
        current["now"] = value
        app.dependency_overrides[get_clock] = lambda: lambda: current["now"]

    return _set
