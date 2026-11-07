'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { formatMoney } from '@/lib/api';
import { Account, CashFlow, Household, HouseholdError, HouseholdListItem, HouseholdVersion, Profile, demoProfile, emptyProfile, householdRequest } from '@/lib/households';

const input = 'mt-1 block w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-100';
const secondary = 'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50';
const primary = 'rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-900 disabled:opacity-50';
const money = (value: string | null) => value === null ? 'Not established' : formatMoney(Number(value));

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block min-w-0 text-sm font-medium text-slate-700">{label}{children}</label>;
}
function Section({ title, detail, children }: { title: string; detail: string; children: ReactNode }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6"><h2 className="text-lg font-semibold">{title}</h2><p className="mb-5 mt-1 text-sm text-slate-500">{detail}</p>{children}</section>;
}
function Remove({ onClick, name }: { onClick: () => void; name: string }) {
  return <button type="button" onClick={onClick} className="text-sm text-rose-700 underline underline-offset-4" aria-label={`Remove ${name}`}>Remove</button>;
}

export default function HouseholdsPage() {
  const [list, setList] = useState<HouseholdListItem[]>([]);
  const [saved, setSaved] = useState<Household | null>(null);
  const [draft, setDraft] = useState<Profile>(emptyProfile);
  const [baseline, setBaseline] = useState(() => JSON.stringify(emptyProfile()));
  const [versions, setVersions] = useState<HouseholdVersion[]>([]);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const dirty = JSON.stringify(draft) !== baseline;
  const refreshList = useCallback(async () => {
    const response = await householdRequest<{ households: HouseholdListItem[] }>('/households');
    setList(response.households);
  }, []);
  useEffect(() => {
    let active = true;
    householdRequest<{ households: HouseholdListItem[] }>('/households')
      .then(result => { if (active) setList(result.households); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const preventLoss = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener('beforeunload', preventLoss);
    return () => window.removeEventListener('beforeunload', preventLoss);
  }, [dirty]);

  function accept(record: Household) {
    setSaved(record); setDraft(record.profile); setBaseline(JSON.stringify(record.profile)); setConflict(false); setVersions([]);
  }
  const canLeave = () => !dirty || window.confirm('Discard your unsaved household changes?');
  async function open(id: number) {
    if (!canLeave()) return;
    setBusy(true); setError(''); setStatus('');
    try { accept(await householdRequest<Household>(`/households/${id}`)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to load household.'); }
    finally { setBusy(false); }
  }
  function startNew(example = false) {
    if (!canLeave()) return;
    const blank = emptyProfile(); setSaved(null); setVersions([]); setBaseline(JSON.stringify(blank));
    setDraft(example ? demoProfile() : blank); setStatus(''); setError(''); setConflict(false);
  }
  async function save() {
    setBusy(true); setError(''); setStatus('');
    try {
      const record = await householdRequest<Household>(saved ? `/households/${saved.id}` : '/households', saved ? 'PUT' : 'POST', saved ? { profile: draft, expected_version: saved.version } : draft);
      accept(record); setStatus(`Household saved · version ${record.version}.`);
      setList(previous => [{ id: record.id, name: record.profile.name, version: record.version }, ...previous.filter(h => h.id !== record.id)]);
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save household.'); setConflict(e instanceof HouseholdError && e.status === 409); }
    finally { setBusy(false); }
  }
  function change<K extends keyof Profile>(key: K, value: Profile[K]) { setDraft(p => ({ ...p, [key]: value })); setStatus(''); }
  function editRow<K extends 'members' | 'goals' | 'accounts' | 'cash_flows'>(key: K, id: string, patch: Partial<Profile[K][number]>) {
    setDraft(p => ({ ...p, [key]: p[key].map(row => row.id === id ? { ...row, ...patch } : row), ...(key === 'cash_flows' ? { cash_flow_complete: false } : {}) })); setStatus('');
  }
  function removeRow(key: 'members' | 'goals' | 'accounts' | 'cash_flows', id: string) {
    if (key === 'members' && draft.accounts.some(a => a.owner_ids.includes(id))) { setError('Update account ownership before removing this member.'); return; }
    setDraft(p => ({ ...p, [key]: p[key].filter(row => row.id !== id), ...(key === 'cash_flows' ? { cash_flow_complete: false } : {}) })); setStatus('');
  }
  const summary = saved?.summary;
  return <div className="min-h-screen bg-slate-50 text-slate-900">
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-5">
      <Link href="/" onClick={e => { if (!canLeave()) e.preventDefault(); }} className="text-xl font-semibold tracking-tight">AdvisorLens<span className="ml-2 text-teal-700">/</span></Link>
      <nav className="flex items-center gap-5 text-sm"><Link href="/workspace" onClick={e => { if (!canLeave()) e.preventDefault(); }} className="text-slate-600 hover:text-teal-800">Portfolio workspace</Link><span aria-current="page" className="font-semibold text-teal-800">Households</span></nav>
    </div></header>
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="mb-7"><p className="text-xs font-semibold uppercase tracking-[.18em] text-teal-700">Planning foundations</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">Start with the household.</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Bring goals, ownership and everyday cash flow into one conversation. Synthetic data only. Amounts are in USD.</p></div>
      <div className="grid items-start gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-slate-200 bg-white p-4"><h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Households</h2>
          <div className="space-y-2">{list.map(h => <button key={h.id} type="button" disabled={busy} onClick={() => open(h.id)} className={`block w-full break-words rounded-lg p-3 text-left text-sm ${saved?.id === h.id ? 'bg-teal-50 font-semibold text-teal-900' : 'hover:bg-slate-50'}`}>{h.name}<span className="mt-1 block text-xs font-normal text-slate-500">Version {h.version}</span></button>)}</div>
          {!list.length && <p className="mb-4 text-sm text-slate-500">No saved households yet.</p>}
          <div className="mt-4 grid gap-2 border-t border-slate-100 pt-4"><button type="button" className={secondary} disabled={busy} onClick={() => startNew()}>New household</button><button type="button" className={secondary} disabled={busy} onClick={() => startNew(true)}>Use fictional example</button><button type="button" className="text-xs text-slate-500 underline" disabled={busy} onClick={() => refreshList().catch(e => setError(e.message))}>Refresh list</button></div>
        </aside>
        <div className="min-w-0 space-y-5">
          {summary && <section aria-label="Saved household summary" className="rounded-xl bg-slate-900 p-5 text-white sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-medium text-slate-300">Saved snapshot · version {saved.version}</h2>{dirty && <span className="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-900">Unsaved changes below</span>}</div>
            <div className="mt-5 grid gap-6 sm:grid-cols-3"><div><p className="text-xs text-slate-300">Known account balances</p><p className="mt-2 text-2xl font-semibold">{saved.profile.accounts.length ? money(summary.known_account_total) : 'Not entered'}</p><p className="mt-1 text-xs text-slate-400">{summary.account_total_complete ? 'All listed balances entered' : 'Incomplete account inventory'}</p></div>
              <div><p className="text-xs text-slate-300">Monthly cash-flow balance</p><p className="mt-2 text-2xl font-semibold">{money(summary.monthly_net)}</p><p className="mt-1 text-xs text-slate-400">{summary.cash_flow_complete ? 'Based on the completed inventory' : 'Complete the inventory to calculate'}</p></div>
              <div><p className="text-xs text-slate-300">Questions to resolve</p><p className="mt-2 text-2xl font-semibold">{summary.missing_information.length}</p><p className="mt-1 text-xs text-slate-400">{summary.estimated_items} estimated inputs</p></div></div>
            {summary.mixed_valuation_dates && <p className="mt-4 text-sm text-amber-200">Balances use different valuation dates; this is not a same-date portfolio total.</p>}
            <details className="mt-5 border-t border-slate-700 pt-4"><summary className="cursor-pointer text-sm">Preparation checklist & annual cash flow</summary><ul className="mt-3 list-inside list-disc space-y-2 text-sm text-slate-300">{summary.missing_information.map((item, index) => <li key={index}>{item}</li>)}</ul>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-slate-400">Known annual income</dt><dd>{money(summary.annual_known.income)}</dd></div><div><dt className="text-slate-400">Known annual expenses</dt><dd>{money(summary.annual_known_expenses)}</dd></div><div><dt className="text-slate-400">Annual irregular expenses</dt><dd>{money(summary.annual_known.irregular)}</dd></div><div><dt className="text-slate-400">Annual balance</dt><dd>{money(summary.annual_net)}</dd></div></dl>
            </details>
          </section>}
          <form onSubmit={e => { e.preventDefault(); save(); }} className="space-y-5">
          <fieldset disabled={busy} className="min-w-0 space-y-5">
          <Section title="Household context" detail="Record what matters to the client. Blank amounts remain unknown; enter 0 only when zero is confirmed.">
            <div className="grid gap-4 sm:grid-cols-2"><Field label="Household name"><input className={input} required maxLength={120} value={draft.name} onChange={e => change('name', e.target.value)} /></Field><Field label="Profile as of"><input className={input} required type="date" value={draft.as_of} onChange={e => change('as_of', e.target.value)} /></Field></div>
            <div className="mt-4"><Field label="Priorities and values"><textarea className={input} maxLength={2000} rows={2} value={draft.priorities} onChange={e => change('priorities', e.target.value)} placeholder="What does a good outcome look like for this household?" /></Field></div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2"><Field label="Discussed risk tolerance"><select className={input} value={draft.risk_tolerance} onChange={e => change('risk_tolerance', e.target.value as Profile['risk_tolerance'])}>{['unknown','conservative','moderate','aggressive'].map(v => <option key={v} value={v}>{v}</option>)}</select></Field><Field label="Capacity for loss — advisor notes"><textarea className={input} rows={2} maxLength={2000} value={draft.risk_capacity_notes} onChange={e => change('risk_capacity_notes', e.target.value)} placeholder="Liquidity needs, time horizon and ability to withstand loss" /></Field></div>
          </Section>
          <Section title="People & retirement timing" detail="Account ownership refers to these members. Dates are planning inputs, not retirement projections.">
            <div className="space-y-4">{draft.members.map((m, i) => <div key={m.id} className="grid items-end gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-[1fr_1fr_auto]"><Field label={`Member ${i+1} name`}><input className={input} required maxLength={120} value={m.name} onChange={e => editRow('members', m.id, { name: e.target.value })} /></Field><Field label={`Member ${i+1} retirement date`}><input className={input} type="date" value={m.retirement_date ?? ''} onChange={e => editRow('members', m.id, { retirement_date: e.target.value || null })} /></Field><Remove name={`member ${i+1}`} onClick={() => removeRow('members', m.id)} /></div>)}</div>
            <button type="button" className={`${secondary} mt-4`} onClick={() => change('members', [...draft.members, { id: crypto.randomUUID(), name: '', retirement_date: null }])}>Add member</button>
          </Section>
          <Section title="Goals & priorities" detail="Capture a target and deadline where known. Goals do not automatically change portfolio rules or spending totals.">
            <div className="space-y-4">{draft.goals.map((g, i) => <div key={g.id} className="rounded-lg border border-slate-200 p-4"><div className="grid gap-3 sm:grid-cols-2"><Field label={`Goal ${i+1} name`}><input className={input} required maxLength={120} value={g.name} onChange={e => editRow('goals',g.id,{name:e.target.value})} /></Field><Field label={`Goal ${i+1} priority`}><select className={input} value={g.priority} onChange={e => editRow('goals',g.id,{priority:e.target.value as typeof g.priority})}>{['essential','important','aspirational'].map(v=><option key={v}>{v}</option>)}</select></Field><Field label={`Goal ${i+1} target amount (USD)`}><input className={input} type="number" min="0" max="1000000000000" step="0.01" placeholder="Unknown" value={g.amount ?? ''} onChange={e => editRow('goals',g.id,{amount:e.target.value || null})} /></Field><Field label={`Goal ${i+1} target date`}><input className={input} type="date" value={g.target_date ?? ''} onChange={e => editRow('goals',g.id,{target_date:e.target.value || null})} /></Field></div><div className="mt-3"><Remove name={`goal ${i+1}`} onClick={() => removeRow('goals',g.id)} /></div></div>)}</div>
            <button type="button" className={`${secondary} mt-4`} onClick={() => change('goals',[...draft.goals,{id:crypto.randomUUID(),name:'',priority:'important',target_date:null,amount:null}])}>Add goal</button>
          </Section>
          <Section title="Accounts & ownership" detail="Manual account inventory. These balances are separate from uploaded holdings and do not constitute net worth. Joint accounts are counted once.">
            <div className="space-y-4">{draft.accounts.map((a,i) => <div key={a.id} className="rounded-lg border border-slate-200 p-4"><div className="grid gap-3 sm:grid-cols-2"><Field label={`Account ${i+1} name`}><input className={input} required maxLength={120} value={a.name} onChange={e=>editRow('accounts',a.id,{name:e.target.value})} /></Field><Field label={`Account ${i+1} type`}><select className={input} value={a.account_type} onChange={e=>editRow('accounts',a.id,{account_type:e.target.value as Account['account_type']})}>{['Unknown','Taxable','Traditional IRA','Roth IRA','401(k)','Savings','Other'].map(v=><option key={v}>{v}</option>)}</select></Field><Field label={`Account ${i+1} balance (USD)`}><input className={input} type="number" min="0" max="1000000000000" step="0.01" placeholder="Unknown" value={a.balance ?? ''} onChange={e=>editRow('accounts',a.id,{balance:e.target.value || null})} /></Field><Field label={`Account ${i+1} valuation date`}><input className={input} type="date" required={a.balance!==null} value={a.as_of ?? ''} onChange={e=>editRow('accounts',a.id,{as_of:e.target.value || null})} /></Field><Field label={`Account ${i+1} evidence`}><select className={input} value={a.evidence} onChange={e=>editRow('accounts',a.id,{evidence:e.target.value as Account['evidence']})}><option value="estimated">Estimated</option><option value="confirmed">Confirmed by advisor</option></select></Field><fieldset><legend className="text-sm font-medium text-slate-700">Account {i+1} owners</legend><div className="mt-2 flex flex-wrap gap-3">{draft.members.map(m=><label key={m.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={a.owner_ids.includes(m.id)} onChange={e=>editRow('accounts',a.id,{owner_ids:e.target.checked ? [...a.owner_ids,m.id] : a.owner_ids.filter(id=>id!==m.id)})} />{m.name || 'Unnamed member'}</label>)}</div></fieldset></div><div className="mt-3"><Remove name={`account ${i+1}`} onClick={()=>removeRow('accounts',a.id)} /></div></div>)}</div>
            <button type="button" disabled={!draft.members.length} className={`${secondary} mt-4`} onClick={()=>change('accounts',[...draft.accounts,{id:crypto.randomUUID(),name:'',owner_ids:[],account_type:'Unknown',balance:null,as_of:null,evidence:'estimated'}])}>Add account</button>{!draft.members.length && <p className="mt-2 text-xs text-slate-500">Add a member first to assign account ownership.</p>}
          </Section>
          <Section title="Cash flow & irregular expenses" detail="Use take-home income and cash spending consistently. Annual amounts are spread across 12 months. Include tax payments not already deducted from income; avoid counting them twice. This is a current budget, not a retirement forecast.">
            <div className="space-y-4">{draft.cash_flows.map((c,i)=><div key={c.id} className="rounded-lg border border-slate-200 p-4"><div className="grid gap-3 sm:grid-cols-2"><Field label={`Cash flow ${i+1} name`}><input className={input} required maxLength={120} value={c.name} onChange={e=>editRow('cash_flows',c.id,{name:e.target.value})} /></Field><Field label={`Cash flow ${i+1} category`}><select className={input} value={c.kind} onChange={e=>editRow('cash_flows',c.id,{kind:e.target.value as CashFlow['kind']})}>{['income','essential','discretionary','irregular'].map(v=><option key={v}>{v}</option>)}</select></Field><Field label={`Cash flow ${i+1} amount (USD)`}><input className={input} type="number" min="0" max="1000000000000" step="0.01" placeholder="Unknown" value={c.amount ?? ''} onChange={e=>editRow('cash_flows',c.id,{amount:e.target.value || null})} /></Field><Field label={`Cash flow ${i+1} frequency`}><select className={input} value={c.frequency} onChange={e=>editRow('cash_flows',c.id,{frequency:e.target.value as CashFlow['frequency']})}><option value="monthly">Monthly</option><option value="annual">Annual</option></select></Field><Field label={`Cash flow ${i+1} evidence`}><select className={input} value={c.evidence} onChange={e=>editRow('cash_flows',c.id,{evidence:e.target.value as CashFlow['evidence']})}><option value="estimated">Estimated</option><option value="confirmed">Confirmed by advisor</option></select></Field></div><div className="mt-3"><Remove name={`cash flow ${i+1}`} onClick={()=>removeRow('cash_flows',c.id)} /></div></div>)}</div>
            <button type="button" className={`${secondary} mt-4`} onClick={()=>setDraft(p=>({...p,cash_flow_complete:false,cash_flows:[...p.cash_flows,{id:crypto.randomUUID(),name:'',kind:'essential',amount:null,frequency:'monthly',evidence:'estimated'}]}))}>Add cash flow</button>
            <label className="mt-5 flex items-start gap-3 rounded-lg bg-teal-50 p-4 text-sm text-teal-950"><input type="checkbox" className="mt-1" checked={draft.cash_flow_complete} disabled={!draft.cash_flows.length || draft.cash_flows.some(c=>c.amount===null)} onChange={e=>change('cash_flow_complete',e.target.checked)} /><span>I have reviewed the income and spending inventory for completeness.<span className="mt-1 block text-xs text-teal-800">Required to show a balance. Editing a cash-flow row resets this check. Estimates can remain, but missing amounts cannot.</span></span></label>
          </Section>
          </fieldset>
          <div className="sticky bottom-3 rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
            {error && <p role="alert" className="mb-3 break-words rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
            {conflict && saved && <button type="button" className={`${secondary} mb-3`} onClick={()=>open(saved.id)}>Discard draft and load latest household</button>}
            <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-sm text-slate-600">{busy ? 'Working…' : status || (dirty ? 'Unsaved changes' : saved ? `Saved version ${saved.version}` : 'Create a household to begin')}</p><button className={primary} type="submit" disabled={busy || (!dirty && !!saved)}>Save household</button></div>
          </div>
          </form>
          {saved && <section className="rounded-xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">Profile history</h2><button type="button" className={secondary} disabled={busy} onClick={async()=>{setBusy(true);try{setVersions((await householdRequest<{versions:HouseholdVersion[]}>(`/households/${saved.id}/versions`)).versions);}catch(e){setError(e instanceof Error?e.message:'Unable to load history.');}finally{setBusy(false);}}}>Load saved versions</button></div>{versions.map(v=><details key={v.version} className="mt-4 border-t border-slate-100 pt-3"><summary className="cursor-pointer text-sm">Version {v.version} · {new Date(v.created_at).toLocaleString()}</summary><p className="mt-2 text-sm">{v.profile.name} · {v.profile.members.length} members · {v.profile.goals.length} goals · {v.profile.accounts.length} accounts</p><div className="mt-3 space-y-3 rounded-lg bg-slate-50 p-4 text-sm">
              <p>Profile as of {v.profile.as_of} · Risk tolerance: {v.profile.risk_tolerance}</p>
              <p>{v.profile.priorities || 'Priorities not recorded.'}</p><p>Capacity for loss: {v.profile.risk_capacity_notes || 'Not recorded'}</p>
              <ul className="space-y-2">{v.profile.members.map(m=><li key={m.id}>{m.name} · Retirement: {m.retirement_date || 'Unknown'}</li>)}</ul>
              <ul className="space-y-2">{v.profile.goals.map(g=><li key={g.id}>{g.name} · {g.priority} · {money(g.amount)} · {g.target_date || 'Timing unknown'}</li>)}</ul>
              <ul className="space-y-2">{v.profile.accounts.map(a=><li key={a.id}>{a.name} · {a.account_type} · {money(a.balance)} · {a.as_of || 'Date unknown'} · {a.evidence} · Owners: {a.owner_ids.map(id=>v.profile.members.find(m=>m.id===id)?.name).join(', ')}</li>)}</ul>
              <ul className="space-y-2">{v.profile.cash_flows.map(c=><li key={c.id}>{c.name} · {c.kind} · {money(c.amount)} {c.frequency} · {c.evidence}</li>)}</ul>
              <p>Cash-flow inventory: {v.profile.cash_flow_complete ? 'Marked complete' : 'Incomplete'}</p>
            </div></details>)}</section>}
          <p className="px-1 text-xs leading-5 text-slate-500">Household context is internal and excluded from AI prompts and client brief exports. No authentication is enabled; use fictional information only. Linking a saved profile to a portfolio analysis preserves that version without changing its calculated findings.</p>
        </div>
      </div>
    </main>
  </div>;
}
