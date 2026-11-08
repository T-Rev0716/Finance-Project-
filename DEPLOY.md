# Deploying AdvisorLens

> **Do not deploy publicly yet.** The API has no authentication: anyone who finds the
> backend URL can read every analysis, internal review note, household profile and approved
> report. Interface and API access protection is the next planned increment
> (see [docs/ROADMAP.md](docs/ROADMAP.md)); the steps below assume it is in place.

Two services, deployed separately, wired together by two environment variables:

- **Backend** (FastAPI + SQLite) → [Railway](https://railway.app), via the
  `backend/Dockerfile` + `railway.json` already in this repo.
- **Frontend** (Next.js) → [Vercel](https://vercel.com), zero-config.

Both support git-based continuous deployment: once connected, every push to
your branch redeploys automatically, so you keep developing locally/here and
the live site stays in sync. Deploying is not a one-way door — nothing below
stops you from continuing to iterate afterward.

## Why this pairing

- Vercel is the native host for Next.js (built by the same team, detects it
  with zero config).
- Railway runs the backend as a long-lived container with a persistent
  volume. AdvisorLens currently stores everything (analyses, briefs, the
  audit log) in a single SQLite file — most serverless hosts give you an
  ephemeral filesystem that wipes that file on every redeploy. A Railway
  volume keeps it around. (If you outgrow SQLite later, the DB layer is
  isolated in `backend/app/db.py` — swapping in Postgres is a separate,
  bigger task, not needed for now.)

## 1. Deploy the backend (Railway)

1. [railway.app](https://railway.app) → New Project → **Deploy from GitHub
   repo** → pick this repo.
2. Railway should detect `railway.json` at the repo root and build
   `backend/Dockerfile` automatically. If it instead tries Nixpacks, open
   the service's **Settings → Build**, set Builder to **Dockerfile**, and
   set the Dockerfile path to `backend/Dockerfile` (build context stays the
   repo root — the Dockerfile deliberately `COPY`s both `backend/` and the
   sibling `data/` directory, so don't set a Root Directory override here).
3. **Settings → Networking → Generate Domain** to get a public URL
   (`https://<something>.up.railway.app`). Note it — the frontend needs it.
4. **Add a volume**: Settings → Volumes → New Volume, mount path `/data`.
5. **Variables**, add:
   - `ADVISORLENS_DB` = `/data/advisorlens.db`
   - `ADVISORLENS_CORS_ORIGINS` = (leave blank for now; you'll set this in
     step 3 below once the frontend URL exists)
   - Optional, only if you want the live LLM-backed brief generator
     (`llm-v1`) rather than the deterministic one: `ADVISORLENS_LLM_PROVIDER`,
     `ADVISORLENS_LLM_MODEL`, `ADVISORLENS_LLM_BASE_URL`,
     `ADVISORLENS_LLM_API_KEY`, `ADVISORLENS_LLM_TIMEOUT_SECONDS` — see
     `backend/.env.example`.
6. Deploy. Check it came up: `curl https://<your-backend>.up.railway.app/health`.

## 2. Deploy the frontend (Vercel)

1. [vercel.com](https://vercel.com/new) → Import the same GitHub repo.
2. In the import screen, set **Root Directory** to `frontend`. Vercel
   auto-detects the Next.js build/output settings from there.
3. **Environment Variables**: add `NEXT_PUBLIC_API_URL` =
   `https://<your-backend>.up.railway.app` (the URL from step 1.3 — no
   trailing slash).
4. Deploy. Vercel gives you `https://<something>.vercel.app`.

## 3. Close the loop: allow the frontend origin in CORS

Back in Railway → your backend service → **Variables**, set
`ADVISORLENS_CORS_ORIGINS` to the Vercel URL from step 2.4 (comma-separate
multiple origins, e.g. if you later add a custom domain too). Railway
redeploys automatically on variable changes.

Open the Vercel URL for the landing page, then `/workspace` — the workspace
should hit the Railway API and work exactly like the local dev setup.

## Ongoing development

Both platforms redeploy on every push to the connected branch. Local dev
(`npm run dev` / `uvicorn --reload`) is unaffected and still points at
`localhost:8000` by default — the env vars above only matter for the
deployed copies. Preview deployments (Vercel does this per-PR automatically;
Railway can be configured similarly under Settings → PR Previews) are worth
turning on once you're iterating on real feedback, so you can test a branch
live before merging it.
