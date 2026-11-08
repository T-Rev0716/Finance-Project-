# Deploying the AdvisorLens demo

AdvisorLens deploys as a **password-protected, shared demo workspace with fictional data**.
Everyone admitted with the demo password sees and edits the same analyses, households,
review notes and reports. This is not individual advisor authentication, per-user
authorization or firm isolation — do not enter real client information.

## Architecture

```
Browser ──HTTPS──▶ Next.js (Vercel)  ──HTTPS + backend secret + session ID──▶ FastAPI (Railway)
                   • sign-in page, sealed session cookie                     • rejects anything without the secret
                   • /api/* proxy: allowlisted routes only                    • revoked-session list, login throttle
                   • origin + CSRF checks on every change                     • SQLite on a persistent volume
```

- The browser only talks to the Next.js site. All data requests and report downloads go
  through its authenticated `/api/*` routes, which forward a fixed list of routes and
  methods to one configured backend URL. The backend secret is a server-only variable: it
  never appears in browser JavaScript, URLs, responses or logs.
- The API rejects every request without the backend secret (401), except a minimal public
  `GET /health` that returns `{"status": "ok"}`. API docs (`/docs`, `/openapi.json`) are
  disabled outside `ADVISORLENS_ENV=development`. CORS is not used: browsers never call the
  API directly.
- Misconfiguration fails closed: a production API with a missing, short or placeholder secret
  or password hash **refuses to start**; a frontend with missing or invalid configuration
  **denies** every protected page and API route. There is no unprotected fallback.

## Sessions

| Topic | Behavior |
|---|---|
| Sign-in | `/login` with the shared demo password. The API checks it against a scrypt hash. |
| Cookie | Sealed (encrypted + authenticated) with `iron-session`. `HttpOnly`, `SameSite=Lax`, `Path=/`; in production also `Secure` with the `__Host-` prefix. |
| Expiration | Absolute: `ADVISORLENS_SESSION_TTL_HOURS` (default 8) after sign-in, not extended by activity. Expired cookies are treated as signed out. |
| Tampering | A modified or forged cookie fails authentication and is treated as signed out. |
| Sign-out | Revokes that session ID on the API (stored hashed in SQLite until it would have expired) and clears the cookie. A copied cookie stops working everywhere. |
| Revoke everyone | Rotate `ADVISORLENS_SESSION_SECRET` (see below): every existing cookie becomes invalid. |
| Password change | Generate a new hash and update the API. Existing sessions continue until they expire unless you also rotate the session secret. |
| CSRF | Every state-changing request needs both the site's own `Origin` and a per-session CSRF token header. Cross-origin form posts and fetches are refused with 403. |
| Login throttling | Kept in the API's SQLite database, so it holds across serverless frontend instances: 5 failures per client per 15 minutes, 100 failures across all clients per 15 minutes. While throttled, even the correct password is refused (429 with `Retry-After`). Client addresses are stored hashed. |

Per-client throttling keys on the platform's `X-Forwarded-For`, which is only trustworthy
behind a proxy that overwrites it (Vercel does). Set `ADVISORLENS_TRUST_PROXY_HEADERS=true`
only there; otherwise all clients share one throttle bucket (an attacker can then delay
everyone's sign-in for up to 15 minutes, but cannot guess faster). The global cap applies
either way.

## 0. Before you start

1. **Deployment branch.** Deploy `main`. In GitHub → Settings → General → *Default branch*,
   select `main` (it currently still points at an older branch). Configure both hosting
   projects below to deploy from `main` explicitly — changing GitHub's default branch does
   not change an existing hosting project's production branch.
2. **Generate secrets** (keep them in a password manager; never commit them):

   ```bash
   # Two different random values, each at least 32 characters:
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # backend secret
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # session secret
   # Demo password hash (prompts for a password of at least 12 characters):
   cd backend && .venv/bin/python -m app.security hash-password
   ```

## 1. Backend (Railway)

1. New Project → **Deploy from GitHub repo** → this repo. In the service's **Settings →
   Source**, set the branch to `main`. `railway.json` builds `backend/Dockerfile`
   (build context is the repo root; do not set a Root Directory override).
2. **Volume:** Settings → Volumes → New Volume, mount path `/data`.
3. **Variables:**

   | Variable | Value |
   |---|---|
   | `ADVISORLENS_ENV` | `production` (also the default when unset) |
   | `ADVISORLENS_DB` | `/data/advisorlens.db` |
   | `ADVISORLENS_BACKEND_SECRET` | backend secret |
   | `ADVISORLENS_DEMO_PASSWORD_HASH` | the `scrypt$…` hash |
   | `ADVISORLENS_LLM_*` | optional; see `backend/.env.example` |

4. **Networking → Generate Domain** (`https://<name>.up.railway.app`).
5. Deploy and check:

   ```bash
   curl https://<name>.up.railway.app/health        # {"status":"ok"}
   curl -i https://<name>.up.railway.app/analyses   # 401 — protected
   ```

   If the deploy fails to start, read the log: the API names the missing or invalid
   security variable rather than starting unprotected.

## 2. Frontend (Vercel)

1. Import the repo, **Root Directory** `frontend`. In **Settings → Git**, set the
   **Production Branch** to `main`.
2. **Environment Variables** (Production; none of these may be prefixed `NEXT_PUBLIC_`):

   | Variable | Value |
   |---|---|
   | `ADVISORLENS_ENV` | `production` |
   | `ADVISORLENS_BACKEND_URL` | `https://<name>.up.railway.app` (origin only, no path) |
   | `ADVISORLENS_BACKEND_SECRET` | the same backend secret |
   | `ADVISORLENS_SESSION_SECRET` | session secret (different from the backend secret) |
   | `ADVISORLENS_PUBLIC_ORIGIN` | the site's exact public origin, e.g. `https://<app>.vercel.app` |
   | `ADVISORLENS_TRUST_PROXY_HEADERS` | `true` (Vercel overwrites `X-Forwarded-For`) |
   | `ADVISORLENS_SESSION_TTL_HOURS` | optional, default `8` |

   `ADVISORLENS_PUBLIC_ORIGIN` must match the address people use. If you add a custom
   domain, update it; requests from any other origin are refused. Preview deployments
   have their own URLs, so they will refuse changes unless configured with their own
   origin — keep previews pointed at a separate backend or leave them unconfigured
   (unconfigured means denied, not open).
3. Deploy, then open `https://<app>.vercel.app/workspace`: you should be sent to `/login`.
   Sign in with the demo password and run a sample analysis.

## Secret rotation

- **Backend secret** (no downtime):
  1. On Railway set `ADVISORLENS_BACKEND_SECRET_PREVIOUS` to the current value and
     `ADVISORLENS_BACKEND_SECRET` to a new one; redeploy. Both are accepted.
  2. On Vercel set `ADVISORLENS_BACKEND_SECRET` to the new value; redeploy.
  3. On Railway delete `ADVISORLENS_BACKEND_SECRET_PREVIOUS`; redeploy.
- **Session secret**: set a new `ADVISORLENS_SESSION_SECRET` on Vercel and redeploy. Every
  existing session is invalidated (everyone signs in again). Use this to revoke all access.
- **Demo password**: generate a new hash, update `ADVISORLENS_DEMO_PASSWORD_HASH` on
  Railway, redeploy. Rotate the session secret too if earlier sessions must end now.
- If a secret may have leaked, rotate it immediately, then review the `audit_log` table
  for `demo_login_*` events.

## Backups and restore

All state is one SQLite file on the Railway volume. `backend/scripts/backup_db.py` uses
SQLite's online backup API (safe while the API runs) and verifies the result.

```bash
# Back up (from a Railway shell: `railway ssh`, or Settings → Shell):
python /app/backend/scripts/backup_db.py backup --db /data/advisorlens.db \
  --out /data/backups/advisorlens-$(date +%Y%m%d-%H%M%S).db
# Copy it off the volume as well, e.g. `railway ssh -- cat <file> > local.db`.

# Check any copy:
python /app/backend/scripts/backup_db.py verify --db /data/backups/<file>.db

# Restore: stop traffic first (Railway: remove the domain or scale the service to 0
# replicas from a one-off shell), then:
python /app/backend/scripts/backup_db.py restore --db /data/advisorlens.db \
  --from /data/backups/<file>.db
# The current file is kept as advisorlens.db.pre-restore-<timestamp>. Restart the service
# and confirm the analyses list in the workspace.
```

The round trip (backup → later writes → restore → earlier state, previous file kept,
no overwrite of existing backups) is covered by `backend/tests/test_security.py`.
Practice a restore before relying on it; a backup you have not restored is unproven.

## Local development and tests

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to
`frontend/.env.local`, fill in the placeholders with locally generated values
(`ADVISORLENS_ENV=development`), then:

```bash
cd backend && set -a && . ./.env && set +a && .venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Automated tests and the browser harness use explicit test credentials
(`ADVISORLENS_ENV=test`; random per harness run) and need no configuration.

## Remaining limitations

- One shared password and one shared workspace; no per-person accounts, audit identity,
  roles or tenant isolation.
- No production request rate limiting beyond sign-in throttling; add platform-level limits
  before wider exposure.
- No retention policy beyond keeping everything; delete the volume data when the demo ends.
