# AdvisorLens roadmap — November 7, 2026

## Product direction

An advisor workspace for understanding a household, reviewing financial evidence,
preparing conversations, and following through on decisions. Initial audience hypothesis:
advisors working with households approaching or entering retirement. Validate this with
additional practitioners; one classroom presentation is not market validation.

Practitioner research emphasized priorities, account ownership, realistic spending,
irregular expenses, tax context, risk capacity versus tolerance, and team follow-through.
These are workflow insights, not universal investment recommendations. Raw transcripts,
identifying anecdotes and photographed client values are not repository fixtures.

## Completed increments

1. Portfolio data integrity: normalized exposure, input validation, immutable analyses.
2. Advisor review queue: saved statuses, internal notes, decision history, concurrency protection.
3. Household foundation: members, goals, manual account inventory with
   ownership/dates, current cash flow, explicit unknowns and estimates, version history,
   and frozen household context attached to an analysis. No changes to existing engine rules.
4. Approved client reports: explicit selection of follow-ups and household context,
   separate client-facing text, exact preview and approval with source-version checks,
   immutable stored exports, and confirmation before permanent household attachment.
   See [CLIENT-REPORTS.md](CLIENT-REPORTS.md).

5. Demo access protection: shared-password sign-in with sealed, expiring sessions,
   server-side sign-out revocation, CSRF and origin checks, login throttling, an
   allowlisted server-side proxy holding a backend secret, and a default-deny API.
   Suitable for a small advisor demonstration with fictional data; see [DEPLOY.md](../DEPLOY.md).

Next: deploy the protected demo from `main`, then run the practitioner validation below.

## Build next

1. **Cash-flow and resilience extension:** liabilities, benefit changes at retirement,
   income start/end dates, insurance inventory and accessible reserves. Clarify current
   versus retirement-period cash flow; avoid automatic product recommendations.
2. **Household portfolio scope:** account identifiers and valuation dates in the holdings
   contract, reconcile imported holdings to selected accounts, distinguish tax container
   from investment structure. Manual balances and imported portfolios must never be added
   together as independent assets. Inventory totals are not net worth.
3. **Current versus proposed:** advisor-entered targets, full-precision calculations,
   percentage-point differences, dollar changes, rationale, constraints, explicit scope
   (same account / household / rollover), and saved comparisons. No assumed access to
   private investments; private equity remains visible as equity risk. Display rounding
   must not silently modify underlying allocations.
4. **Retirement scenarios:** separately tested deterministic cash-flow engine before
   Monte Carlo. Make cash-flow timing, inflation, fees, returns and reserve funding explicit.
   Compare strategies using equal starting resources. Preserve distinction between
   arithmetic/geometric returns and return sequencing with withdrawals.
5. **Meeting preparation and team workflow:** selected context in client-facing reports,
   action owners, due dates, review reminders. Add simple task fields earlier when useful.
   Require explicit approval of what leaves the internal workspace.

## Required before real-client use

Individual advisor authentication and per-user authorization on every data/report endpoint
(the current shared demo password is not this), advisor/firm isolation, privacy controls,
production request limits, retention policy, and a restore drill on the deployed environment
(backup/restore tooling exists and is tested automatically; see DEPLOY.md).
An “owner” in a household means financial account ownership, not access authorization.
No real client information belongs in this demo. Frameworks or banned-phrase checks do
not establish regulatory compliance.

## Completion gates for each increment

- Check financial examples independently; never promote a transcript error to a rule.
- Validate unknown versus zero, period conversions, ownership, duplicate counts,
  missing dates and contradictory inputs.
- Preserve historical analysis/brief inputs when context changes.
- Test the end-to-end browser path, responsive layout, API errors and stale edits.
- Record actual checks in the PR; do not label unexecuted checks as passed.
- Use synthetic cases and identify remaining limitations.

## Practitioner validation questions

What takes the most preparation time? Which inputs are usually missing or unreliable?
Where do agreed actions get delayed? Test a fictional case with an advisor and observe
where they need to leave AdvisorLens to complete the meeting workflow.
