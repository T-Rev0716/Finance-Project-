"use client";

import { useEffect, useState } from "react";

import { SavedAnalysis, briefExportUrl, formatMoney, listAnalyses } from "@/lib/api";

export default function HistoryView({
  onOpen,
  onViewBrief,
  opening,
}: {
  onOpen: (id: number) => void;
  onViewBrief: (id: number) => void;
  opening: boolean;
}) {
  const [analyses, setAnalyses] = useState<SavedAnalysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAnalyses()
      .then(setAnalyses)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load history."));
  }, []);

  if (error) {
    return (
      <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>
    );
  }
  if (analyses === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate-500">
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
        Loading saved analyses…
      </p>
    );
  }
  if (analyses.length === 0) {
    return (
      <p className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-500">
        No saved analyses yet. Analyze a sample or upload a CSV — every run is recorded here with
        its file hash and audit trail.
      </p>
    );
  }

  return (
    <section className="rounded-lg border bg-white p-5">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Saved analyses
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase text-slate-400">
              <th className="py-2 pr-3">#</th>
              <th className="py-2 pr-3">Date</th>
              <th className="py-2 pr-3">Source file</th>
              <th className="py-2 pr-3">Profile</th>
              <th className="py-2 pr-3 text-right">Total value</th>
              <th className="py-2 pr-3 text-right">Review items</th>
              <th className="py-2 pr-3">Brief</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {analyses.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="py-2 pr-3 text-slate-500">{a.id}</td>
                <td className="py-2 pr-3 text-slate-500">
                  {new Date(a.created_at).toLocaleString()}
                </td>
                <td className="py-2 pr-3 font-medium">{a.source_name}</td>
                <td className="py-2 pr-3 text-slate-600">
                  {a.risk_tolerance} · {a.client_goal}
                </td>
                <td className="py-2 pr-3 text-right">{formatMoney(a.total_market_value)}</td>
                <td className="py-2 pr-3 text-right">{a.flag_count}</td>
                <td className="py-2 pr-3">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                      a.has_brief
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-slate-200 bg-slate-50 text-slate-500"
                    }`}
                  >
                    {a.has_brief ? "Generated" : "Not generated"}
                  </span>
                </td>
                <td className="py-2">
                  <div className="flex flex-wrap justify-end gap-1.5">
                    <button
                      onClick={() => onOpen(a.id)}
                      disabled={opening}
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
                    >
                      Open
                    </button>
                    <button
                      onClick={() => onViewBrief(a.id)}
                      disabled={opening}
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
                    >
                      {a.has_brief ? "View Brief" : "Generate Brief"}
                    </button>
                    <a
                      href={briefExportUrl(a.id, "markdown")}
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100"
                    >
                      Export Markdown
                    </a>
                    <a
                      href={briefExportUrl(a.id, "html")}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100"
                    >
                      Export HTML
                    </a>
                    <a
                      href={briefExportUrl(a.id, "pdf")}
                      className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100"
                    >
                      Export PDF
                    </a>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
