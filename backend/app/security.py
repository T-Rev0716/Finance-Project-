"""Access control for the shared fictional-data demo workspace.

Browsers never call this API directly: the Next.js server holds the backend secret
and the signed session, and forwards a fixed set of routes. Every route except the
minimal `/health` check requires the backend secret; every route except login also
requires the caller's session ID, which is refused after logout (server-side
revocation list). This is shared-password demo access, not individual advisor
authentication or tenant isolation: all admitted users share one workspace.

Generate a password hash with:  python -m app.security hash-password
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from . import db

ENVIRONMENTS = ("production", "development", "test")
SECRET_HEADER = "x-advisorlens-backend-secret"
SESSION_HEADER = "x-advisorlens-session"
MIN_SECRET_LENGTH = 32
PUBLIC_PATHS = frozenset({"/health"})
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
LOGIN_PATH = "/auth/login"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

LOGIN_WINDOW_SECONDS = 15 * 60
MAX_CLIENT_FAILURES = 5
MAX_GLOBAL_FAILURES = 100
MAX_SESSION_LIFETIME_SECONDS = 2 * 24 * 3600

_SCRYPT_R, _SCRYPT_P = 8, 1
_SCRYPT_N = 2**14
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_PLACEHOLDER_PREFIX = "replace_me"


class SecurityConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityConfig:
    environment: str
    secrets: tuple[bytes, ...]  # current first, then the optional previous one
    password_hash: str


# --- Password hashing (stdlib scrypt) ------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, n: int = _SCRYPT_N) -> str:
    if not password:
        raise ValueError("Password must not be empty.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=_SCRYPT_R, p=_SCRYPT_P,
                            maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${n}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _parse_hash(encoded: str):
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, digest = _unb64(parts[4]), _unb64(parts[5])
    except ValueError:
        return None
    if n < 2**12 or n > 2**17 or n & (n - 1) or r < 1 or r > 32 or p < 1 or p > 4:
        return None
    if len(salt) < 16 or len(digest) != 32:
        return None
    return n, r, p, salt, digest


def verify_password(password: str, encoded: str) -> bool:
    parsed = _parse_hash(encoded)
    if parsed is None:
        return False
    n, r, p, salt, expected = parsed
    actual = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=32)
    return hmac.compare_digest(actual, expected)


# --- Configuration ---------------------------------------------------------------

def environment(environ=None) -> str:
    environ = os.environ if environ is None else environ
    value = environ.get("ADVISORLENS_ENV", "production").strip().lower()
    if value not in ENVIRONMENTS:
        raise SecurityConfigError(f"ADVISORLENS_ENV must be one of {', '.join(ENVIRONMENTS)}.")
    return value


def _secret_errors(name: str, value: str) -> list[str]:
    if len(value) < MIN_SECRET_LENGTH:
        return [f"{name} must be at least {MIN_SECRET_LENGTH} characters."]
    if value.lower().startswith(_PLACEHOLDER_PREFIX):
        return [f"{name} still contains the placeholder value."]
    if not value.isascii() or any(c.isspace() for c in value):
        return [f"{name} must be printable ASCII without spaces."]
    return []


@lru_cache(maxsize=8)
def _load(env_name: str, secret: str, previous: str, password_hash: str) -> SecurityConfig:
    errors = _secret_errors("ADVISORLENS_BACKEND_SECRET", secret)
    if previous:
        errors += _secret_errors("ADVISORLENS_BACKEND_SECRET_PREVIOUS", previous)
        if previous == secret:
            errors.append("ADVISORLENS_BACKEND_SECRET_PREVIOUS must differ from the current secret.")
    if _parse_hash(password_hash) is None:
        errors.append("ADVISORLENS_DEMO_PASSWORD_HASH must be a hash from `python -m app.security hash-password`.")
    if errors:
        raise SecurityConfigError(" ".join(errors))
    keys = tuple(s.encode() for s in (secret, previous) if s)
    return SecurityConfig(env_name, keys, password_hash)


def load_config(environ=None) -> SecurityConfig:
    environ = os.environ if environ is None else environ
    return _load(
        environment(environ),
        environ.get("ADVISORLENS_BACKEND_SECRET", ""),
        environ.get("ADVISORLENS_BACKEND_SECRET_PREVIOUS", ""),
        environ.get("ADVISORLENS_DEMO_PASSWORD_HASH", ""),
    )


def startup_check(environ=None) -> str:
    """Refuse to start a production API without valid access protection.

    Development and test may start with incomplete configuration so the error is
    visible, but every protected request is then denied (503), never allowed.
    """
    env = environment(environ)
    if env == "production":
        load_config(environ)
    return env


def docs_enabled(environ=None) -> bool:
    return environment(environ) == "development"


# --- Login throttling and session revocation ----------------------------------

class LoginThrottled(Exception):
    def __init__(self, retry_after: int):
        super().__init__("Too many failed sign-in attempts.")
        self.retry_after = retry_after


def _client_key(client: str) -> str:
    # Stored hashed: the throttle only needs equality, not the address itself.
    return hashlib.sha256(client.encode()).hexdigest()


def attempt_login(db_path, password: str, client: str, config: SecurityConfig, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    since = now - LOGIN_WINDOW_SECONDS
    key = _client_key(client)
    with closing(db._connect(db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE created_at < ?", (now - 24 * 3600,))
        last_success = conn.execute(
            "SELECT MAX(created_at) FROM login_attempts WHERE client_key = ? AND succeeded = 1", (key,)
        ).fetchone()[0] or 0
        client_failures = conn.execute(
            "SELECT created_at FROM login_attempts WHERE client_key = ? AND succeeded = 0 AND created_at > ? "
            "ORDER BY created_at", (key, max(since, last_success))).fetchall()
        global_failures = conn.execute(
            "SELECT created_at FROM login_attempts WHERE succeeded = 0 AND created_at > ? ORDER BY created_at",
            (since,)).fetchall()
        for rows, limit in ((client_failures, MAX_CLIENT_FAILURES), (global_failures, MAX_GLOBAL_FAILURES)):
            if len(rows) >= limit:
                # Throttled attempts are not checked and not recorded, so waiting is the only way through.
                raise LoginThrottled(max(1, int(rows[-limit][0] + LOGIN_WINDOW_SECONDS - now) + 1))
        ok = verify_password(password, config.password_hash)
        conn.execute("INSERT INTO login_attempts (client_key, succeeded, created_at) VALUES (?, ?, ?)",
                     (key, int(ok), now))
        conn.execute("INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (NULL, ?, ?, ?)",
                     ("demo_login_succeeded" if ok else "demo_login_failed", json.dumps({}), db._now()))
    return ok


def _session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def revoke_session(db_path, session_id: str, expires_at: float, now: float | None = None) -> None:
    now = time.time() if now is None else now
    with closing(db._connect(db_path)) as conn, conn:
        conn.execute("DELETE FROM revoked_sessions WHERE expires_at < ?", (now,))
        conn.execute("INSERT OR IGNORE INTO revoked_sessions (session_key, expires_at, revoked_at) VALUES (?, ?, ?)",
                     (_session_key(session_id), expires_at, now))
        conn.execute("INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (NULL, ?, ?, ?)",
                     ("demo_session_signed_out", json.dumps({}), db._now()))


def is_revoked(db_path, session_id: str) -> bool:
    with closing(db._connect(db_path)) as conn:
        return conn.execute("SELECT 1 FROM revoked_sessions WHERE session_key = ?",
                            (_session_key(session_id),)).fetchone() is not None


# --- ASGI middleware ---------------------------------------------------------------

async def _deny(send, status: int, detail: str, auth_reason: str | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
               (b"content-length", str(len(body)).encode())]
    if auth_reason:
        headers.append((b"x-advisorlens-auth", auth_reason.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AccessControlMiddleware:
    """Default-deny: checked before routing and before any request body is read."""

    def __init__(self, app, db_path_provider):
        self.app = app
        self.db_path_provider = db_path_provider

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in PUBLIC_PATHS:
            return await self.app(scope, receive, send)
        try:
            config = load_config()
        except SecurityConfigError:
            return await _deny(send, 503, "API access protection is not configured on this server.")
        if path in DOCS_PATHS and config.environment == "development":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        provided = headers.get(SECRET_HEADER.encode(), b"")
        if not provided or not any(hmac.compare_digest(provided, key) for key in config.secrets):
            return await _deny(send, 401, "Backend credentials are missing or invalid.", "credentials")
        if path != LOGIN_PATH:
            session_id = headers.get(SESSION_HEADER.encode(), b"").decode("latin-1")
            if not SESSION_ID_RE.fullmatch(session_id):
                return await _deny(send, 401, "A signed-in session is required.", "session")
            if is_revoked(self.db_path_provider(), session_id):
                return await _deny(send, 401, "This session has been signed out. Sign in again.", "session")
        return await self.app(scope, receive, send)


# --- Routes ----------------------------------------------------------------------

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)
    client: str = Field(min_length=1, max_length=200)


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_at: float = Field(gt=0)


def router(db_path_provider) -> APIRouter:
    api = APIRouter()

    @api.post(LOGIN_PATH)
    def login(request: LoginRequest, response: Response):
        try:
            ok = attempt_login(db_path_provider(), request.password, request.client, load_config())
        except LoginThrottled as exc:
            raise HTTPException(429, {"message": "Too many failed sign-in attempts. Try again later.",
                                      "retry_after": exc.retry_after},
                                headers={"Retry-After": str(exc.retry_after)}) from exc
        if not ok:
            raise HTTPException(401, "Incorrect password.")
        response.headers["cache-control"] = "no-store"
        return {"ok": True}

    @api.post("/auth/logout", status_code=204)
    def logout(request: LogoutRequest, x_advisorlens_session: str = Header()):
        now = time.time()
        expires_at = min(max(request.expires_at, now), now + MAX_SESSION_LIFETIME_SECONDS)
        revoke_session(db_path_provider(), x_advisorlens_session, expires_at, now)
        return Response(status_code=204)

    @api.get("/auth/session", status_code=204)
    def session_status():
        # Reaching this handler means the middleware accepted the secret and the session.
        return Response(status_code=204, headers={"cache-control": "no-store"})

    return api


def _cli(argv: list[str]) -> int:
    if argv[:1] != ["hash-password"]:
        print("Usage: python -m app.security hash-password  (reads the password from stdin when piped)")
        return 2
    if sys.stdin.isatty():
        password = getpass.getpass("Demo password: ")
        if password != getpass.getpass("Repeat: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
    else:
        password = sys.stdin.readline().rstrip("\n")
    if len(password) < 12:
        print("Use a demo password of at least 12 characters.", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
