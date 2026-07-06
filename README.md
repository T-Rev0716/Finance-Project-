# AdvisorLens

AdvisorLens is an AI-assisted **portfolio review support tool for financial advisors**.
Upload (or pick) a **synthetic** portfolio CSV, run **deterministic analysis rules**, review
a dashboard of summary metrics and advisor review items, browse saved analyses, and generate
an advisor-presentable **Client Portfolio Review Brief** with Markdown, HTML, and
print-ready PDF export. Every analysis is stored with an audit trail.

> **Compliance posture**
> - Synthetic sample data only — no real client data, no brokerage connections, no market data APIs.
> - Advisor-support language only (*review, evaluate, consider, may indicate*). Output never
>   contains direct-advice language; a runtime guard and tests enforce a banned-phrase list
>   (buy, sell, guaranteed, risk-free, best investment, will outperform).
> - Every finding traces back to the uploaded file (SHA-256 recorded) and a named
>   deterministic rule with its threshold and evidence values.
> - This is an advisor-support tool, **not** a robo-advisor, and does not provide investment,
>   tax, or legal advice.

## Stack

| Layer     | Choice                                   |
|-----------|------------------------------------------|
| Frontend  | Next.js 16 (App Router) + Tailwind CSS 4 |
| Backend   | FastAPI (Python 3.11)                     |
| Analytics | Pandas                                    |
| Storage   | SQLite (analyses + briefs + append-only audit log) |
| PDF export| Headless Chromium via Playwright (renders the same HTML template) |
| LLM (optional) | OpenAI-compatible `/chat/completions` provider behind the `GENERATORS` registry |
| Tests     | pytest (108 tests)                        |

shadcn/ui and integrations (FMP/Plaid/SnapTrade/Langfuse) are deliberately deferred. The
brief generator is deterministic by default; an optional LLM generator (`llm-v1`) drafts
narrative language only and requires no API keys unless explicitly enabled.

## Project structure

```
backend/
  app/
    ingestion.py    # CSV parsing + validation (schema, numerics, enums)
    analytics.py    # total value, asset/sector allocation, top holdings, unrealized G/L
    rules.py        # deterministic review rules -> Flags with evidence + thresholds
    compliance.py   # banned-phrase guard applied to every generated flag and brief
    brief.py        # Client Portfolio Review Brief generators + Markdown/HTML rendering
    llm.py          # optional LLM config (env) + OpenAI-compatible/mock providers
    llm_brief.py    # llm-v1: input packet, prompt, validation + fact-token guard
    pdf_export.py   # renders the brief's HTML export to PDF via headless Chromium
    db.py           # SQLite: analyses + briefs + audit_log
    service.py      # ingest -> summarize -> rules -> persist pipeline
    main.py         # FastAPI endpoints
  tests/            # pytest suite
frontend/           # Next.js dashboard (analyze, saved-analyses history, review brief)
data/samples/       # 3 synthetic portfolio CSVs
```

## Portfolio CSV format

One row per holding:

```
ticker,security_name,asset_class,sector,shares,market_value,cost_basis,account_type,risk_tolerance,client_goal
```

- `asset_class`: Equity, Fixed Income, Cash, …
- `account_type`: Taxable / Individual / Joint (taxable) or Traditional IRA / Roth IRA / 401k / 403b / Rollover IRA (retirement)
- `risk_tolerance`: Conservative, Moderate, Aggressive
- Market value is the authoritative amount; percentages are of total portfolio market value.

## Five advisor review rules plus one compliance guardrail

| rule_id                        | Trigger                                              | Severity |
|--------------------------------|------------------------------------------------------|----------|
| `concentration_single_holding` | Any single non-cash holding > 20% of portfolio       | high     |
| `concentration_sector`         | Any non-cash sector > 35% of portfolio               | medium   |
| `cash_drag`                    | Cash > 10% of portfolio                              | medium   |
| `risk_tolerance_mismatch`      | Conservative profile with equity > 60% of portfolio  | high     |
| `tax_review_taxable_loss`      | Unrealized loss in a **taxable** account (surfaced as a "tax-related review consideration") | info |

**Compliance guardrail (not a user-facing review flag):** retirement accounts never
receive tax review language — enforced inside the rule, re-checked by the runtime
compliance guard, and covered by tests.

## Sample portfolios

| File                        | Demonstrates                                                        |
|-----------------------------|---------------------------------------------------------------------|
| `growth_concentrated.csv`   | Single-holding concentration (NVDA 24%), Technology sector 56%, tax-related review consideration |
| `conservative_mismatch.csv` | Conservative profile with 70% equity, tax-related review consideration (IRA losses correctly ignored) |
| `retiree_cash_drag.csv`     | 18% cash (cash drag) and a retirement-account loss that produces no tax language |

## Running it

Backend (port 8000):

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend (port 3000):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, pick a sample or upload a CSV.

API without the frontend:

```bash
curl -X POST localhost:8000/analyze/sample/growth_concentrated.csv
curl localhost:8000/analyses                       # saved analyses
curl localhost:8000/analyses/1                     # full record incl. audit log
curl localhost:8000/analyses/1/brief               # generate/view review brief (cached)
curl -X POST localhost:8000/analyses/1/brief       # force regenerate
curl localhost:8000/analyses/1/brief/markdown      # Markdown export (download)
curl localhost:8000/analyses/1/brief/html          # printable HTML export
curl localhost:8000/analyses/1/brief/pdf -o brief.pdf   # PDF export (download)
```

PDF export renders the same HTML template through headless Chromium (via Playwright),
so the two stay visually consistent by construction. It needs a Chromium binary — run
`playwright install chromium` after installing requirements, or set
`ADVISORLENS_CHROMIUM_PATH` to point at one already installed elsewhere.

Tests:

```bash
cd backend && .venv/bin/python -m pytest
```

## Client Portfolio Review Brief

Generated per analysis (`GET /analyses/{id}/brief`, cached in SQLite; `POST` regenerates)
with nine sections: Executive Summary, Portfolio Snapshot, Key Review Items, Advisor
Talking Points, Client Discussion Questions, Follow-Up Items, Evidence Table, Data
Assumptions, and Compliance Disclaimer.

Grounding guarantees (tested):
- Built **only** from the stored analysis record — summary, flags, evidence, and audit
  metadata. Review items in the brief are exactly the stored flags, in order.
- Every review item and evidence row carries its rule ID and threshold.
- All brief text passes the banned-phrase compliance guard at generation time.
- Tax items use "tax-related review consideration" wording, and the brief states it is
  not tax, legal, or investment advice.

The History tab lists every saved analysis with a Generated / Not generated brief status
badge, plus Open, a Generate Brief / View Brief action (label reflects that status), and
Export Markdown / Export HTML / Export PDF actions per row — every export generates the
brief on first request if one doesn't exist yet.

## Optional LLM-backed briefs (llm-v1)

The `GENERATORS` registry has a second entry, `llm-v1`, which asks an LLM to **rewrite the
narrative language only** — deterministic rules remain the source of truth, and this does not
turn AdvisorLens into a robo-advisor. It is a compliance-conscious MVP feature, not a
production compliance system.

**Deterministic stays the default.** `llm-v1` runs only when explicitly requested via
`POST /analyses/{id}/brief?generator=llm-v1` or `ADVISORLENS_BRIEF_GENERATOR=llm-v1` —
never merely because credentials are configured. With no environment variables set, the
app is fully deterministic and needs no API keys.

Configuration (environment variables only; no secrets are ever stored or logged):

| Variable | Meaning |
|---|---|
| `ADVISORLENS_LLM_PROVIDER` | `openai-compatible` (any `/chat/completions` endpoint: OpenAI, Hermes, gateways) or `mock` (keyless test/demo provider) |
| `ADVISORLENS_LLM_MODEL` | model name passed to the endpoint |
| `ADVISORLENS_LLM_API_KEY` | bearer token (required for `openai-compatible`) |
| `ADVISORLENS_LLM_BASE_URL` | endpoint base, default `https://api.openai.com/v1` |
| `ADVISORLENS_LLM_TIMEOUT_SECONDS` | request timeout, default 30 |
| `ADVISORLENS_BRIEF_GENERATOR` | default generator override (`deterministic-v1` or `llm-v1`) |

Grounding and safety (all tested):
- The model receives a **normalized input packet** (analysis metadata, summary, flags with
  rule IDs/thresholds/evidence) and may return only the five narrative sections as strict JSON.
- Portfolio snapshot, evidence table, data assumptions, and the compliance disclaimer are
  copied **verbatim from the deterministic generator** — the model cannot alter them.
- Validation compares the output back against the packet: exact 1:1 rule-ID mapping (no
  invented or dropped review items), a stricter banned-phrase list (adds should invest,
  tax-loss harvesting, harvest losses, execute trades, rebalance now, hold, …), and a
  **fact-token guard**: any dollar amount, percentage, ticker-like symbol, or snake_case
  identifier in the narrative must already appear in the packet.
- Any provider error, invalid JSON, or validation failure falls back safely to the
  deterministic brief, stored as `deterministic-fallback-after-llm-failure` with the reason
  in `generator_metadata` and in the audit log (prompt version only — never prompt text or
  keys). The UI shows a subtle "Generated with deterministic fallback" note.

## Storage & audit

Each analysis is saved to SQLite (`backend/advisorlens.db`, created on first run) with the
source filename, file SHA-256, engine version, client profile, full summary, and all flags.
Generated briefs are stored in a `briefs` table. An append-only `audit_log` records
completion events (including which rules fired), brief generations, and rejected
ingestions with their validation errors.

## Phase 3C+ candidates (not built)

- Real provider verification against a live LLM endpoint; an Anthropic-native provider
- LLM observability (Langfuse) and prompt iteration
- shadcn/ui component polish
- Real market data (FMP), account aggregation (Plaid/SnapTrade)
- Authentication and multi-user support
