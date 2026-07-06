"use client";

import { useState } from "react";

import { Brief, briefExportUrl, formatMoney, getBrief } from "@/lib/api";

const SEVERITY_TEXT: Record<string, string> = {
  high: "text-red-700",
  medium: "text-amber-700",
  info: "text-sky-700",
};

export default function BriefView({ analysisId }: { analysisId: number }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setBrief(await getBrief(analysisId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Brief generation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-lg border bg-white p-5 print:border-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Client Portfolio Review Brief
        </h2>
        <div className="flex flex-wrap gap-2">
          {!brief && (
            <button
              onClick={load}
              disabled={loading}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {loading ? "Generating…" : "Generate / View Brief"}
            </button>
          )}
          {brief && (
            <>
              <a
                href={briefExportUrl(analysisId, "markdown")}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
              >
                Export Markdown
              </a>
              <a
                href={briefExportUrl(analysisId, "html")}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
              >
                Export HTML
              </a>
            </>
          )}
        </div>
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}

      {!brief && !error && (
        <p className="mt-3 text-sm text-slate-500">
          Generates a deterministic, advisor-presentable brief grounded in this analysis&apos;s
          data and rule evidence. Nothing is invented; every review item maps to a rule ID.
        </p>
      )}

      {brief && <BriefBody brief={brief} />}
    </section>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const s = brief.sections;
  return (
    <div className="mt-4 space-y-5 text-sm">
      <p className="text-xs text-slate-400">
        Generated {new Date(brief.generated_at).toLocaleString()} · generator {brief.generator} ·
        engine v{brief.engine_version}
      </p>

      <Section title="Executive Summary">
        {s.executive_summary.map((p) => (
          <p key={p} className="mb-2 text-slate-700">
            {p}
          </p>
        ))}
      </Section>

      <Section title="Portfolio Snapshot">
        <p className="text-slate-700">
          Total value {formatMoney(s.portfolio_snapshot.total_market_value)} · cost basis{" "}
          {formatMoney(s.portfolio_snapshot.total_cost_basis)} · unrealized G/L{" "}
          {formatMoney(s.portfolio_snapshot.total_unrealized_gain_loss)} ·{" "}
          {s.portfolio_snapshot.holdings_count} holdings · {s.portfolio_snapshot.risk_tolerance}{" "}
          profile, goal: {s.portfolio_snapshot.client_goal}. Full allocations and top holdings
          appear in the dashboard above and in the exported brief.
        </p>
      </Section>

      <Section title="Key Review Items">
        {s.key_review_items.length === 0 ? (
          <p className="text-slate-500">No review thresholds were exceeded for this portfolio.</p>
        ) : (
          <ul className="space-y-2">
            {s.key_review_items.map((item, i) => (
              <li key={`${item.rule_id}-${i}`}>
                <span className={`font-semibold ${SEVERITY_TEXT[item.severity] ?? ""}`}>
                  [{item.severity.toUpperCase()}]
                </span>{" "}
                <span className="font-medium">{item.title}</span>{" "}
                <code className="rounded bg-slate-100 px-1 text-xs">{item.rule_id}</code>
                <p className="text-slate-600">{item.message}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <BulletSection title="Advisor Talking Points" items={s.advisor_talking_points} />
      <BulletSection title="Client Discussion Questions" items={s.client_discussion_questions} />
      <BulletSection title="Follow-Up Items" items={s.follow_up_items} />

      <Section title="Evidence Table">
        {s.evidence_table.length === 0 ? (
          <p className="text-slate-500">No rules fired; there is no evidence to report.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left uppercase text-slate-400">
                  <th className="py-1 pr-2">Rule ID</th>
                  <th className="py-1 pr-2">Severity</th>
                  <th className="py-1 pr-2">Threshold</th>
                  <th className="py-1">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {s.evidence_table.map((row, i) => (
                  <tr key={`${row.rule_id}-${i}`} className="border-b align-top last:border-0">
                    <td className="py-1.5 pr-2 font-mono">{row.rule_id}</td>
                    <td className="py-1.5 pr-2">{row.severity}</td>
                    <td className="py-1.5 pr-2">{row.threshold}</td>
                    <td className="py-1.5 font-mono text-slate-500">
                      {Object.entries(row.evidence)
                        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                        .join("; ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <BulletSection title="Data Assumptions" items={s.data_assumptions} />

      <Section title="Compliance Disclaimer">
        <p className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
          {s.compliance_disclaimer}
        </p>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 border-b border-slate-200 pb-1 font-semibold text-slate-800">{title}</h3>
      {children}
    </div>
  );
}

function BulletSection({ title, items }: { title: string; items: string[] }) {
  return (
    <Section title={title}>
      <ul className="list-inside list-disc space-y-1 text-slate-700">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Section>
  );
}
