import json
from dataclasses import replace

import httpx
import pytest
from test_workflows import calendar_payload

from app.domain import Problem
from app.google_calendar import GoogleCalendar


def adapter(client, handler):
    settings = replace(
        client.app.state.settings,
        calendar_provider="google",
        google_client_id="test",
        google_client_secret="test",
        google_refresh_token="test",
    )

    def transport(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer fake-token"
        return handler(request)

    return GoogleCalendar(settings, httpx.Client(transport=httpx.MockTransport(transport)))


def test_google_stable_create_reconciles_lost_response(client):
    events, posts = {}, []

    def handler(request):
        eid = request.url.path.split("/")[-1]
        if request.method == "GET":
            return httpx.Response(200, json=events[eid]) if eid in events else httpx.Response(404)
        if request.method == "POST":
            data = json.loads(request.content)
            data["etag"] = "etag-1"
            events[data["id"]] = data
            posts.append(data)
            raise httpx.ReadTimeout("Simulated response lost")
        raise AssertionError(request.method)

    google = adapter(client, handler)
    body = {**calendar_payload(), "event_id": None, "source_etag": None, "attendees": []}
    with pytest.raises(Problem) as exc:
        google.write(None, body, "12345678-1234-1234-1234-123456789012")
    assert exc.value.code == "CALENDAR_PENDING"
    result = google.write(None, body, "12345678-1234-1234-1234-123456789012")
    assert result["verified"] and not result["simulation"]
    assert len(posts) == 1


def test_google_edit_if_match_and_stale_rejection(client):
    body = {
        **calendar_payload(),
        "operation": "edit",
        "event_id": "event",
        "source_etag": "old",
        "attendees": [],
    }

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"etag": "old"})
        assert request.method == "PATCH"
        assert request.headers["if-match"] == "old"
        return httpx.Response(412)

    google = adapter(client, handler)
    with pytest.raises(Problem) as exc:
        google.write(None, body, "stable-id")
    assert exc.value.code == "CALENDAR_STALE"


def test_google_preview_read_only_and_calendar_scope(client):
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(
            200, json={"items": [{"id": "busy", "start": {"dateTime": "start"}, "end": {"dateTime": "end"}}]}
        )

    google = adapter(client, handler)
    assert len(google.preview(calendar_payload())["conflicts"]) == 1
    assert calls == ["GET"]
    with pytest.raises(Problem) as exc:
        google.preview({**calendar_payload(), "calendar_id": "other"})
    assert exc.value.code == "CALENDAR_FORBIDDEN"


def test_google_transient_failure_not_success(client):
    google = adapter(client, lambda request: httpx.Response(429))
    with pytest.raises(Problem) as exc:
        google.preview(calendar_payload())
    assert exc.value.code == "CALENDAR_PENDING"


def test_reconcile_cannot_bypass_confirmation(client):
    proposal = client.post("/v1/calendar/mutation-proposals", json=calendar_payload()).json()
    response = client.post(f"/v1/calendar/mutation-proposals/{proposal['id']}/reconcile")
    assert response.status_code == 409
    assert client.get("/v1/calendar/pending").json()["items"] == []
