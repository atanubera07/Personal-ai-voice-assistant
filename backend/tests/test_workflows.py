import hashlib
import hmac
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.db import Call, Intent, Policy
from app.domain import caller_tool_allowed


def event(client, kind, ref="call-1", **fields):
    payload = {"event_id": str(uuid.uuid4()), "provider_call_id": ref, "type": kind, **fields}
    return send(client, payload)


def send(client, payload):
    raw = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        client.app.state.settings.webhook_secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/v1/provider/calls/events", content=raw, headers={"X-Timestamp": stamp, "X-Signature": signature}
    )


def active(client, recording=False):
    cid = event(client, "received").json()["call_id"]
    assert event(client, "disclosed").status_code == 200
    assert event(client, "consent", processing=True, recording=recording).status_code == 200
    return cid


def test_owner_auth_and_revocation(client):
    assert client.get("/v1/calls", headers={"Authorization": ""}).status_code == 401
    assert client.delete("/v1/auth/devices/test-device").status_code == 200
    assert client.get("/v1/calls").status_code == 401


def test_webhook_signature_and_replay(client):
    assert client.post("/v1/provider/calls/events", json={}).status_code == 401
    payload = {"type": "received", "event_id": "one", "provider_call_id": "one"}
    assert send(client, payload).status_code == 200
    assert send(client, payload).json()["duplicate"]
    assert send(client, {**payload, "reserve_paise": 22}).status_code == 409
    assert client.get("/v1/budget/current").json()["reserved_paise"] == 1000


def test_recording_requires_disclosure_and_consent(client):
    event(client, "received")
    assert event(client, "consent", processing=True, recording=True).status_code == 409
    event(client, "disclosed")
    result = event(client, "consent", processing=True, recording=False)
    assert result.json()["state"]["recording"] == "NEVER_RECORDED"
    assert event(client, "consent", processing=True, recording=True).status_code == 409


def test_processing_refusal_no_summary(client):
    cid = event(client, "received").json()["call_id"]
    event(client, "disclosed")
    event(client, "consent", processing=False, recording=True)
    assert event(client, "urgent").status_code == 409
    event(client, "ended", summary="Must not be retained")
    result = client.get(f"/v1/calls/{cid}").json()
    assert result.get("summary") is None
    assert result["recording"] == "NEVER_RECORDED"


def test_takeover_stop_before_bridge_and_one_use(client):
    cid = active(client, True)
    response = client.post(
        f"/v1/calls/{cid}/takeover-intents", json={"device_id": "test-device", "idempotency_key": "12345678"}
    )
    assert response.status_code == 200
    intent = response.json()
    assert event(client, "bridge_confirmed").status_code == 409
    consume = f"/v1/simulator/takeover/{intent['intent_id']}/consume"
    assert client.post(consume, json={"nonce": intent["join_token"]}).status_code == 200
    assert client.post(consume, json={"nonce": intent["join_token"]}).status_code == 409
    event(client, "media_ready", summary="AI-only summary")
    assert event(client, "handoff_failed").status_code == 409
    assert event(client, "bridge_confirmed").status_code == 409
    event(client, "recording_stopped")
    assert event(client, "bridge_confirmed").json()["state"]["phase"] == "OWNER_ACTIVE"
    event(client, "ai_left")
    event(client, "ended", summary="Private human speech")
    result = client.get(f"/v1/calls/{cid}").json()
    assert result["summary"] == "AI-only summary"
    from datetime import datetime

    assert (
        datetime.fromisoformat(result["expiry_at"]) - datetime.fromisoformat(result["ended_at"])
    ).days == 30


def test_urgency_outbox_once_and_summary_tombstone(client):
    cid = active(client)
    event(client, "urgent", reason="Callback today")
    event(client, "urgent", reason="Again")
    assert len(client.get("/v1/notifications").json()["items"]) == 1
    event(client, "ended", summary="Keep until deleted")
    assert client.delete(f"/v1/calls/{cid}").status_code == 200
    assert event(client, "ended", summary="Resurrection").json()["deleted"]
    assert client.get(f"/v1/calls/{cid}").status_code == 404
    assert client.get("/v1/notifications").json()["items"] == []


def test_budget_confirmation_replay_and_limit(client):
    period = client.get("/v1/budget/current").json()["period"]
    event(client, "received", reserve_paise=50000)
    assert event(client, "received", ref="second").json()["state"]["phase"] == "FAILED_ROUTED"
    proposal = client.post("/v1/budget/approvals", json={"period": period, "amount_paise": 10000}).json()
    assert client.get("/v1/budget/current").json()["authorized_limit_paise"] == 50000
    path = f"/v1/budget/approvals/{proposal['id']}/confirm"
    assert client.post(path, json={"nonce": "wrong-nonce" * 4}).status_code == 409
    for _ in range(2):
        assert client.post(path, json={"nonce": proposal["nonce"]}).json()["authorized_limit_paise"] == 60000


def test_concurrent_reservations_cannot_overspend(client):
    def receive(i):
        return event(client, "received", ref=f"parallel-{i}", reserve_paise=30000).json()["state"]["phase"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, range(2)))
    assert sorted(results) == ["DISCLOSURE", "FAILED_ROUTED"]
    assert client.get("/v1/budget/current").json()["reserved_paise"] == 30000


def test_unknown_end_preserves_reserve(client):
    active(client)
    event(client, "connection_lost")
    assert client.get("/v1/budget/current").json()["reserved_paise"] == 1000


def calendar_payload():
    return {
        "operation": "create",
        "calendar_id": "primary",
        "title": "Review",
        "start": "2026-10-16T10:00:00+05:30",
        "end": "2026-10-16T11:00:00+05:30",
        "timezone": "Asia/Kolkata",
    }


def test_calendar_confirm_and_stale_etag(client):
    body = calendar_payload()
    proposal = client.post("/v1/calendar/mutation-proposals", json=body).json()
    with client.app.state.db.transaction() as s:
        assert list(s.scalars(select(Policy).where(Policy.id.like("calendar:%")))) == []
    path = f"/v1/calendar/mutation-proposals/{proposal['id']}/confirm"
    created = client.post(path, json={"nonce": proposal["nonce"]}).json()
    assert client.post(path, json={"nonce": proposal["nonce"]}).json() == created
    edit = {**body, "operation": "edit", "event_id": created["event_id"], "source_etag": created["etag"]}
    first, second = [client.post("/v1/calendar/mutation-proposals", json=edit).json() for _ in range(2)]
    assert (
        client.post(
            f"/v1/calendar/mutation-proposals/{first['id']}/confirm", json={"nonce": first["nonce"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/calendar/mutation-proposals/{second['id']}/confirm", json={"nonce": second["nonce"]}
        ).status_code
        == 409
    )


def test_sensitive_values_encrypted_no_transcript(client):
    cid = active(client)
    event(client, "ended", summary="Sensitive summary 4321")
    with client.app.state.db.transaction() as s:
        row = s.get(Call, cid)
        assert "Sensitive" not in row.private
        assert "summary" not in row.data
    assert client.get(f"/v1/calls/{cid}").json()["summary"] == "Sensitive summary 4321"
    assert not caller_tool_allowed("read_notes")
    assert not caller_tool_allowed("approve_budget")
    assert caller_tool_allowed("take_message")
    assert event(client, "received", ref="bad", transcript="not allowed").status_code == 422


def test_live_mode_disabled(client):
    object.__setattr__(client.app.state.settings, "simulation", False)
    object.__setattr__(client.app.state.settings, "public_origin", "https://testserver")
    client.base_url = "https://testserver"
    assert event(client, "received").status_code == 503


def test_expired_confirmation_rejected(client):
    p = client.post("/v1/calendar/mutation-proposals", json=calendar_payload()).json()
    db = client.app.state.db
    with db.transaction() as s:
        row = s.get(Intent, p["id"])
        data = db.decrypt(row.data)
        data["expires_at"] = "2000-01-01T00:00:00+00:00"
        row.data = db.encrypt(data)
    assert (
        client.post(
            f"/v1/calendar/mutation-proposals/{p['id']}/confirm", json={"nonce": p["nonce"]}
        ).status_code
        == 409
    )


def test_trusted_end_reconciles_unknown_terminal(client):
    cid = active(client)
    event(client, "connection_lost")
    assert event(client, "urgent").status_code == 409
    assert event(client, "ended", estimated_cost_paise=1400).status_code == 200
    assert client.get(f"/v1/calls/{cid}").json()["phase"] == "ENDED"
    assert client.get("/v1/budget/current").json()["estimated_paise"] == 1400
    assert client.get("/v1/budget/current").json()["reserved_paise"] == 0


def test_calendar_concurrent_edit_and_create_collision(client):
    body = calendar_payload()
    p = client.post("/v1/calendar/mutation-proposals", json=body).json()
    created = client.post(
        f"/v1/calendar/mutation-proposals/{p['id']}/confirm", json={"nonce": p["nonce"]}
    ).json()
    collision = client.post(
        "/v1/calendar/mutation-proposals", json={**body, "event_id": created["event_id"]}
    ).json()
    assert (
        client.post(
            f"/v1/calendar/mutation-proposals/{collision['id']}/confirm", json={"nonce": collision["nonce"]}
        ).status_code
        == 409
    )
    edit = {**body, "operation": "edit", "event_id": created["event_id"], "source_etag": created["etag"]}
    proposals = [
        client.post("/v1/calendar/mutation-proposals", json={**edit, "title": f"Edit {i}"}).json()
        for i in range(2)
    ]

    def confirm(p):
        return client.post(
            f"/v1/calendar/mutation-proposals/{p['id']}/confirm", json={"nonce": p["nonce"]}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, proposals)) == [200, 409]


def test_join_token_rejected_after_call_ends(client):
    cid = active(client)
    p = client.post(
        f"/v1/calls/{cid}/takeover-intents",
        json={"device_id": "test-device", "idempotency_key": "ended-test"},
    ).json()
    event(client, "ended")
    assert (
        client.post(
            f"/v1/simulator/takeover/{p['intent_id']}/consume", json={"nonce": p["join_token"]}
        ).status_code
        == 409
    )
