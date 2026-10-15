import base64
import hashlib
import json
import time
import uuid
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.db import Device
from app.main import create_app


def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


def sign(key, message):
    return base64.b64encode(key.sign(message.encode(), ec.ECDSA(hashes.SHA256()))).decode()


def enroll(client, key, device="paired-device"):
    pairing = client.app.state.auth.issue_pairing()
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode()
    body = {
        "device_id": device,
        "pairing_token": pairing,
        "public_key": public,
        "signature": sign(key, "personal-agent-enroll-v1\n" + device + "\n" + pairing),
    }
    response = client.post("/v1/auth/enroll", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"], body


def signed_headers(key, token, path="/v1/calls", method="GET", body=b"", nonce=None):
    timestamp = str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    message = "\n".join(
        [
            "personal-agent-request-v1",
            method,
            path,
            hashlib.sha256(body).hexdigest(),
            hashlib.sha256(token.encode()).hexdigest(),
            timestamp,
            nonce,
        ]
    )
    return {
        "Authorization": "Bearer " + token,
        "X-Device-Timestamp": timestamp,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": sign(key, message),
    }


def test_pairing_one_use_and_bearer_theft(client):
    key = signing_key()
    token, enrollment = enroll(client, key)
    assert client.post("/v1/auth/enroll", json=enrollment).status_code == 401
    assert client.get("/v1/calls", headers={"Authorization": "Bearer " + token}).status_code == 401
    headers = signed_headers(key, token)
    assert client.get("/v1/calls", headers=headers).status_code == 200
    assert client.get("/v1/calls", headers=headers).status_code == 401
    assert client.get("/v1/calls", headers=signed_headers(signing_key(), token)).status_code == 401


def test_challenge_session_replay_logout_and_revocation(client):
    key = signing_key()
    token, _ = enroll(client, key)
    challenge = client.post("/v1/auth/challenge", json={"device_id": "paired-device"}).json()
    body = {
        "device_id": "paired-device",
        "challenge_id": challenge["id"],
        "signature": sign(key, "personal-agent-session-v1\n" + challenge["id"] + "\n" + challenge["nonce"]),
    }
    session = client.post("/v1/auth/device-session", json=body)
    assert session.status_code == 200
    assert client.post("/v1/auth/device-session", json=body).status_code == 401
    assert (
        client.post(
            "/v1/auth/logout", headers=signed_headers(key, token, "/v1/auth/logout", "POST")
        ).status_code
        == 200
    )
    assert client.get("/v1/calls", headers=signed_headers(key, token)).status_code == 401
    assert (
        client.get("/v1/calls", headers=signed_headers(key, session.json()["access_token"])).status_code
        == 401
    )
    with client.app.state.db.transaction() as s:
        s.get(Device, "paired-device").enabled = False
    assert client.post("/v1/auth/challenge", json={"device_id": "paired-device"}).status_code == 401


def test_proof_covers_body_path_and_token(client):
    key = signing_key()
    token, _ = enroll(client, key)
    body = json.dumps({"text": "note: secret"}).encode()
    headers = signed_headers(key, token, "/v1/assistant/interpret", "POST", body)
    headers["Content-Type"] = "application/json"
    assert (
        client.post(
            "/v1/assistant/interpret", content=body.replace(b"secret", b"change"), headers=headers
        ).status_code
        == 401
    )
    assert client.get("/v1/budget/current", headers=signed_headers(key, token)).status_code == 401
    assert client.post("/v1/assistant/interpret", content=body, headers=headers).status_code == 200


def test_login_throttle_shared_and_body_limit(client):
    object.__setattr__(client.app.state.settings, "auth_rate_limit", 3)
    for _ in range(2):
        assert (
            client.post("/v1/auth/session", json={"device_id": "test-device", "secret": "x" * 40}).status_code
            == 401
        )
    assert (
        client.post("/v1/auth/session", json={"device_id": "test-device", "secret": "x" * 40}).status_code
        == 429
    )
    response = client.post("/v1/auth/session", content=b"x" * 70000)
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert "x-request-id" in response.headers


def test_production_rejects_sqlite_and_bad_origin(client):
    settings = client.app.state.settings
    with pytest.raises(RuntimeError):
        create_app(
            replace(
                settings,
                simulation=False,
                public_origin="https://agent.example",
                database_url="sqlite:///:memory:",
            )
        )
    with pytest.raises(RuntimeError):
        create_app(
            replace(
                settings,
                simulation=False,
                public_origin="http://agent.example",
                database_url="postgresql+psycopg://localhost/db",
            )
        )


def test_production_http_boundary_and_no_shared_secret(client):
    # Use an already migrated test database; production construction is independently validated above.
    settings = client.app.state.settings
    object.__setattr__(settings, "simulation", False)
    object.__setattr__(settings, "public_origin", "https://testserver")
    assert client.get("/v1/calls").status_code == 400
    assert client.get("/v1/calls", headers={"X-Forwarded-Proto": "https"}).status_code == 400
    with TestClient(client.app, base_url="https://testserver") as https:
        assert (
            https.post(
                "/v1/auth/session", json={"device_id": "test-device", "secret": settings.owner_secret}
            ).status_code
            == 503
        )
        assert https.get("/health").headers["strict-transport-security"]


def test_unknown_error_redacted(client, caplog):
    @client.app.get("/fail-private")
    def fail():
        raise RuntimeError("PRIVATE-TOKEN-123")

    response = client.get("/fail-private")
    assert response.status_code == 500
    assert "PRIVATE-TOKEN-123" not in response.text
    assert "PRIVATE-TOKEN-123" not in caplog.text


def test_upgrade_legacy_device_and_key_rotation(client):
    from cryptography.fernet import Fernet

    from app.db import Database

    key = signing_key()
    old_token = client.headers["Authorization"]
    token, _ = enroll(client, key, "test-device")
    assert client.get("/v1/calls", headers={"Authorization": old_token}).status_code == 401
    assert client.get("/v1/calls", headers=signed_headers(key, token)).status_code == 200
    original = client.app.state.settings
    ciphertext = client.app.state.db.encrypt({"private": "stored"})
    rotated = Database(
        replace(
            original,
            encryption_key=Fernet.generate_key().decode(),
            previous_encryption_keys=(original.encryption_key,),
        )
    )
    assert rotated.decrypt(ciphertext) == {"private": "stored"}
    assert client.app.state.db.number_fingerprints("+919876543210").issubset(
        rotated.number_fingerprints("+919876543210")
    )
