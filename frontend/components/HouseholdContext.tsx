'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { HouseholdContext as Context, HouseholdListItem, householdRequest } from '@/lib/households';

export default function HouseholdContext({ analysisId }: { analysisId: number }) {
  const [context, setContext] = useState<Context | null>(null);
  const [households, setHouseholds] = useState<HouseholdListItem[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([householdRequest<{context: Context | null}>(`/analyses/${analysisId}/household`), householdRequest<{households: HouseholdListItem[]}>('/households')])
      .then(([record, list]) => { if (active) { setContext(record.context); setHouseholds(list.households); setLoaded(true); } })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [analysisId]);
  async function attach() {
    const chosen = households.find(h => h.id === Number(selected));
    if (!chosen) return;
    setBusy(true); setError('');
    try {
      const result = await householdRequest<{context:Context}>(`/analyses/${analysisId}/household`, 'POST', { household_id: chosen.id, expected_version: chosen.version });
      setContext(result.context);
    } catch(e) { setError(e instanceof Error ? e.message : 'Unable to attach context.'); }
    finally { setBusy(false); }
  }
  return <section className="rounded-lg border border-teal-200 bg-teal-50 p-5" aria-label="Household context">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-teal-950">Household context</h2><Link className="text-sm text-teal-800 underline underline-offset-4" href="/households">Manage households</Link></div>
    {busy && <p role="status" className="mt-3 text-sm">Loading household context…</p>}
    {error && <p role="alert" className="mt-3 text-sm text-red-800">{error}</p>}
    {context ? <div className="mt-3"><p className="font-medium">{context.profile.name} · version {context.version}</p><p className="mt-1 text-sm text-slate-600">Profile as of {context.profile.as_of} · {context.profile.members.map(m=>m.name).join(', ') || 'Members not entered'}</p><p className="mt-2 text-sm">{context.profile.priorities || 'Priorities not yet recorded.'}</p><details className="mt-3 text-sm"><summary className="cursor-pointer">Goals in this saved snapshot</summary><ul className="mt-2 space-y-2">{context.profile.goals.map(g=><li key={g.id}>{g.name} · {g.priority} · {g.target_date || 'Timing unknown'}</li>)}</ul></details><p className="mt-3 text-xs leading-5 text-teal-900">This context is fixed to the attached version. Later profile edits do not change it. Portfolio rules still use the original CSV inputs; household context is not included in client briefs or AI prompts.</p></div>
      : loaded && <div className="mt-3"><p className="text-sm text-slate-600">Attach a saved household version for meeting context. Confirm that this analysis belongs to the selected household. The association is permanent; create a new analysis to use a different snapshot.</p><div className="mt-3 flex flex-wrap items-end gap-3"><div className="min-w-0 flex-1 text-sm"><label htmlFor={`household-choice-${analysisId}`}>Saved household</label><select id={`household-choice-${analysisId}`} className="mt-1 block w-full rounded-md border border-slate-300 bg-white p-2" value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy}><option value="">Select a household</option>{households.map(h=><option key={h.id} value={h.id}>{h.name} · v{h.version}</option>)}</select></div><button type="button" disabled={busy || !selected} onClick={attach} className="rounded-md bg-teal-800 px-3 py-2 text-sm text-white disabled:opacity-50">Attach snapshot</button><button type="button" disabled={busy} onClick={async()=>{try{const data=await householdRequest<{households:HouseholdListItem[]}>('/households');setHouseholds(data.households);setError('');}catch(e){setError(e instanceof Error?e.message:'Refresh failed.');}}} className="text-sm text-teal-800 underline">Refresh households</button></div></div>}
  </section>;
}
