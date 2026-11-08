"use client";

import { useEffect, useRef, useState } from "react";

import { ReviewStatus, getBrief } from "@/lib/api";
import {
  ApprovedReport,
  DraftDefaults,
  ReportDraft,
  ReportError,
  ReportFormat,
  approveReport,
  getDraftDefaults,
  listReports,
  previewReport,
  reportFileUrl,
} from "@/lib/reports";

const STATUS_LABELS: Record<ReviewStatus, string> = {
  open: "Open",
  discussed: "Discussed",
  follow_up: "Follow-up",
  resolved: "Resolved",
};
const FORMATS: { format: ReportFormat; label: string }[] = [
  { format: "markdown", label: "Markdown" },
  { format: "html", label: "HTML" },
  { format: "pdf", label: "PDF" },
];
const BUTTON =
  "rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700";
const PRIMARY = `${BUTTON} bg-slate-900 text-white hover:bg-slate-700`;
const SECONDARY = `${BUTTON} border border-slate-300 bg-white hover:bg-slate-100`;
const TEXTAREA = "mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm";

interface HouseholdChoice {
  enabled: boolean;
  priorities: boolean;
  goals: boolean;
  accounts: boolean;
}
const NO_HOUSEHOLD: HouseholdChoice = { enabled: false, priorities: false, goals: false, accounts: false };

export default function ClientReportBuilder({
  analysisId,
  sourcesToken,
}: {
  analysisId: number;
  /** Incremented by the workspace when report sources change elsewhere (e.g. a household is attached). */
  sourcesToken: number;
}) {
  const [defaults, setDefaults] = useState<DraftDefaults | null>(null);
  const [summary, setSummary] = useState("");
  const [followUps, setFollowUps] = useState<Record<string, string>>({});
  const [household, setHousehold] = useState<HouseholdChoice>(NO_HOUSEHOLD);
  const [preview, setPreview] = useState<{ sha: string; html: string; draft: ReportDraft } | null>(null);
  const [reports, setReports] = useState<ApprovedReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [message, setMessage] = useState("");
  // Bumped on every draft or source change; a preview response is only accepted for the
  // revision it was requested for, so a slow response can't revive an outdated draft.
  const draftRevision = useRef(0);

  useEffect(() => {
    let active = true;
    listReports(analysisId)
      .then((list) => active && setReports(list))
      .catch(() => active && setError("Unable to load approved reports."));
    return () => {
      active = false;
    };
  }, [analysisId]);

  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : "Something went wrong.");
    setStale(e instanceof ReportError && e.status === 409);
  }

  // Any edit after a preview invalidates it, so approval can only send what was shown.
  function edit<T>(setter: (value: T) => void) {
    return (value: T) => {
      draftRevision.current += 1;
      setter(value);
      setPreview(null);
      setMessage("");
    };
  }
  const editSummary = edit(setSummary);
  const editFollowUps = edit(setFollowUps);
  const editHousehold = edit(setHousehold);

  async function loadDefaults(keepDraft: boolean) {
    draftRevision.current += 1;
    setBusy(true);
    setError(null);
    setStale(false);
    setPreview(null);
    try {
      let next = await getDraftDefaults(analysisId);
      if (next.brief_id === null) {
        await getBrief(analysisId);
        next = await getDraftDefaults(analysisId);
      }
      if (keepDraft) {
        // Keep the advisor's wording; drop selections that no longer exist.
        const ids = new Set(next.reviews.map((r) => r.finding_id));
        setFollowUps((current) => Object.fromEntries(Object.entries(current).filter(([id]) => ids.has(id))));
        const sameSnapshot =
          next.household !== null &&
          defaults?.household?.household_id === next.household.household_id &&
          defaults?.household?.version === next.household.version;
        if (!sameSnapshot) setHousehold(NO_HOUSEHOLD);
        setMessage(
          next.household && !sameSnapshot
            ? "Latest sources loaded. A household snapshot is now available; it stays excluded unless you select it."
            : "Latest sources loaded. Preview the report again before approving.",
        );
      } else {
        setSummary(next.client_summary);
        setFollowUps({});
        setHousehold(NO_HOUSEHOLD);
      }
      setDefaults(next);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  function currentDraft(): ReportDraft | null {
    if (!defaults || defaults.brief_id === null) return null;
    return {
      brief_id: defaults.brief_id,
      client_summary: summary,
      follow_ups: defaults.reviews
        .filter((r) => r.finding_id in followUps)
        .map((r) => ({ finding_id: r.finding_id, review_version: r.version, client_text: followUps[r.finding_id] })),
      household:
        household.enabled && defaults.household
          ? {
              household_id: defaults.household.household_id,
              version: defaults.household.version,
              priorities: household.priorities,
              goals: household.goals,
              accounts: household.accounts,
            }
          : null,
    };
  }

  const draft = currentDraft();
  const incomplete = !draft || !summary.trim() || Object.values(followUps).some((text) => !text.trim());

  async function runPreview() {
    if (!draft) return;
    const revision = draftRevision.current;
    setBusy(true);
    setError(null);
    setStale(false);
    setMessage("");
    try {
      const result = await previewReport(analysisId, draft);
      if (revision !== draftRevision.current) {
        setMessage("The draft changed while the preview was loading. Preview again to review the current draft.");
        return;
      }
      setPreview({ sha: result.preview_sha256, html: result.html, draft });
    } catch (e) {
      if (revision === draftRevision.current) fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!preview) return;
    setBusy(true);
    setApproving(true);
    setError(null);
    try {
      const report = await approveReport(analysisId, preview.draft, preview.sha);
      setReports((current) => [report, ...current]);
      setPreview(null);
      setMessage(`Approved report #${report.id} saved. Its downloads will not change.`);
    } catch (e) {
      setPreview(null);
      fail(e);
    } finally {
      setApproving(false);
      setBusy(false);
    }
  }

  // Context attached elsewhere refreshes sources without discarding the advisor's wording.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: refresh on external trigger token
    if (sourcesToken > 0 && defaults) loadDefaults(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourcesToken]);

  return (
    <section className="rounded-lg border bg-white p-5" aria-label="Client report">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Client report</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-600">
        Choose what the client sees. Internal advisor notes and household details stay out unless you select
        them. Approval saves exactly the previewed report, and an approved report cannot be edited afterwards.
      </p>

      {!defaults && (
        <button className={`${PRIMARY} mt-4`} disabled={busy} onClick={() => loadDefaults(false)}>
          {busy ? "Preparing…" : "Prepare client report"}
        </button>
      )}

      {defaults && (
        <fieldset disabled={approving} aria-label="Report draft" className="mt-5 min-w-0 space-y-6">
          <div>
            <label htmlFor={`report-summary-${analysisId}`} className="text-sm font-medium">
              Client-facing summary
            </label>
            <textarea
              id={`report-summary-${analysisId}`}
              className={TEXTAREA}
              rows={4}
              maxLength={4000}
              value={summary}
              onChange={(e) => editSummary(e.target.value)}
            />
          </div>

          <fieldset>
            <legend className="text-sm font-medium">Follow-ups to include</legend>
            {defaults.reviews.length === 0 && (
              <p className="mt-2 text-sm text-slate-500">No review items for this analysis.</p>
            )}
            <ul className="mt-2 space-y-3">
              {defaults.reviews.map((review) => {
                const selected = review.finding_id in followUps;
                const textId = `report-followup-${review.finding_id}`;
                return (
                  <li key={review.finding_id} className="rounded-md border border-slate-200 p-3">
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={selected}
                        onChange={(e) => {
                          const next = { ...followUps };
                          if (e.target.checked) next[review.finding_id] = "";
                          else delete next[review.finding_id];
                          editFollowUps(next);
                        }}
                      />
                      <span>
                        {review.title} <span className="text-slate-500">· {STATUS_LABELS[review.status]}</span>
                      </span>
                    </label>
                    {selected && (
                      <div className="mt-2 pl-6">
                        <label htmlFor={textId} className="text-sm">
                          Client-facing text for {review.title}
                        </label>
                        <textarea
                          id={textId}
                          className={TEXTAREA}
                          rows={2}
                          maxLength={1000}
                          value={followUps[review.finding_id]}
                          onChange={(e) => editFollowUps({ ...followUps, [review.finding_id]: e.target.value })}
                        />
                        {review.internal_note && (
                          <div className="mt-2 rounded bg-slate-50 p-2 text-xs text-slate-600">
                            <p>
                              Internal note (not included): <span className="whitespace-pre-wrap">{review.internal_note}</span>
                            </p>
                            <button
                              type="button"
                              className="mt-1 text-xs font-medium underline"
                              onClick={() => editFollowUps({ ...followUps, [review.finding_id]: review.internal_note })}
                            >
                              Copy internal note into client text
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-medium">Household context</legend>
            {!defaults.household && (
              <p className="mt-2 text-sm text-slate-500">
                No household snapshot is attached to this analysis, so none can be included.
              </p>
            )}
            {defaults.household && (
              <div className="mt-2 space-y-2 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={household.enabled}
                    onChange={(e) => editHousehold({ ...NO_HOUSEHOLD, enabled: e.target.checked })}
                  />
                  Include {defaults.household.name} (version {defaults.household.version})
                </label>
                {household.enabled && (
                  <div className="space-y-2 pl-6">
                    {(
                      [
                        ["priorities", "Priorities"],
                        ["goals", `Goals (${defaults.household.goal_count})`],
                        ["accounts", `Account inventory (${defaults.household.account_count}), listed separately and not reconciled with the analyzed portfolio`],
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key} className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={household[key]}
                          onChange={(e) => editHousehold({ ...household, [key]: e.target.checked })}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <button className={PRIMARY} disabled={busy || incomplete} onClick={runPreview}>
              {busy && !preview ? "Working…" : "Preview report"}
            </button>
            <button className={SECONDARY} disabled={busy} onClick={() => loadDefaults(true)}>
              Refresh sources
            </button>
            {incomplete && (
              <span className="text-xs text-slate-500">Add a summary and client-facing text for each selected follow-up.</span>
            )}
          </div>
        </fieldset>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
          {stale && (
            <button className={`${SECONDARY} ml-3`} disabled={busy} onClick={() => loadDefaults(true)}>
              Reload latest sources
            </button>
          )}
        </div>
      )}
      <p role="status" className="mt-3 text-sm text-emerald-800">{message}</p>

      {preview && (
        <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3">
          <p className="text-sm text-amber-900">
            Review this preview. Approving saves exactly this content and its sources; editing the draft clears the
            preview.
          </p>
          <iframe
            title="Client report preview"
            srcDoc={preview.html}
            sandbox=""
            className="mt-3 h-[640px] w-full rounded border border-slate-300 bg-white"
          />
          <button className={`${PRIMARY} mt-3`} disabled={busy} onClick={approve}>
            {busy ? "Approving…" : "Approve and save report"}
          </button>
        </div>
      )}

      {reports.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold">Approved reports</h3>
          <ul className="mt-2 divide-y rounded-md border">
            {reports.map((report) => (
              <li key={report.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
                <span>
                  Report #{report.id} · approved {new Date(report.approved_at).toLocaleString()}
                  <span className="ml-2 font-mono text-xs text-slate-400">{report.content_sha256.slice(0, 12)}</span>
                </span>
                <span className="flex gap-2">
                  {FORMATS.map(({ format, label }) => (
                    <a
                      key={format}
                      href={reportFileUrl(report.id, format)}
                      download
                      className={SECONDARY}
                      aria-label={`Download report ${report.id} as ${label}`}
                    >
                      {label}
                    </a>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
