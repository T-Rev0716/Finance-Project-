"""Demo access protection: default-deny API, sessions, throttling, configuration."""
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import main, security
from tests.conftest import (
    AUTH_HEADERS,
    BACKEND_DIR,
    TEST_BACKEND_SECRET,
    TEST_PASSWORD,
    TEST_SESSION_ID,
    api_client,
)

PATH_VALUES = {"analysis_id": "1", "report_id": "1", "household_id": "1", "fmt": "pdf",
               "format": "pdf", "finding_id": "a" * 24, "name": "growth_concentrated.csv"}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "security.db"
    monkeypatch.setattr(main, "DB_PATH", path)
    return path


def _protected_routes():
    # The public OpenAPI generator sees every route, including ones added via include_router.
    for path, operations in main.app.openapi()["paths"].items():
        if path in security.PUBLIC_PATHS:
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: PATH_VALUES[m.group(1)], path)
        for method in sorted(operations):
            yield method.upper(), concrete


def test_route_inventory_is_not_vacuous():
    routes = list(_protected_routes())
    assert len(routes) >= 25
    paths = {p for _, p in routes}
    for expected in ["/analyze/upload", "/analyses/1/brief/pdf", "/reports/1/pdf", "/households",
                     "/analyses/1/reports", "/auth/login", "/generator"]:
        assert expected in paths


@pytest.mark.parametrize("headers", [
    {},
    {security.SECRET_HEADER: "wrong-secret-0123456789abcdefghijklmnopqrstuv"},
    {security.SECRET_HEADER: TEST_BACKEND_SECRET[:-1]},
    {"authorization": f"Bearer {TEST_BACKEND_SECRET}"},  # only the dedicated header is accepted
], ids=["missing", "wrong", "truncated", "wrong-header"])
def test_every_route_except_health_rejects_bad_backend_credentials(headers, isolated_db):
    client = TestClient(main.app, headers=headers)
    for method, path in _protected_routes():
        r = client.request(method, path)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["x-advisorlens-auth"] == "credentials"
        assert r.headers["cache-control"] == "no-store"
    with closing(sqlite3.connect(isolated_db)) as conn:  # Rejected before any handler ran.
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "analyses" in tables:
            assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def test_health_is_public_and_minimal():
    r = TestClient(main.app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_unauthenticated_upload_is_rejected_before_parsing(isolated_db):
    body = b"x" * 3_000_000
    r = TestClient(main.app).post("/analyze/upload", files={"file": ("big.csv", body, "text/csv")})
    assert r.status_code == 401


def test_secret_alone_is_not_enough_for_data_routes():
    client = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    for method, path in _protected_routes():
        r = client.request(method, path)
        if path == security.LOGIN_PATH:
            assert r.status_code == 422  # Reaches validation: no session exists before login.
        else:
            assert r.status_code == 401 and r.headers["x-advisorlens-auth"] == "session", (method, path)


@pytest.mark.parametrize("session_id", ["short", "x" * 129, "has space-0123456789", "bad/char-0123456789"])
def test_malformed_session_ids_are_rejected(session_id):
    client = TestClient(main.app, headers={**AUTH_HEADERS, security.SESSION_HEADER: session_id})
    assert client.get("/analyses").status_code == 401


@pytest.mark.parametrize("issued_at", [None, "", "abc", "0", "-5", "nan", "inf"])
def test_missing_or_malformed_session_issue_time_is_rejected(issued_at):
    headers = {k: v for k, v in AUTH_HEADERS.items() if k != security.ISSUED_HEADER}
    if issued_at is not None:
        headers[security.ISSUED_HEADER] = issued_at
    r = TestClient(main.app, headers=headers).get("/analyses")
    assert r.status_code == 401 and r.headers["x-advisorlens-auth"] == "session"


def test_logout_revokes_that_session_only(isolated_db):
    client = api_client()
    assert client.get("/auth/session").status_code == 204
    assert client.post("/auth/logout", json={"expires_at": time.time() + 3600}).status_code == 204
    for method, path in [("GET", "/analyses"), ("GET", "/auth/session"), ("GET", "/reports/1/pdf"),
                         ("POST", "/analyze/sample/growth_concentrated.csv")]:
        r = client.request(method, path)
        assert r.status_code == 401 and r.headers["x-advisorlens-auth"] == "session", path
    other = TestClient(main.app, headers={**AUTH_HEADERS, security.SESSION_HEADER: "another-session-0123456789"})
    assert other.get("/analyses").status_code == 200
    with closing(sqlite3.connect(isolated_db)) as conn:  # Only a hash of the session ID is stored.
        stored = [r[0] for r in conn.execute("SELECT session_key FROM revoked_sessions")]
    assert stored and TEST_SESSION_ID not in stored


def test_expired_revocations_are_cleaned_up(isolated_db):
    security.revoke_session(isolated_db, "old-session-0123456789", expires_at=100.0, now=50.0)
    security.revoke_session(isolated_db, "new-session-0123456789", expires_at=time.time() + 60)
    assert not security.is_revoked(isolated_db, "old-session-0123456789")
    assert security.is_revoked(isolated_db, "new-session-0123456789")


def test_previous_secret_is_accepted_only_during_rotation(monkeypatch):
    new_secret = "rotated-backend-secret-0123456789abcdefghijk"
    monkeypatch.setenv("ADVISORLENS_BACKEND_SECRET", new_secret)
    monkeypatch.setenv("ADVISORLENS_BACKEND_SECRET_PREVIOUS", TEST_BACKEND_SECRET)
    old = TestClient(main.app, headers=AUTH_HEADERS)
    new = TestClient(main.app, headers={**AUTH_HEADERS, security.SECRET_HEADER: new_secret})
    assert old.get("/analyses").status_code == 200 and new.get("/analyses").status_code == 200
    monkeypatch.delenv("ADVISORLENS_BACKEND_SECRET_PREVIOUS")
    assert old.get("/analyses").status_code == 401 and new.get("/analyses").status_code == 200


def _login(client, password=TEST_PASSWORD, client_key="203.0.113.10"):
    return client.post("/auth/login", json={"password": password, "client": client_key})


def test_login_accepts_only_the_demo_password(isolated_db):
    client = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    before = time.time()
    body = _login(client).json()
    assert body["ok"] is True and before <= body["issued_at"] <= time.time()
    r = _login(client, "wrong-password")
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect password."
    with closing(sqlite3.connect(isolated_db)) as conn:  # Client addresses are stored hashed.
        keys = {r[0] for r in conn.execute("SELECT client_key FROM login_attempts")}
    assert "203.0.113.10" not in keys and len(keys) == 1


def test_repeated_failures_throttle_that_client(isolated_db):
    client = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    for _ in range(security.MAX_CLIENT_FAILURES):
        assert _login(client, "wrong-password").status_code == 401
    blocked = _login(client)  # Even the correct password is not checked while throttled.
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.json()["detail"]["retry_after"] == int(blocked.headers["retry-after"])
    assert _login(client, client_key="198.51.100.7").status_code == 200  # Other clients unaffected.


def test_success_resets_the_client_counter(isolated_db):
    client = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    for _ in range(security.MAX_CLIENT_FAILURES - 1):
        _login(client, "wrong-password")
    assert _login(client).status_code == 200
    for _ in range(security.MAX_CLIENT_FAILURES - 1):
        assert _login(client, "wrong-password").status_code == 401
    assert _login(client).status_code == 200


def test_global_failure_cap_applies_across_clients(isolated_db, monkeypatch):
    monkeypatch.setattr(security, "MAX_GLOBAL_FAILURES", 3)
    client = TestClient(main.app, headers={security.SECRET_HEADER: TEST_BACKEND_SECRET})
    for i in range(3):
        assert _login(client, "wrong-password", f"192.0.2.{i}").status_code == 401
    assert _login(client, client_key="192.0.2.99").status_code == 429


def test_throttle_window_expires(isolated_db):
    config = security.load_config()
    t0 = 1_000_000.0
    for i in range(security.MAX_CLIENT_FAILURES):
        assert security.attempt_login(isolated_db, "wrong", "c", config, now=t0 + i) is False
    with pytest.raises(security.LoginThrottled):
        security.attempt_login(isolated_db, TEST_PASSWORD, "c", config, now=t0 + 10)
    later = t0 + security.MAX_CLIENT_FAILURES + security.LOGIN_WINDOW_SECONDS + 1
    assert security.attempt_login(isolated_db, TEST_PASSWORD, "c", config, now=later) is True


def test_docs_are_disabled_outside_development():
    client = TestClient(main.app, headers=AUTH_HEADERS)
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert TestClient(main.app).get(path).status_code == 401
        assert client.get(path).status_code == 404
    assert security.docs_enabled({"ADVISORLENS_ENV": "development"}) is True
    assert security.docs_enabled({"ADVISORLENS_ENV": "production"}) is False
    assert security.docs_enabled({}) is False  # Unset means production.


def test_incomplete_configuration_denies_access_in_development(monkeypatch):
    monkeypatch.setenv("ADVISORLENS_ENV", "development")
    monkeypatch.delenv("ADVISORLENS_BACKEND_SECRET")
    client = TestClient(main.app, headers=AUTH_HEADERS)
    assert client.get("/analyses").status_code == 503
    assert client.post("/auth/login", json={"password": TEST_PASSWORD, "client": "x"}).status_code == 503
    assert client.get("/health").status_code == 200


VALID_HASH = os.environ["ADVISORLENS_DEMO_PASSWORD_HASH"]


@pytest.mark.parametrize("environ, message", [
    ({"ADVISORLENS_BACKEND_SECRET": "short", "ADVISORLENS_DEMO_PASSWORD_HASH": VALID_HASH}, "at least 32"),
    ({"ADVISORLENS_BACKEND_SECRET": "REPLACE_ME_with_a_long_random_value_0123456789",
      "ADVISORLENS_DEMO_PASSWORD_HASH": VALID_HASH}, "placeholder"),
    ({"ADVISORLENS_BACKEND_SECRET": TEST_BACKEND_SECRET, "ADVISORLENS_DEMO_PASSWORD_HASH": "plaintext"}, "hash"),
    ({"ADVISORLENS_BACKEND_SECRET": TEST_BACKEND_SECRET, "ADVISORLENS_DEMO_PASSWORD_HASH": VALID_HASH,
      "ADVISORLENS_BACKEND_SECRET_PREVIOUS": TEST_BACKEND_SECRET}, "differ"),
    ({"ADVISORLENS_ENV": "staging"}, "ADVISORLENS_ENV"),
    ({}, "ADVISORLENS_BACKEND_SECRET"),
])
def test_invalid_configuration_is_rejected(environ, message):
    with pytest.raises(security.SecurityConfigError, match=message):
        security.load_config(environ)


def _import_app(env_overrides: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ADVISORLENS_")}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND_DIR, env=env,
                          capture_output=True, text=True, timeout=60)


def test_production_refuses_to_start_without_valid_protection():
    missing = _import_app({"ADVISORLENS_ENV": "production"})
    assert missing.returncode != 0 and "ADVISORLENS_BACKEND_SECRET" in missing.stderr
    unset_env = _import_app({})  # No ADVISORLENS_ENV at all is treated as production.
    assert unset_env.returncode != 0
    placeholder = _import_app({"ADVISORLENS_ENV": "production", "ADVISORLENS_DEMO_PASSWORD_HASH": VALID_HASH,
                               "ADVISORLENS_BACKEND_SECRET": "replace_me_0123456789012345678901234567"})
    assert placeholder.returncode != 0 and "placeholder" in placeholder.stderr
    valid = _import_app({"ADVISORLENS_ENV": "production", "ADVISORLENS_DEMO_PASSWORD_HASH": VALID_HASH,
                         "ADVISORLENS_BACKEND_SECRET": TEST_BACKEND_SECRET})
    assert valid.returncode == 0, valid.stderr


def test_password_hash_cli_and_verification():
    r = subprocess.run([sys.executable, "-m", "app.security", "hash-password"], cwd=BACKEND_DIR,
                       input="correct horse battery\n", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    encoded = r.stdout.strip()
    assert encoded.startswith("scrypt$") and "correct horse" not in encoded
    assert security.verify_password("correct horse battery", encoded)
    assert not security.verify_password("correct horse battery!", encoded)
    assert not security.verify_password("anything", "scrypt$1$1$1$x$y")
    short = subprocess.run([sys.executable, "-m", "app.security", "hash-password"], cwd=BACKEND_DIR,
                           input="short\n", capture_output=True, text=True, timeout=60)
    assert short.returncode != 0
