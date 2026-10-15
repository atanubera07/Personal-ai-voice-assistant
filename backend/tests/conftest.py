import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import Settings
from app.db import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    database_url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    if os.environ.get("TEST_DATABASE_URL"):
        engine = create_engine(database_url)
        # Dedicated disposable test database only. CI and local scripts create it for this suite.
        Base.metadata.drop_all(engine)
        engine.dispose()
    settings = Settings(database_url, "o" * 40, "j" * 40, Fernet.generate_key().decode(), "w" * 40, True)
    with TestClient(create_app(settings)) as client:
        token = client.post(
            "/v1/auth/session", json={"device_id": "test-device", "secret": settings.owner_secret}
        ).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        yield client
