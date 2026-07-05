# AdvisorLens

AdvisorLens is an AI-assisted **portfolio review support tool for financial advisors**.
Phase 1 lets a user upload (or pick) a **synthetic** portfolio CSV, runs **deterministic
analysis rules**, shows a dashboard of summary metrics and advisor review items, and
stores every analysis with an audit trail — preparing the data foundation for a future
AI-generated Client Portfolio Review Brief.

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
| Storage   | SQLite (analyses + append-only audit log) |
| Tests     | pytest (52 tests)                         |

shadcn/ui, Markdown/HTML brief export, and integrations (FMP/Plaid/SnapTrade/Langfuse)
are deliberately deferred beyond Phase 1.

## Project structure

```
backend/
  app/
    ingestion.py    # CSV parsing + validation (schema, numerics, enums)
    analytics.py    # total value, asset/sector allocation, top holdings, unrealized G/L
    rules.py        # deterministic risk rules -> Flags with evidence + thresholds
    compliance.py   # banned-phrase guard applied to every generated flag
    db.py           # SQLite: analyses + audit_log
    service.py      # ingest -> summarize -> rules -> persist pipeline
    main.py         # FastAPI endpoints
  tests/            # pytest suite
frontend/           # Next.js dashboard (sample picker, upload, summary, flags)
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

## Deterministic rules (Phase 1)

| rule_id                        | Trigger                                              | Severity |
|--------------------------------|------------------------------------------------------|----------|
| `concentration_single_holding` | Any single non-cash holding > 20% of portfolio       | high     |
| `concentration_sector`         | Any non-cash sector > 35% of portfolio               | medium   |
| `cash_drag`                    | Cash > 10% of portfolio                              | medium   |
| `risk_tolerance_mismatch`      | Conservative profile with equity > 60% of portfolio  | high     |
| `tax_review_taxable_loss`      | Unrealized loss in a **taxable** account             | info     |

Retirement accounts never trigger tax-loss review language — enforced in the rule,
re-checked by the compliance guard, and covered by tests.

## Sample portfolios

| File                        | Demonstrates                                                        |
|-----------------------------|---------------------------------------------------------------------|
| `growth_concentrated.csv`   | Single-holding concentration (NVDA 24%), Technology sector 56%, taxable loss note |
| `conservative_mismatch.csv` | Conservative profile with 70% equity, taxable loss note (IRA losses correctly ignored) |
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
curl localhost:8000/analyses          # saved analyses
curl localhost:8000/analyses/1        # full record incl. audit log
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest
```

## Storage & audit

Each analysis is saved to SQLite (`backend/advisorlens.db`, created on first run) with the
source filename, file SHA-256, engine version, client profile, full summary, and all flags.
An append-only `audit_log` records completion events (including which rules fired) and
rejected ingestions with their validation errors.

## Phase 2 candidates (not built)

- AI-generated Client Portfolio Review Brief (Markdown/HTML export first, PDF later)
- shadcn/ui component polish, saved-analyses history view in the UI
- Real market data (FMP), account aggregation (Plaid/SnapTrade), LLM observability (Langfuse)
- Authentication and multi-user support
