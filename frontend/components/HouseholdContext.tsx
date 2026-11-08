'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { HouseholdContext as Context, HouseholdListItem, householdRequest } from '@/lib/households';

export default function HouseholdContext({ analysisId, sourceName }: { analysisId: number; sourceName: string }) {
  const [context, setContext] = useState<Context | null>(null);
  const [households, setHouseholds] = useState<HouseholdListItem[]>([]);
  const [selected, setSelected] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      householdRequest<{ context: Context | null }>(`/analyses/${analysisId}/household`),
      householdRequest<{ households: HouseholdListItem[] }>('/households'),
    ])
      .then(([record, list]) => {
        if (active) { setContext(record.context); setHouseholds(list.households); setLoaded(true); }
      })
      .catch(e => { if (active) setError(e.message); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [analysisId]);

  const chosen = households.find(h => h.id === Number(selected));

  async function attach() {
    if (!chosen) return;
    setBusy(true); setError('');
    try {
      const result = await householdRequest<{ context: Context }>(`/analyses/${analysisId}/household`, 'POST', {
        household_id: chosen.id, expected_version: chosen.version,
      });
      setContext(result.context);
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to attach context.');
      setConfirming(false);
    } finally { setBusy(false); }
  }

  async function refresh() {
    try {
      const data = await householdRequest<{ households: HouseholdListItem[] }>('/households');
      setHouseholds(data.households); setError(''); setConfirming(false);
    } catch (e) { setError(e instanceof Error ? e.message : 'Refresh failed.'); }
  }

  return (
    <section className="rounded-lg border border-teal-200 bg-teal-50 p-5" aria-label="Household context">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-teal-950">Household context</h2>
        <Link className="text-sm text-teal-800 underline underline-offset-4" href="/households">Manage households</Link>
      </div>
      {busy && <p role="status" className="mt-3 text-sm">Loading household context…</p>}
      {error && <p role="alert" className="mt-3 text-sm text-red-800">{error}</p>}

      {context && (
        <div className="mt-3">
          <p className="font-medium">{context.profile.name} · version {context.version}</p>
          <p className="mt-1 text-sm text-slate-600">
            Profile as of {context.profile.as_of} · {context.profile.members.map(m => m.name).join(', ') || 'Members not entered'}
          </p>
          <p className="mt-2 text-sm">{context.profile.priorities || 'Priorities not yet recorded.'}</p>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer">Goals in this saved snapshot</summary>
            <ul className="mt-2 space-y-2">
              {context.profile.goals.map(g => <li key={g.id}>{g.name} · {g.priority} · {g.target_date || 'Timing unknown'}</li>)}
            </ul>
          </details>
          <p className="mt-3 text-xs leading-5 text-teal-900">
            This context is fixed to the attached version. Later profile edits do not change it. Portfolio rules still use
            the original CSV inputs; household context only reaches a client report if you select it there.
          </p>
        </div>
      )}

      {!context && loaded && (
        <div className="mt-3">
          <p className="text-sm text-slate-600">
            Attach a saved household version for meeting context. The association is permanent; create a new analysis to
            use a different snapshot.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1 text-sm">
              <label htmlFor={`household-choice-${analysisId}`}>Saved household</label>
              <select
                id={`household-choice-${analysisId}`}
                className="mt-1 block w-full rounded-md border border-slate-300 bg-white p-2"
                value={selected}
                onChange={e => { setSelected(e.target.value); setConfirming(false); }}
                disabled={busy || confirming}
              >
                <option value="">Select a household</option>
                {households.map(h => <option key={h.id} value={h.id}>{h.name} · v{h.version}</option>)}
              </select>
            </div>
            <button type="button" disabled={busy || !chosen || confirming} onClick={() => setConfirming(true)}
              className="rounded-md bg-teal-800 px-3 py-2 text-sm text-white disabled:opacity-50">
              Attach snapshot
            </button>
            <button type="button" disabled={busy} onClick={refresh} className="text-sm text-teal-800 underline">
              Refresh households
            </button>
          </div>
          {confirming && chosen && (
            <div role="group" aria-label="Confirm household attachment" className="mt-4 rounded-md border border-amber-300 bg-white p-4 text-sm">
              <p className="font-medium">Permanently attach this household snapshot?</p>
              <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
                <dt className="text-slate-500">Household</dt><dd>{chosen.name}</dd>
                <dt className="text-slate-500">Saved version</dt><dd>{chosen.version}</dd>
                <dt className="text-slate-500">Analysis</dt><dd>#{analysisId} · {sourceName}</dd>
              </dl>
              <p className="mt-2 text-slate-600">
                This cannot be undone or changed later. Confirm that this analysis belongs to this household.
              </p>
              <div className="mt-3 flex gap-3">
                <button type="button" disabled={busy} onClick={attach} className="rounded-md bg-teal-800 px-3 py-2 text-white disabled:opacity-50">
                  Confirm permanent attachment
                </button>
                <button type="button" disabled={busy} onClick={() => setConfirming(false)} className="rounded-md border border-slate-300 px-3 py-2">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
