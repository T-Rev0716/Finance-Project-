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
| Sign-out | Revokes that session ID on the API (stored hashed in SQLite until it would have expired), then clears the cookie. A copied cookie stops working everywhere. If the request does not reach the server, or the API cannot record the revocation, the page says "You are still signed in", keeps the cookie and offers **Try sign-out again**; it never reports a sign-out that did not happen. |
| Restore | Restoring a backup ends every session issued before the restore, including sessions signed out after the backup was taken (whose revocations the backup does not contain). Everyone signs in again. |
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
SQLite's online backup API (safe while the API runs). Every source is opened read-only and
must already exist, so a mistyped path fails instead of creating an empty database. Before
anything is written, the source must pass SQLite's integrity check and match the
AdvisorLens schema; the new file is then validated again before it replaces anything. On
any failure the command exits non-zero and the destination is unchanged.

```bash
# Back up (from a Railway shell: `railway ssh`, or Settings → Shell):
python /app/backend/scripts/backup_db.py backup --db /data/advisorlens.db \
  --out /data/backups/advisorlens-$(date +%Y%m%d-%H%M%S).db
# Copy it off the volume as well (paths are relative to the volume root; get the volume
# ID from `railway volume list --json`), then compare `sha256sum` with the copy on the volume:
railway volume files --volume <volume-id> download /backups/<file>.db ./<file>.db

# Check any copy:
python /app/backend/scripts/backup_db.py verify --db /data/backups/<file>.db
```

### Restore

Replace the database only when nothing else can be using it. A paused, idle or unreachable
API is not enough: `kill -STOP` freezes a process but leaves its connections and SQLite
locks in place, an idle API opens a new connection with its next request, and routing the
domain away stops new public requests without showing that requests already in progress, or
callers on another route, have finished. Each step below ends the procedure if its check
fails: put traffic back and stop rather than working around it.

> **Railway: in-place restore is currently blocked.** Step 3 cannot be done on the Railway
> service as deployed. Railway reaches a volume's files only through a running deployment
> of the service it is attached to (`railway ssh`, SFTP/SCP, `railway volume files`); that
> deployment's start command is the API (`backend/Dockerfile`), so stopping the API stops
> the container and the shell with it; and a service with a volume cannot run a second
> replica or deployment alongside it. There is no state in which the API has exited and the
> database is still reachable. Do not restore the live Railway database in place until such
> a maintenance state exists and has been rehearsed on a copy of the service. Candidates,
> none built or tested: an API maintenance mode that answers 503 without opening the
> database, a deployment whose start command does not run the API, or restoring onto a new
> service and volume and switching over. Backups (above) and step 2 work on Railway today.

Elsewhere the procedure needs a host where the API can be stopped while a shell in the same
process namespace can still reach the database (for example a VM that runs the API under a
service manager).

1. **Check the backup you will restore from**, before touching traffic:

   ```bash
   python /app/backend/scripts/backup_db.py verify --db /data/backups/<restore-from>.db
   ```

2. **Block new requests** and keep the hostname that the frontend's `ADVISORLENS_BACKEND_URL`
   points at. On Railway, route the domain to a port nothing listens on, then confirm there
   is no other way in:

   ```bash
   railway domain list --service <service> --json      # note the domain id and targetPort
   railway domain update <domain-id> --port 9 --service <service>
   curl -s -o /dev/null -w '%{http_code}\n' https://<name>.up.railway.app/health   # expect 502
   railway tcp-proxy list --service <service> --json   # expect no proxies
   railway service list --json                         # expect no other service that could call it privately
   ```

   Elsewhere, take the API out of the load balancer or close its port the same way. A 502
   shows that new public requests are refused, nothing more.

3. **Let requests in progress finish, then stop the API.** Stop it with SIGTERM and enough
   grace time, never SIGKILL or SIGSTOP: uvicorn then stops accepting connections, finishes
   the requests in progress and exits. Make sure nothing restarts it. The maintenance state
   is reached once the API process has exited. **On Railway, stop here** (see above) and put
   the port back: `railway domain update <domain-id> --port <original-targetPort> --service <service>`.

4. **Back up the current database outside the live path** now that nothing writes to it, and
   keep a verified copy off the host. The `advisorlens.db.pre-restore-<timestamp>` file the
   restore leaves next to the live one is not verified and does not count.

   ```bash
   python /app/backend/scripts/backup_db.py backup --db /data/advisorlens.db \
     --out /data/backups/before-restore-$(date +%Y%m%d-%H%M%S).db
   python /app/backend/scripts/backup_db.py verify --db /data/backups/before-restore-<timestamp>.db
   sha256sum /data/backups/before-restore-<timestamp>.db
   # Copy it off the host, check that the copy's sha256sum matches, then verify the copy:
   python backend/scripts/backup_db.py verify --db ./before-restore-<timestamp>.db
   ```

5. **Confirm exclusive access and restore in one command**, so the restore runs only if the
   check passes:

   ```bash
   python /app/backend/scripts/backup_db.py preflight --db /data/advisorlens.db && \
   python /app/backend/scripts/backup_db.py restore --db /data/advisorlens.db \
     --from /data/backups/<restore-from>.db
   ```

   `preflight` exits non-zero, and nothing is restored, if any process cannot be inspected
   (including on a host without `/proc`), the API (`uvicorn`) is still running, any process
   has `advisorlens.db` or its `-journal`, `-wal` or `-shm` file open, or SQLite's exclusive
   lock is not free at once. It sees only its own PID namespace, so run it on the host where
   the API ran and make sure no other host or container has the volume mounted. If it fails,
   deal with the cause it names; never restore without it passing.

6. **Start the API and check it with traffic still blocked.** Start it the way the host
   normally does, confirm the running API process started after the restore finished, then
   on the host:

   ```bash
   python /app/backend/scripts/backup_db.py verify --db /data/advisorlens.db   # counts as restore printed
   python -c 'import urllib.request as u; print(u.urlopen("http://127.0.0.1:8000/health").read())'  # API port
   ```

   If a check fails, keep traffic blocked and go back to step 3, restoring the step 4 backup.

7. **Let traffic back in** (on Railway, put the original `targetPort` back as in step 3), sign
   in through the frontend and confirm the analyses list. If that fails, block traffic again
   and go back to step 3.

A restore records the restore time in the restored database, and the API then rejects
every session issued before it, so everyone signs in again. Run the restore on the API host,
whose clock sets that cutoff. No secret rotation is needed for this; still rotate the session
secret if you restored because of a suspected compromise.

Covered by `backend/tests/test_backup.py` (round trip, previous file kept, no overwrite of
existing backups, missing/empty/foreign/corrupt sources rejected with the destination
unchanged, signed-out sessions not revived by a restore; `preflight` refusing while the API
runs, while a process holds the database or a journal file, when processes cannot be
inspected and when the exclusive lock is taken) and by the browser harness (back up, sign
out, restore, then replay the signed-out cookie). Practice a restore before relying on it; a
backup you have not restored is unproven.

#### Railway restore drill, 2026-11-08 (earlier procedure, superseded)

A restore was rehearsed on the live demo (commit `cbe1767`) with the procedure this section
replaces. The domain was routed to port 9 (`/health` returned 502), a backup was downloaded
with `railway volume files download` and its hash checked, and the idle API turned out to
still hold two to three handles on `/data/advisorlens.db` (a connection leak in `db.py`,
since fixed). The API process was then frozen with `kill -STOP`, the restore was run, and
the service was restarted and the port put back. The drill showed that the backup, download
and traffic-routing commands work on Railway. It did not show that the restore was safe: the
frozen process kept its connections and any locks, and the 502 did not prove that no request
was still in progress. The procedure above has not been run on Railway, and it cannot be
completed there until the blocker is resolved.

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
- Sign-out needs the API. While it is unreachable a session cannot be revoked and stays
  valid until it expires or is revoked later; rotate the session secret to end every
  session without the API.
