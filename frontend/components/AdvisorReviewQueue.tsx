"use client";

import { useEffect, useState } from "react";
import { FindingReview, ReviewStatus, ReviewSaveError, getReviews, saveReview } from "@/lib/api";

const LABELS: Record<ReviewStatus, string> = {
  open: "Open", discussed: "Discussed", follow_up: "Follow-up", resolved: "Resolved",
};
const STATUS_STYLE: Record<ReviewStatus, string> = {
  open: "bg-slate-100 text-slate-700", discussed: "bg-blue-50 text-blue-800",
  follow_up: "bg-amber-50 text-amber-800", resolved: "bg-emerald-50 text-emerald-800",
};
const CONTROL = "rounded-md border border-slate-300 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:opacity-50";

export default function AdvisorReviewQueue({ analysisId }: { analysisId: number }) {
  const [items, setItems] = useState<FindingReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<ReviewStatus | "all">("all");
  useEffect(() => {
    let cancelled = false;
    getReviews(analysisId).then(data => {
      if (!cancelled) { setItems(data); setError(null); }
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [analysisId, attempt]);

  return <section className="rounded-xl border border-slate-200 bg-white p-5" aria-label="Advisor review queue">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-lg font-semibold">Advisor review queue</h2>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">Record decisions and follow-ups for analysis #{analysisId}. Resolving an item records your review; it does not remove the underlying finding.</p>
      </div>
      {items && <span className="rounded-full bg-teal-50 px-3 py-1 text-sm font-medium text-teal-800">
        {items.filter(i => i.status === "resolved").length} of {items.length} resolved
      </span>}
    </div>
    <p className="mt-2 text-xs text-slate-500">Internal demo notes stay with this analysis. They are not sent to AI, and a client report only includes text you write or explicitly copy into it.</p>
    {error && <div role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error} <button className={`${CONTROL} ml-2`} onClick={() => setAttempt(a => a + 1)}>Retry loading reviews</button></div>}
    {!items && !error && <p role="status" className="mt-4 text-sm text-slate-500">Loading review decisions…</p>}
    {items && <>
      <div className="my-4 flex flex-wrap gap-2" aria-label="Filter review status">
        {(["all", "open", "discussed", "follow_up", "resolved"] as const).map(value => <button
          key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}
          className={`${CONTROL} ${filter === value ? "border-teal-700 bg-teal-700 text-white" : "bg-white text-slate-600"}`}>
          {value === "all" ? "All" : LABELS[value]} ({items.filter(i => value === "all" || i.status === value).length})
        </button>)}
      </div>
      {items.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No review thresholds were exceeded. No decisions need tracking for this analysis.</p>}
      {items.length > 0 && !items.some(i => filter === "all" || i.status === filter) && <p role="status" className="p-4 text-sm text-slate-500">No items with this status.</p>}
      <div className="space-y-4">{items.map(item => <div key={item.finding_id} hidden={filter !== "all" && item.status !== filter}>
        <ReviewCard analysisId={analysisId} item={item} onSaved={updated => setItems(current => current!.map(i => i.finding_id === updated.finding_id ? updated : i))} />
      </div>)}</div>
    </>}
  </section>;
}

function ReviewCard({ analysisId, item, onSaved }: { analysisId: number; item: FindingReview; onSaved: (item: FindingReview) => void }) {
  const [status, setStatus] = useState(item.status);
  const [note, setNote] = useState(item.note);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const dirty = status !== item.status || note !== item.note;
  const prefix = `review-${item.finding_id}`;

  async function save() {
    setSaving(true); setError(null); setSavedMessage("");
    try {
      const saved = await saveReview(analysisId, item.finding_id, { status, note, expected_version: item.version });
      onSaved({ ...item, ...saved, history: saved.version === item.version ? item.history : [{
        finding_id: item.finding_id, status: saved.status, note: saved.note,
        version: saved.version, created_at: saved.updated_at!,
      }, ...item.history] });
      setNote(saved.note); setStatus(saved.status); setSavedMessage("Review saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save review.");
      setConflict(e instanceof ReviewSaveError && e.statusCode === 409);
    } finally { setSaving(false); }
  }
  async function reload() {
    setSaving(true);
    try {
      const latest = (await getReviews(analysisId)).find(i => i.finding_id === item.finding_id);
      if (!latest) throw new Error("Finding no longer available.");
      onSaved(latest); setNote(latest.note); setStatus(latest.status); setConflict(false); setError(null); setSavedMessage("Latest saved review loaded.");
    } catch (e) { setError(e instanceof Error ? e.message : "Reload failed."); }
    finally { setSaving(false); }
  }

  return <article className="min-w-0 rounded-lg border border-slate-200 p-4" aria-labelledby={`${prefix}-title`}>
    <div className="flex flex-wrap items-center gap-2">
      <span className={`rounded px-2 py-1 text-xs font-semibold ${item.flag.severity === "high" ? "bg-red-50 text-red-800" : item.flag.severity === "medium" ? "bg-amber-50 text-amber-800" : "bg-blue-50 text-blue-800"}`}>{item.flag.severity} priority</span>
      <h3 id={`${prefix}-title`} className="font-medium">{item.flag.title}</h3>
      <span className={`rounded-full px-2 py-1 text-xs font-medium ${STATUS_STYLE[item.status]}`}>{LABELS[item.status]}</span>
    </div>
    <p className="mt-3 text-sm leading-relaxed text-slate-600">{item.flag.message}</p>
    <details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer font-medium">Evidence and threshold</summary>
      <p className="mt-2 break-words">{item.flag.rule_id} · {item.flag.threshold}</p>
      <pre className="mt-2 max-w-full overflow-x-auto rounded bg-slate-50 p-3">{JSON.stringify(item.flag.evidence, null, 2)}</pre>
    </details>
    <div className="mt-4 grid gap-4 sm:grid-cols-[160px_1fr]">
      <div><label htmlFor={`${prefix}-status`} className="mb-1 block text-sm font-medium">Review status</label>
        <select id={`${prefix}-status`} value={status} disabled={saving} onChange={e => { setStatus(e.target.value as ReviewStatus); setSavedMessage(""); }} className={`${CONTROL} w-full bg-white`}>
          {Object.entries(LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select>
      </div>
      <div><label htmlFor={`${prefix}-note`} className="mb-1 block text-sm font-medium">Advisor note</label>
        <textarea id={`${prefix}-note`} aria-describedby={`${prefix}-help`} value={note} disabled={saving} maxLength={4000} rows={3}
          onChange={e => { setNote(e.target.value); setSavedMessage(""); }} placeholder="Record what you discussed, the decision, or the next follow-up."
          className={`${CONTROL} w-full resize-y`} />
        <p id={`${prefix}-help`} className="mt-1 text-xs text-slate-500">A decision note is required to resolve an item. {note.length}/4,000 characters.</p>
      </div>
    </div>
    {error && <p role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {conflict && <button className={`${CONTROL} mt-2`} disabled={saving} onClick={reload}>Discard draft and load latest review</button>}
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button onClick={save} disabled={saving || !dirty || conflict || (status === "resolved" && !note.trim())}
        className={`${CONTROL} border-teal-700 bg-teal-700 font-medium text-white`}>{saving ? "Saving…" : "Save review"}</button>
      <span role="status" className="text-xs text-slate-500">{dirty ? "Unsaved changes" : savedMessage || (item.updated_at ? `Saved ${new Date(item.updated_at).toLocaleString()}` : "Not reviewed yet")}</span>
    </div>
    {item.history.length > 0 && <details className="mt-4 border-t pt-3 text-xs text-slate-600"><summary className="cursor-pointer font-medium">Decision history ({item.history.length})</summary>
      <ol className="mt-3 space-y-3">{item.history.map(event => <li key={event.version} className="rounded bg-slate-50 p-3">
        <div className="font-medium">{LABELS[event.status]} · revision {event.version} · {new Date(event.created_at).toLocaleString()}</div>
        <p className="mt-1 whitespace-pre-wrap break-words">{event.note || "No note recorded."}</p>
      </li>)}</ol>
    </details>}
  </article>;
}
