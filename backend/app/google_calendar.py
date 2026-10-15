"""Single-owner Google Calendar REST adapter. No mutation occurs during preview."""

import threading
import time
from datetime import datetime
from urllib.parse import quote

import httpx

from .domain import Problem


class GoogleCalendar:
    simulation = False

    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
        self.lock = threading.Lock()
        self.access_token, self.expiry = "", 0

    def close(self):
        self.client.close()

    def token(self):
        with self.lock:
            if time.time() < self.expiry:
                return self.access_token
            try:
                response = self.client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.settings.google_client_id,
                        "client_secret": self.settings.google_client_secret,
                        "refresh_token": self.settings.google_refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                if response.status_code != 200:
                    raise Problem("CALENDAR_RECONNECT", "Google authorization requires attention", 503)
                value = response.json()
                self.access_token = value["access_token"]
                self.expiry = time.time() + max(0, min(value.get("expires_in", 3600), 3600) - 60)
                return self.access_token
            except (httpx.HTTPError, ValueError, KeyError):
                raise Problem(
                    "CALENDAR_UNAVAILABLE", "Google authorization is temporarily unavailable", 503
                ) from None

    def request(self, method, path, **kwargs):
        headers = {**kwargs.pop("headers", {}), "Authorization": "Bearer " + self.token()}
        try:
            response = self.client.request(
                method, "https://www.googleapis.com/calendar/v3/" + path, headers=headers, **kwargs
            )
        except httpx.HTTPError:
            raise Problem(
                "CALENDAR_PENDING", "Google outcome is uncertain. Retry this same confirmed proposal.", 503
            ) from None
        if response.status_code in {401, 403}:
            self.expiry = 0
            raise Problem("CALENDAR_RECONNECT", "Reconnect Google Calendar or check its permissions", 503)
        if response.status_code == 412:
            raise Problem("CALENDAR_STALE", "Event changed. Review and confirm a fresh proposal.", 412)
        if response.status_code == 429 or response.status_code >= 500:
            raise Problem(
                "CALENDAR_PENDING", "Google is temporarily unavailable. Retry this proposal later.", 503
            )
        if response.status_code not in {200, 201, 204, 404, 409, 410}:
            raise Problem(
                "CALENDAR_REJECTED", "Google rejected the requested change. Review the proposal.", 422
            )
        return response

    def path(self, calendar_id, event_id=None):
        if calendar_id != self.settings.google_calendar_id:
            raise Problem("CALENDAR_FORBIDDEN", "Only the configured owner calendar is allowed", 403)
        path = "calendars/" + quote(calendar_id, safe="") + "/events"
        return path + ("/" + quote(event_id, safe="") if event_id else "")

    def get(self, session, calendar_id, event_id):
        response = self.request("GET", self.path(calendar_id, event_id))
        if response.status_code in {404, 410}:
            return {}
        if response.status_code != 200:
            raise Problem("CALENDAR_UNAVAILABLE", "Unable to read Google event", 503)
        return response.json()

    def preview(self, proposal):
        path = self.path(proposal["calendar_id"])
        if proposal["operation"] != "create":
            current = self.get(None, proposal["calendar_id"], proposal["event_id"])
            if current.get("etag") != proposal["source_etag"]:
                raise Problem("CALENDAR_STALE", "Refresh the event before proposing a change", 412)
        response = self.request(
            "GET",
            path,
            params={
                "timeMin": proposal["start"],
                "timeMax": proposal["end"],
                "singleEvents": "true",
                "maxResults": 250,
            },
        )
        if response.status_code != 200:
            raise Problem("CALENDAR_UNAVAILABLE", "Unable to check calendar conflicts", 503)
        result = response.json()
        return {
            "conflicts": [
                {"start": item.get("start"), "end": item.get("end")}
                for item in result.get("items", [])
                if item.get("id") != proposal.get("event_id")
                and item.get("status") != "cancelled"
                and item.get("transparency") != "transparent"
            ],
            "conflicts_truncated": bool(result.get("nextPageToken")),
        }

    @staticmethod
    def matches(current, proposal, stable_id):
        try:
            return (
                current.get("extendedProperties", {}).get("private", {}).get("agentMutation") == stable_id
                and current.get("summary") == proposal["title"]
                and datetime.fromisoformat(current["start"]["dateTime"])
                == datetime.fromisoformat(proposal["start"])
                and datetime.fromisoformat(current["end"]["dateTime"])
                == datetime.fromisoformat(proposal["end"])
                and sorted(a["email"].lower() for a in current.get("attendees", []))
                == sorted(a.lower() for a in proposal["attendees"])
            )
        except (ValueError, KeyError):
            return False

    def write(self, session, proposal, stable_id):
        eid = proposal.get("event_id") or stable_id.replace("-", "")
        current = self.get(session, proposal["calendar_id"], eid)
        if self.matches(current, proposal, stable_id):
            return {"event_id": eid, "etag": current["etag"], "simulation": False, "verified": True}
        operation = proposal["operation"]
        if operation != "create":
            if operation == "delete" and not current:
                return {"event_id": eid, "deleted": True, "simulation": False}
            if current.get("etag") != proposal["source_etag"]:
                raise Problem("CALENDAR_STALE", "Event changed. Review a fresh proposal.", 412)
        elif current:
            raise Problem("CALENDAR_EXISTS", "Event ID is already in use", 409)
        path = self.path(proposal["calendar_id"], eid)
        headers = {"If-Match": proposal["source_etag"]} if operation != "create" else {}
        if operation == "delete":
            response = self.request("DELETE", path, headers=headers, params={"sendUpdates": "all"})
            if response.status_code not in {204, 404, 410}:
                raise Problem("CALENDAR_PENDING", "Deletion is not verified; retry the same proposal", 503)
            return {"event_id": eid, "deleted": True, "simulation": False}
        payload = {
            "summary": proposal["title"],
            "start": {"dateTime": proposal["start"], "timeZone": proposal["timezone"]},
            "end": {"dateTime": proposal["end"], "timeZone": proposal["timezone"]},
            "attendees": [{"email": email} for email in proposal["attendees"]],
            "extendedProperties": {
                "private": {
                    **current.get("extendedProperties", {}).get("private", {}),
                    "agentMutation": stable_id,
                }
            },
        }
        if operation == "create":
            payload["id"] = eid
            response = self.request(
                "POST", self.path(proposal["calendar_id"]), json=payload, params={"sendUpdates": "all"}
            )
        else:
            response = self.request(
                "PATCH", path, headers=headers, json=payload, params={"sendUpdates": "all"}
            )
        if response.status_code not in {200, 201, 409}:
            raise Problem("CALENDAR_PENDING", "Mutation is not verified; retry the same proposal", 503)
        # Reconcile even after insert conflict or a previous successful write with a lost response.
        result = self.get(session, proposal["calendar_id"], eid)
        if not self.matches(result, proposal, stable_id):
            raise Problem(
                "CALENDAR_PENDING", "Google read-back differs; refresh before claiming success", 503
            )
        return {"event_id": eid, "etag": result["etag"], "simulation": False, "verified": True}
