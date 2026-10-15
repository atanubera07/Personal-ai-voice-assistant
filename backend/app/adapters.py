"""Capability boundaries: deliberately no selected production telecom or speech vendor."""

import hashlib
from typing import Protocol

from .domain import Problem


class TelephonyProvider(Protocol):
    async def route_to_fallback(self, call_id: str, reason: str) -> str: ...
    async def prepare_owner_leg(self, call_id: str, token: str) -> str: ...
    async def stop_recording(self, call_id: str) -> bool: ...
    async def bridge(self, call_id: str, owner_leg: str) -> bool: ...
    async def delete_recording(self, call_id: str) -> str: ...


class UnqualifiedProvider:
    async def route_to_fallback(self, call_id, reason):
        raise Problem("PROVIDER_UNVERIFIED", "G0–G6 must pass before live routing", 503)


class CalendarAdapter(Protocol):
    def get(self, session, calendar_id: str, event_id: str) -> dict: ...
    def write(self, session, proposal: dict, stable_id: str) -> dict: ...


class SimulatedCalendar:
    """Durable fake calendar for confirmation/ETag tests. Never touches Google."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def key(calendar_id, event_id):
        return "calendar:" + hashlib.sha256((calendar_id + "\0" + event_id).encode()).hexdigest()

    def get(self, session, calendar_id, event_id):
        from .db import Policy

        row = session.get(Policy, self.key(calendar_id, event_id))
        return self.db.decrypt(row.data) if row else {}

    def write(self, session, proposal, stable_id):
        import secrets

        from sqlalchemy import select

        from .db import Policy
        from .domain import require

        eid = proposal.get("event_id") or stable_id.replace("-", "")
        key = self.key(proposal["calendar_id"], eid)
        row = session.execute(select(Policy).where(Policy.id == key).with_for_update()).scalar_one_or_none()
        if proposal["operation"] == "create":
            require(row is None, "CALENDAR_EXISTS", "An event with this ID already exists")
        current = self.db.decrypt(row.data) if row else {}
        if proposal["operation"] != "create":
            require(
                current.get("etag") == proposal["source_etag"],
                "CALENDAR_STALE",
                "Event changed; confirm a fresh proposal",
            )
        if proposal["operation"] == "delete":
            session.delete(row)
            return {"event_id": eid, "deleted": True, "simulation": True}
        result = {**proposal, "event_id": eid, "etag": secrets.token_hex(12), "simulation": True}
        if row:
            row.data = self.db.encrypt(result)
        else:
            session.add(Policy(id=key, data=self.db.encrypt(result)))
        return result
