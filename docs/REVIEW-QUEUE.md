# Advisor review queue — implementation notes

This increment builds on the data-integrity branch, without merging it or deploying.

## Shipped behavior

- One saved status and note per analysis/finding; stable identities include the immutable analysis ID and original finding.
- Four statuses with a required note for resolution; reopening is allowed and recorded.
- Atomic state, revision snapshot, and audit-log persistence. No update/delete endpoint for decision history.
- Optimistic concurrency inside a serialized SQLite write transaction. Stale requests cannot overwrite notes.
- Accessible labels, saved-status filters/counts, explicit save, unsaved/error/conflict states, and expandable evidence/history.
- Existing analyses gain the workflow without migration of their financial data.
- Top-holdings table scrolls locally on narrow screens.

## Scope boundaries

Notes remain internal, separate from client reports and LLM input. Household entities,
review ownership/authentication, valuation dates, follow-up due dates, and explicit
selection of notes for a meeting report are later increments. Existing generated briefs
remain cached financial snapshots; review edits do not imply their text changed.

## Verification

19 workflow tests cover persistence, isolation between analyses/findings, validation,
unknown records, no-op saves, concurrent writers, transactional rollback, legacy tables,
and exclusion of internal notes from briefs. Frontend lint and production build pass.
The full local run has 147 passing tests and five pre-existing PDF failures caused by
blocked Chromium execution. No tests were disabled to conceal this limitation.

The browser acceptance script and GitHub workflow provision a browser and exercise the
working UI plus PDF export. Their execution status is reported in the PR; adding the
script alone does not prove browser verification passed.
