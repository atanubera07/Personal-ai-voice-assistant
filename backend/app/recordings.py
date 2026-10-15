"""Encrypted app-owned recorder component. No production media is attached yet.

Frames are encrypted individually; no plaintext audio hits disk. A provider adapter
must prove every external recorder is also stopped before authorizing a bridge.
"""

import os
import uuid
from datetime import timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from .db import Recording
from .domain import Problem, now, require


class RecordingStore:
    def __init__(self, db, root):
        self.db = db
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, rid):
        # Only UUID object IDs, never caller-controlled paths or public URLs.
        try:
            return self.root / (str(uuid.UUID(rid)) + ".enc")
        except ValueError:
            raise Problem("INVALID_RECORDING", "Invalid recording ID", 422) from None

    def start(self, session, call):
        require(
            call.data["processing"] is True
            and call.data["consent"] is True
            and call.data["phase"] == "AI_ACTIVE"
            and call.data["recording"] == "RECORDING",
            "CONSENT_REQUIRED",
            "Explicit recording and processing consent required",
        )
        require(
            session.scalar(select(Recording.id).where(Recording.call_id == call.id)) is None,
            "RECORDER_EXISTS",
            "A recorder already exists for this call; never restart it",
        )
        rid = str(uuid.uuid4())
        # Empty file only created after the consent check.
        fd = os.open(self.path(rid), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        session.add(Recording(id=rid, call_id=call.id, state="RECORDING"))
        session.flush()
        return rid

    def append(self, session, rid, frame):
        require(0 < len(frame) <= 65536, "INVALID_FRAME", "Frame must be 1–65536 bytes")
        row = session.execute(select(Recording).where(Recording.id == rid).with_for_update()).scalar_one()
        require(row.state == "RECORDING", "RECORDING_STOPPED", "Recorder is closed")
        # Small encrypted frames bound memory use. Files are never a playable public object.
        with self.path(rid).open("ab") as handle:
            handle.write(self.db.cipher.encrypt(frame) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def stop(self, session, rid):
        row = session.execute(select(Recording).where(Recording.id == rid).with_for_update()).scalar_one()
        if row.state == "RECORDING":
            # append holds the same row lock; acknowledgement follows durable frame writes.
            row.state = "STOPPED"
        return row.state == "STOPPED"

    def end(self, session, rid, trusted_end):
        row = session.get(Recording, rid)
        require(row.state == "STOPPED", "RECORDING_ACTIVE", "Stop and flush before finalizing")
        require(trusted_end.tzinfo is not None, "INVALID_TIME", "Trusted call end must include timezone")
        row.expiry_at = (trusted_end.astimezone(timezone.utc) + timedelta(days=30)).isoformat()

    def delete(self, session, rid):
        row = session.execute(
            select(Recording).where(Recording.id == rid).with_for_update()
        ).scalar_one_or_none()
        if not row or row.state == "DELETED":
            return "DELETED"
        require(row.state != "RECORDING", "RECORDING_ACTIVE", "Stop before deleting")
        row.state = "DELETING"
        try:
            self.path(rid).unlink(missing_ok=True)
            require(not self.path(rid).exists(), "DELETE_FAILED", "Object still exists")
        except OSError:
            row.state = "DELETE_FAILED"
            row.receipt = None
            return row.state
        row.state, row.receipt = "DELETED", "local-object-absent:" + now().isoformat()
        return row.state

    def expire(self, at=None):
        at = at or now()
        counts = {"deleted": 0, "failed": 0}
        with self.db.transaction() as session:
            rows = list(
                session.scalars(
                    select(Recording).where(
                        Recording.expiry_at <= at.isoformat(), Recording.state != "DELETED"
                    )
                )
            )
            for row in rows:
                result = self.delete(session, row.id)
                counts["deleted" if result == "DELETED" else "failed"] += 1
        return counts
