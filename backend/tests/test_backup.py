"""Backup/restore safety and post-restore session invalidation."""
import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import main, security
from tests.conftest import REPO_ROOT, TEST_BACKEND_SECRET, TEST_PASSWORD, api_client

SCRIPT = [sys.executable, str(REPO_ROOT / "backend" / "scripts" / "backup_db.py")]


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    path = tmp_path / "live.db"
    monkeypatch.setattr(main, "DB_PATH", path)
    client = api_client()
    assert client.post("/analyze/sample/growth_concentrated.csv").status_code == 200
    return path


def run(*args):
    return subprocess.run([*SCRIPT, *map(str, args)], capture_output=True, text=True, timeout=120)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_backup_and_restore_round_trip(tmp_path, live_db):
    backup = tmp_path / "backups" / "copy.db"
    r = run("backup", "--db", live_db, "--out", backup)
    assert r.returncode == 0 and "analyses=1" in r.stdout
    api_client().post("/analyze/sample/retiree_cash_drag.csv")  # Changes after the backup...
    r = run("restore", "--db", live_db, "--from", backup)
    assert r.returncode == 0, r.stderr
    assert api_client().get("/analyses").status_code == 401  # The pre-restore session is gone.
    fresh = _session("after-restore-0123456789", _sign_in(TestClient(main.app, headers={
        security.SECRET_HEADER: TEST_BACKEND_SECRET})))
    assert [a["source_name"] for a in fresh.get("/analyses").json()["analyses"]] == ["growth_concentrated.csv"]
    assert list(tmp_path.glob("live.db.pre-restore-*"))  # ...are kept aside, not destroyed.
    assert not list(tmp_path.glob("*.restore-staging")) and not list(backup.parent.glob("*.partial"))
    assert run("backup", "--db", live_db, "--out", backup).returncode != 0  # Never overwrites a backup.


def test_mistyped_source_path_creates_nothing(tmp_path, live_db):
    missing = tmp_path / "advisorlens-typo.db"
    out = tmp_path / "backups" / "copy.db"
    r = run("backup", "--db", missing, "--out", out)
    assert r.returncode == 1 and "not found" in r.stderr
    assert not missing.exists() and not out.exists() and not out.parent.exists()
    before = digest(live_db)
    r = run("restore", "--db", live_db, "--from", missing)
    assert r.returncode == 1 and not missing.exists()
    assert digest(live_db) == before and not list(tmp_path.glob("live.db.pre-restore-*"))
    assert run("verify", "--db", missing).returncode == 1 and not missing.exists()


@pytest.mark.parametrize("make", [
    lambda p: p.write_bytes(b""),                                         # empty file
    lambda p: sqlite3.connect(p).close(),                                 # empty SQLite database
    lambda p: p.write_text("not a database at all " * 100),              # not SQLite
    lambda p: _foreign_database(p),                                       # another application's data
    lambda p: _damaged_advisorlens_table(p),                              # right names, wrong shape
], ids=["empty-file", "empty-sqlite", "not-sqlite", "foreign-schema", "wrong-columns"])
def test_invalid_databases_are_never_backed_up_or_restored(tmp_path, live_db, make):
    candidate = tmp_path / "candidate.db"
    make(candidate)
    out = tmp_path / "backups" / "copy.db"
    r = run("backup", "--db", candidate, "--out", out)
    assert r.returncode == 1 and "Nothing was changed" in r.stderr
    assert not out.exists() and not list(tmp_path.rglob("*.partial"))
    before = digest(live_db)
    r = run("restore", "--db", live_db, "--from", candidate)
    assert r.returncode == 1
    assert digest(live_db) == before, "live database changed after a rejected restore"
    assert not list(tmp_path.glob("live.db.pre-restore-*")) and not list(tmp_path.glob("*.restore-staging"))
    assert len(api_client().get("/analyses").json()["analyses"]) == 1


def _foreign_database(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO customers (name) VALUES ('x')")
        conn.commit()


def _damaged_advisorlens_table(path):
    with closing(sqlite3.connect(path)) as conn:
        for table in ("analyses", "briefs", "audit_log"):
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.commit()


def test_restoring_onto_itself_is_refused(live_db):
    before = digest(live_db)
    assert run("restore", "--db", live_db, "--from", live_db).returncode == 1
    assert digest(live_db) == before


def _sign_in(client):
    body = client.post("/auth/login", json={"password": TEST_PASSWORD, "client": "198.51.100.1"}).json()
    return body["issued_at"]


def _session(session_id, issued_at):
    return TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET,
                                         security.SESSION_HEADER: session_id,
                                         security.ISSUED_HEADER: str(issued_at)})


def test_restore_invalidates_sessions_signed_out_after_the_backup(tmp_path, live_db):
    login = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    signed_out = _session("signed-out-later-0123456789", _sign_in(login))
    still_open = _session("still-open-session-0123456789", _sign_in(login))
    assert signed_out.get("/analyses").status_code == 200 and still_open.get("/analyses").status_code == 200

    backup = tmp_path / "backups" / "before-logout.db"
    assert run("backup", "--db", live_db, "--out", backup).returncode == 0
    assert signed_out.post("/auth/logout", json={"expires_at": 9e9}).status_code == 204
    assert signed_out.get("/analyses").status_code == 401

    r = run("restore", "--db", live_db, "--from", backup)
    assert r.returncode == 0, r.stderr
    assert "everyone signs in again" in r.stdout
    with closing(sqlite3.connect(live_db)) as conn:  # The restored file has no record of that sign-out...
        assert conn.execute("SELECT COUNT(*) FROM revoked_sessions").fetchone()[0] == 0
        events = [r[0] for r in conn.execute("SELECT event FROM audit_log")]
    assert "database_restored" in events
    for client in (signed_out, still_open):  # ...yet every pre-restore session is refused.
        r = client.get("/analyses")
        assert r.status_code == 401 and r.headers["x-advisorlens-auth"] == "session"
        assert "restore" in r.json()["detail"]
    fresh = _session("after-restore-session-0123456789", _sign_in(login))
    assert [a["source_name"] for a in fresh.get("/analyses").json()["analyses"]] == ["growth_concentrated.csv"]


def test_session_epoch_only_moves_forward(live_db):
    with closing(sqlite3.connect(live_db)) as conn, conn:
        security.invalidate_sessions_before(conn, 2000.0, "first")
        security.invalidate_sessions_before(conn, 1000.0, "earlier")
        assert conn.execute("SELECT not_before FROM session_epoch").fetchone()[0] == 2000.0
    assert security.session_rejection(live_db, "any-session-0123456789", 1999.0)
    assert security.session_rejection(live_db, "any-session-0123456789", 2000.0) is None
