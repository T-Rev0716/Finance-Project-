# Approved client reports

Open an analysis in the workspace, generate its review brief, then use **Client report**.

## Workflow

1. **Draft.** Edit a client-facing summary (prefilled from the analysis, separate from
   internal notes). Select findings to include as follow-ups and write client-facing text for
   each. Internal review notes are shown to the advisor as "not included"; they only reach a
   report if the advisor explicitly copies them into client text. Household context
   (priorities, goals, account inventory) is included only when selected, and only from the
   snapshot permanently attached to the analysis.
2. **Preview.** The server builds the report and returns its HTML plus a SHA-256 digest of
   the content and its source references (analysis, brief ID, review revisions, household
   version). Any draft edit clears the preview.
3. **Approve.** The server rebuilds the report from current records. If the digest differs
   (draft edited, newer brief, review revision changed, household snapshot mismatch), it
   returns 409 and nothing is saved; the advisor reloads sources and previews again.
   Otherwise it stores the content, sources, and rendered Markdown/HTML/PDF bytes.
4. **Download.** `/reports/{id}/{format}` returns the stored bytes, so downloads are
   byte-for-byte identical however sources change later.

## Guarantees and their enforcement

| Guarantee | Enforcement |
|---|---|
| Approved content and files never change | SQLite triggers abort any UPDATE/DELETE on `approved_reports` and `approved_report_files`; exports are served from stored bytes |
| Approval matches the preview | Digest re-derived at approval and again under the write lock |
| Unselected notes/context stay out | Report content is built only from selected IDs and advisor-written text; tests scan Markdown, HTML and extracted PDF text |
| Analyzed CSV kept separate from household inventory | Every report states the file it analyzed and that it may not cover every account; inventory is labelled advisor-entered and not reconciled, never added to portfolio totals; unknown balances show "Not established" |
| Brief history preserved | Existing brief endpoints unchanged; regeneration still appends; each report cites the brief ID it used |
| Client-facing wording | Advisor-written summary and follow-up text pass the base banned-phrase check (422 otherwise) |

The approval stamp ("Approved client report #N · time · digest") is the only difference
between the previewed and approved renderings. PDF rendering happens during approval; if it
fails, nothing is approved.

## API

- GET `/analyses/{id}/reports/draft` — latest brief ID, default summary, review items
  (with internal notes for the advisor's screen), attached household summary
- POST `/analyses/{id}/reports/preview` — draft → `{preview_sha256, content, sources, html}`
- POST `/analyses/{id}/reports` — `{draft, preview_sha256}` → approved record (201) or 409
- GET `/analyses/{id}/reports`, GET `/reports/{report_id}`
- GET `/reports/{report_id}/{markdown|html|pdf}` — stored bytes, `X-Content-SHA256` header

## Limitations

- No authentication or authorization; approval records no actor identity. Do not deploy
  this publicly until the protected-demo increment lands.
- Review-item messages come from the existing engine and are phrased for the advisor
  ("consider reviewing … with the client"). Engine wording is unchanged in this increment.
- Household account inventory is not reconciled with imported holdings; the report says so
  rather than attempting reconciliation.
- Approval holds the SQLite write lock while the PDF renders (about 1–2 s), serializing
  concurrent approvals. Acceptable for the demo; revisit with a production database.
