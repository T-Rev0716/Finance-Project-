"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import AdvisorReviewQueue from "@/components/AdvisorReviewQueue";
import BriefView from "@/components/BriefView";
import HistoryView from "@/components/HistoryView";
import {
  AllocationItem,
  AnalysisResult,
  GeneratorInfo,
  analyzeSample,
  analyzeUpload,
  fetchGeneratorInfo,
  fetchSamples,
  formatMoney,
  getAnalysis,
} from "@/lib/api";

export default function Workspace() {
  const [samples, setSamples] = useState<string[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"analyze" | "history">("analyze");
  const [briefRequest, setBriefRequest] = useState<{ id: number; token: number } | null>(null);
  const [generatorInfo, setGeneratorInfo] = useState<GeneratorInfo | null>(null);

  useEffect(() => {
    fetchSamples()
      .then(setSamples)
      .catch(() =>
        setError("Could not reach the AdvisorLens API. Start the backend on port 8000."),
      );
    fetchGeneratorInfo()
      .then(setGeneratorInfo)
      .catch(() => setGeneratorInfo(null));
  }, []);

  async function run(action: () => Promise<AnalysisResult>) {
    setLoading(true);
    setError(null);
    try {
      setResult(await action());
      setTab("analyze");
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "Analysis failed.");
    } finally {
      setLoading(false);
    }
  }

  function openFromHistory(id: number) {
    run(() => getAnalysis(id));
  }

  function viewBriefFromHistory(id: number) {
    setBriefRequest({ id, token: Date.now() });
    run(() => getAnalysis(id));
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-end justify-between gap-3 px-6 py-5">
          <div>
            <h1 className="text-2xl font-semibold">
              <Link href="/" className="hover:text-slate-700">
                AdvisorLens
              </Link>
            </h1>
            <p className="text-sm text-slate-500">
              Portfolio review support for advisors — synthetic data only, deterministic rules
              only.
            </p>
          </div>
          <nav className="flex gap-1 rounded-lg border border-slate-200 bg-slate-100 p-1">
            {(["analyze", "history"] as const).map((name) => (
              <button
                key={name}
                onClick={() => setTab(name)}
                className={`rounded-md px-3 py-1 text-sm font-medium capitalize ${
                  tab === name ? "bg-white shadow-sm" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {name}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-6">
        {tab === "history" && (
          <HistoryView
            opening={loading}
            onOpen={openFromHistory}
            onViewBrief={viewBriefFromHistory}
          />
        )}

        <section className={`rounded-lg border bg-white p-5 ${tab !== "analyze" ? "hidden" : ""}`}>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Analyze a portfolio
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            {samples.map((name) => (
              <button
                key={name}
                disabled={loading}
                onClick={() => run(() => analyzeSample(name))}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-100 disabled:opacity-50"
              >
                {name.replace(".csv", "").replaceAll("_", " ")}
              </button>
            ))}
            <label
              className={`rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 ${
                loading ? "pointer-events-none opacity-50" : "cursor-pointer"
              }`}
            >
              Upload CSV
              <input
                type="file"
                accept=".csv"
                className="hidden"
                disabled={loading}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) run(() => analyzeUpload(file));
                  e.target.value = "";
                }}
              />
            </label>
            {loading && (
              <span className="flex items-center gap-2 text-sm text-slate-500">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
                Analyzing…
              </span>
            )}
          </div>
          {error && (
            <p className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {error}
            </p>
          )}
        </section>

        {tab === "analyze" && result && (
          <Results
            result={result}
            autoLoadBriefToken={briefRequest?.id === result.analysis_id ? briefRequest.token : undefined}
            generatorInfo={generatorInfo}
          />
        )}
      </main>
    </div>
  );
}

function Results({
  result,
  autoLoadBriefToken,
  generatorInfo,
}: {
  result: AnalysisResult;
  autoLoadBriefToken?: number;
  generatorInfo: GeneratorInfo | null;
}) {
  const { summary, flags } = result;
  const gain = summary.total_unrealized_gain_loss;
  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-white p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">{result.source_name}</h2>
          <span className="text-xs text-slate-400">
            analysis #{result.analysis_id} · engine v{result.engine_version} · sha256{" "}
            {result.file_sha256.slice(0, 12)}…
          </span>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Risk tolerance: <b>{result.client_profile.risk_tolerance}</b> · Goal:{" "}
          <b>{result.client_profile.client_goal}</b>
        </p>
        {result.warnings.length > 0 && (
          <ul className="mt-2 list-inside list-disc text-sm text-amber-700">
            {result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Total value" value={formatMoney(summary.total_market_value)} />
          <Stat
            label="Unrealized G/L"
            value={`${gain >= 0 ? "+" : ""}${formatMoney(gain)}`}
            tone={gain >= 0 ? "text-emerald-700" : "text-red-700"}
          />
          <Stat label="Holdings" value={String(summary.holdings_count)} />
          <Stat label="Review items" value={String(flags.length)} />
        </div>
      </section>

      <AdvisorReviewQueue key={result.analysis_id} analysisId={result.analysis_id} />

      <div className="grid gap-6 md:grid-cols-2">
        <AllocationCard title="Asset allocation" items={summary.asset_allocation} />
        <AllocationCard title="Sector allocation" items={summary.sector_allocation} />
      </div>

      <section className="rounded-lg border bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Top holdings
        </h2>
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase text-slate-400">
              <th className="py-2">Ticker</th>
              <th className="py-2">Name</th>
              <th className="py-2 text-right">Value</th>
              <th className="py-2 text-right">Weight</th>
              <th className="py-2 text-right">Unrealized G/L</th>
            </tr>
          </thead>
          <tbody>
            {summary.top_holdings.map((h) => (
              <tr key={h.ticker} className="border-b last:border-0">
                <td className="py-2 font-medium">{h.ticker}</td>
                <td className="py-2 text-slate-600">{h.security_name}</td>
                <td className="py-2 text-right">{formatMoney(h.market_value)}</td>
                <td className="py-2 text-right">{h.weight_pct.toFixed(1)}%</td>
                <td
                  className={`py-2 text-right ${
                    h.unrealized_gain_loss >= 0 ? "text-emerald-700" : "text-red-700"
                  }`}
                >
                  {formatMoney(h.unrealized_gain_loss)}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </section>

      <BriefView
        key={result.analysis_id}
        analysisId={result.analysis_id}
        autoLoadToken={autoLoadBriefToken}
        generatorInfo={generatorInfo}
      />

      <p className="rounded-md border border-slate-200 bg-white p-4 text-xs text-slate-500">
        {result.disclaimer}
      </p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md border bg-slate-50 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function AllocationCard({ title, items }: { title: string; items: AllocationItem[] }) {
  return (
    <section className="rounded-lg border bg-white p-5">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.name}>
            <div className="flex justify-between text-sm">
              <span>{item.name}</span>
              <span className="text-slate-500">
                {item.weight_pct.toFixed(1)}% · {formatMoney(item.market_value)}
              </span>
            </div>
            <div className="mt-1 h-2 rounded bg-slate-100">
              <div
                className="h-2 rounded bg-slate-700"
                style={{ width: `${Math.min(item.weight_pct, 100)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
