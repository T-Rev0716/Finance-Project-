# Household planning foundation

Open `/households` from the portfolio workspace. Create a blank household or use the
fictional example. Add members before assigning account owners, enter goals and dates,
and record current income/spending. Save explicitly; reload retains the saved version.

## Data and calculations

- USD only. Nonnegative decimal monetary inputs, at most two decimal places, capped at
  $1 trillion per row. Negative cash-flow balances are valid calculated shortfalls.
- Empty monetary fields persist as null, not zero. A zero must be explicitly entered.
- Each listed account is counted once regardless of the number of joint owners.
  A non-null balance requires a valuation date; mixed dates are called out.
- Manual account balances are separate from uploaded holdings, and are not net worth.
  No reconciliation or holding-level account mapping is claimed in this increment.
- Cash-flow periods are monthly or annual. Annual totals use exact Decimal arithmetic;
  monthly net is annual net / 12 rounded half-up to cents for output. Income should be
  take-home; record expenses consistently and avoid duplicate tax deductions.
- Essential, discretionary and irregular spending all count as expenses. Annual repair
  reserves are spread across 12 months. This is a current cash-flow inventory, not a
  scheduled projection. Goal amounts do not automatically count as expenses.
- A balance is withheld until the inventory is explicitly marked complete and every
  entered cash-flow amount is known. Editing a cash-flow row in the UI resets completion.
  Estimates remain visibly distinct from advisor-confirmed amounts.
- Risk tolerance is separate from capacity-for-loss notes. Neither changes engine rules.

## Persistence and historical context

`households` stores the latest profile; `household_versions` stores immutable JSON input
snapshots for each changed save. State, history and audit event use one transaction.
No-op saves create no revision. Optimistic version checks inside BEGIN IMMEDIATE prevent
stale writes. The UI preserves failed drafts and offers explicit discard/reload.

An analysis can attach one saved household version after the advisor confirms the
association. It is a permanent context link, not a statement that every account appears
in that CSV. Later profile edits cannot rewrite attached context. To use different
context, generate a new analysis and attach the correct snapshot. Original engine
findings, CSV profile values and cached briefs remain unchanged.

Household context is internal and excluded from brief generation, AI input and exports.
Version history records values/time, not an authenticated actor identity. The system
remains a fictional-data demo without authentication or tenant isolation.

## API

- GET/POST `/households`
- GET/PUT `/households/{id}` (PUT requires profile and expected_version)
- GET `/households/{id}/versions`
- GET/POST `/analyses/{id}/household` (POST requires household_id and expected_version)

Unknown records return 404, stale/conflicting associations 409, invalid inputs 422.
Tables are additive; prior analyses/reviews/briefs are not rewritten.

## Verification

29 new backend cases cover money precision, unknowns, period conversion, joint accounts,
missing/foreign owners, invalid dates, incomplete inventories, shortfalls, version
history, concurrent edits, frozen context, internal-data exclusion, rollback and legacy
schema preservation. The browser harness also exercises creation, reload, missing amounts,
inventory confirmation, history, conflict recovery, mobile width and frozen context.
See the PR for executed results; tests in source alone are not proof of execution.
