"use client";

import { useEffect, useState } from "react";

import {
  Brief,
  GeneratorInfo,
  briefExportUrl,
  formatMoney,
  getBrief,
  regenerateBrief,
} from "@/lib/api";

const FALLBACK_GENERATOR = "deterministic-fallback-after-llm-failure";

const SEVERITY_TEXT: Record<string, string> = {
  high: "text-red-700",
  medium: "text-amber-700",
  info: "text-sky-700",
};

const SEVERITY_BORDER: Record<string, string> = {
  high: "border-l-red-700",
  medium: "border-l-amber-700",
  info: "border-l-sky-700",
};

export default function BriefView({
  analysisId,
  autoLoadToken,
  generatorInfo,
}: {
  analysisId: number;
  /** Changing this value (e.g. from a "View Brief" click) triggers an automatic load. */
  autoLoadToken?: number;
  generatorInfo?: GeneratorInfo | null;
}) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<Brief>) {
    setLoading(true);
    setError(null);
    try {
      setBrief(await action());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Brief generation failed.");
    } finally {
      setLoading(false);
    }
  }

  function load() {
    return run(() => getBrief(analysisId));
  }

  function generateWithLlm() {
    return run(() => regenerateBrief(analysisId, "llm-v1"));
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch on external trigger token
    if (autoLoadToken !== undefined) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoadToken]);

  return (
    <section className="rounded-lg border bg-white p-5 print:border-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Client Portfolio Review Brief
        </h2>
        <div className="flex flex-wrap gap-2 print:hidden">
          {!brief && (
            <button
              onClick={load}
              disabled={loading}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {loading ? "Generating…" : "Generate / View Brief"}
            </button>
          )}
          {generatorInfo?.llm_configured &&
            (!brief || brief.generator === "deterministic-v1") && (
              <button
                onClick={generateWithLlm}
                disabled={loading}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-50"
              >
                {brief ? "Regenerate with LLM" : "Generate with LLM"}
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
              <a
                href={briefExportUrl(analysisId, "pdf")}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
              >
                Export PDF
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
          Generates an advisor-presentable brief grounded in this analysis&apos;s data and rule
          evidence. Nothing is invented; every review item maps to a rule ID.{" "}
          {generatorInfo?.llm_configured ? (
            <span>
              Deterministic generation is the default; an LLM language generator
              {generatorInfo.llm_model ? ` (${generatorInfo.llm_model})` : ""} is available and
              falls back to deterministic output if its draft fails validation.
            </span>
          ) : (
            <span>Deterministic generator active — no LLM is configured.</span>
          )}
        </p>
      )}

      {brief && <BriefBody brief={brief} />}
    </section>
  );
}

function BriefBody({ brief }: { brief: Brief }) {
  const s = brief.sections;
  const model = brief.generator_metadata?.model;
  return (
    <div className="mt-5 space-y-6 text-sm">
      {brief.generator === FALLBACK_GENERATOR && (
        <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Generated with rule-based fallback because the LLM draft was unavailable or failed
          validation.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-4">
        <div>
          <dt className="font-semibold text-slate-700">Analysis ID</dt>
          <dd>{brief.analysis_id}</dd>
        </div>
        <div>
          <dt className="font-semibold text-slate-700">Source file</dt>
          <dd className="truncate">{brief.source_name}</dd>
        </div>
        <div>
          <dt className="font-semibold text-slate-700">Generated</dt>
          <dd>{new Date(brief.generated_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="font-semibold text-slate-700">Engine version</dt>
          <dd className="truncate">
            {brief.engine_version} ({brief.generator}
            {brief.generator === "llm-v1" && model ? ` · ${model}` : ""})
          </dd>
        </div>
      </dl>

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
          <ul className="space-y-3">
            {s.key_review_items.map((item, i) => (
              <li
                key={`${item.rule_id}-${i}`}
                className={`border-l-4 pl-3 ${SEVERITY_BORDER[item.severity] ?? "border-l-slate-300"}`}
              >
                <span className={`font-semibold ${SEVERITY_TEXT[item.severity] ?? ""}`}>
                  [{item.severity.toUpperCase()}]
                </span>{" "}
                <span className="font-medium">{item.title}</span>{" "}
                <code className="rounded bg-slate-100 px-1 text-xs">{item.rule_id}</code>
                <p className="mt-1 text-slate-600">{item.message}</p>
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
          <ul className="space-y-3">
            {s.evidence_table.map((row, i) => (
              <li key={`${row.rule_id}-${i}`} className="rounded-md border p-3">
                <p className="text-xs text-slate-600">
                  <code className="rounded bg-slate-100 px-1 font-mono">{row.rule_id}</code>{" "}
                  · severity: {row.severity} · threshold: {row.threshold}
                </p>
                <ul className="mt-2 space-y-0.5 font-mono text-xs text-slate-500">
                  {Object.entries(row.evidence).map(([k, v]) => (
                    <li key={k}>
                      {k}: {JSON.stringify(v)}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
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
