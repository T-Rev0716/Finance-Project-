# Dependency follow-up — November 7, 2026

The household increment's installation exposed existing advisories in Next.js 16.2.10
and transitive packages. Upgraded Next.js and eslint-config-next together to 16.4.5,
and applied compatible transitive updates with `npm audit fix` (no force/major downgrade).

Primary release information:
https://github.com/vercel/next.js/releases/tag/v16.4.5

Local checks after the update: frontend lint and production build passed;
`npm audit --omit=dev --json` reported zero known vulnerabilities.
This is an advisory database check, not proof that the application is secure.

Eight moderate development-tool advisory entries remain through the lint dependency
chain (typescript-eslint -> minimatch, GHSA-g3hv-75wg-m249). npm proposes a major downgrade
of eslint-config-next to 15.5.29; that was not applied. These entries are tracked for an
upstream-compatible update. They are not reported in the production-only dependency audit.

CI captures the full advisory report as evidence. That reporting step is non-blocking
because development advisories are documented; the functional/backend/browser gates are
blocking. A separate production-only dependency audit is also blocking. No real-client readiness is implied: authentication, authorization and production
data protections are separate outstanding roadmap work.

## Sample-report follow-up

The sample PDF was successfully regenerated and compared with the existing fictional
repository report: extracted-text changes were only generation timestamps and engine
version 0.1.0 -> 0.1.1. Automatic approval review nevertheless rejected uploading the
refreshed PDF as potentially sensitive derived financial data without explicit user
authorization. Published sample assets remain unchanged. CI still checks PDF rendering
but does not upload the generated PDF as an artifact. The sample refresh remains blocked
pending explicit approval; this does not block the household workflow.
