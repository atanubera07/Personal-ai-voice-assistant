from datetime import timedelta

import pytest
from test_workflows import active

from app.db import Call, Recording
from app.domain import Problem, now
from app.recordings import RecordingStore


def test_refused_consent_creates_no_file(client, tmp_path):
    cid = active(client, False)
    db = client.app.state.db
    store = RecordingStore(db, tmp_path / "audio")
    with db.transaction() as s:
        with pytest.raises(Problem):
            store.start(s, s.get(Call, cid))
    assert list(store.root.iterdir()) == []


def test_stop_blocks_frames_and_expiry_preserves_summary(client, tmp_path):
    cid = active(client, True)
    db = client.app.state.db
    store = RecordingStore(db, tmp_path / "audio")
    end = now()
    with db.transaction() as s:
        call = s.get(Call, cid)
        call.private = db.encrypt({"summary": "Keep summary"})
        rid = store.start(s, call)
        store.append(s, rid, b"private audio frame")
        assert b"private audio frame" not in store.path(rid).read_bytes()
        assert store.stop(s, rid)
        with pytest.raises(Problem):
            store.start(s, call)
        with pytest.raises(Problem):
            store.append(s, rid, b"human audio")
        store.end(s, rid, end)
    assert store.expire(end + timedelta(days=29))["deleted"] == 0
    assert store.expire(end + timedelta(days=30))["deleted"] == 1
    assert store.expire(end + timedelta(days=31))["deleted"] == 0
    assert not store.path(rid).exists()
    with db.transaction() as s:
        assert s.get(Recording, rid).receipt.startswith("local-object-absent:")
        assert db.decrypt(s.get(Call, cid).private)["summary"] == "Keep summary"


def test_failed_delete_not_reported_as_success(client, tmp_path, monkeypatch):
    cid = active(client, True)
    db = client.app.state.db
    store = RecordingStore(db, tmp_path / "audio")
    with db.transaction() as s:
        rid = store.start(s, s.get(Call, cid))
        store.stop(s, rid)
        store.end(s, rid, now() - timedelta(days=31))
    from pathlib import Path

    with monkeypatch.context() as patch:

        def failed(*args, **kwargs):
            raise OSError("Storage unavailable")

        patch.setattr(Path, "unlink", failed)
        assert store.expire()["failed"] == 1
    with db.transaction() as s:
        assert s.get(Recording, rid).state == "DELETE_FAILED"
        assert s.get(Recording, rid).receipt is None
    assert store.expire()["deleted"] == 1
