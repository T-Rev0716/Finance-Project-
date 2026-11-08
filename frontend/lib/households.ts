import { API_BASE } from './api';

export type Evidence = 'estimated' | 'confirmed';
export interface Member { id: string; name: string; retirement_date: string | null }
export interface Goal { id: string; name: string; priority: 'essential' | 'important' | 'aspirational'; target_date: string | null; amount: string | null }
export interface Account { id: string; name: string; owner_ids: string[]; account_type: 'Taxable' | 'Traditional IRA' | 'Roth IRA' | '401(k)' | 'Savings' | 'Other' | 'Unknown'; balance: string | null; as_of: string | null; evidence: Evidence }
export interface CashFlow { id: string; name: string; kind: 'income' | 'essential' | 'discretionary' | 'irregular'; amount: string | null; frequency: 'monthly' | 'annual'; evidence: Evidence }
export interface Profile {
  name: string; as_of: string; members: Member[]; goals: Goal[]; accounts: Account[]; cash_flows: CashFlow[];
  cash_flow_complete: boolean; priorities: string; risk_tolerance: 'unknown' | 'conservative' | 'moderate' | 'aggressive'; risk_capacity_notes: string;
}
export interface Household {
  id: number; version: number; updated_at: string; profile: Profile;
  summary: { known_account_total: string | null; account_total_complete: boolean; valuation_dates: string[]; mixed_valuation_dates: boolean;
    annual_known: Record<CashFlow['kind'], string>; annual_known_expenses: string; monthly_net: string | null; annual_net: string | null;
    cash_flow_complete: boolean; estimated_items: number; missing_information: string[] };
}
export interface HouseholdListItem { id: number; name: string; version: number }
export interface HouseholdVersion { version: number; created_at: string; profile: Profile }
export interface HouseholdContext { household_id: number; version: number; linked_at: string; profile: Profile }
export class HouseholdError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function householdRequest<T>(path: string, method = 'GET', payload?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method, cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((d: { loc: (string | number)[]; msg: string }) => `${d.loc.filter(x => x !== 'body').join(' → ')}: ${d.msg}`).join('; ')
      : 'Unable to save household. Please try again.';
    throw new HouseholdError(message, response.status);
  }
  return data;
}
export function emptyProfile(): Profile {
  return { name: '', as_of: new Date().toLocaleDateString('en-CA'), members: [], goals: [], accounts: [], cash_flows: [],
    cash_flow_complete: false, priorities: '', risk_tolerance: 'unknown', risk_capacity_notes: '' };
}
export function demoProfile(): Profile {
  const today = new Date().toLocaleDateString('en-CA');
  return { name: 'Morgan & Avery · fictional household', as_of: today,
    priorities: 'Retire together, spend time with family, and keep room in the budget for travel and home repairs.',
    risk_tolerance: 'moderate', risk_capacity_notes: 'Discuss how an early market decline would affect planned withdrawals. Capacity for loss has not yet been established.',
    members: [{ id: 'morgan', name: 'Morgan', retirement_date: '2030-06-01' }, { id: 'avery', name: 'Avery', retirement_date: '2030-06-01' }],
    goals: [{ id: 'retirement', name: 'Retirement spending per year', priority: 'essential', target_date: '2030-06-01', amount: '72000' },
      { id: 'travel', name: 'Family trip', priority: 'aspirational', target_date: '2031-07-01', amount: null }],
    accounts: [{ id: 'ira', name: 'Morgan retirement account', owner_ids: ['morgan'], account_type: 'Traditional IRA', balance: '520000', as_of: today, evidence: 'estimated' },
      { id: 'reserve', name: 'Joint savings', owner_ids: ['morgan','avery'], account_type: 'Savings', balance: '40000', as_of: today, evidence: 'estimated' }],
    cash_flows: [{ id: 'pay', name: 'Take-home pay', kind: 'income', amount: '9000', frequency: 'monthly', evidence: 'estimated' },
      { id: 'essential', name: 'Housing, food and core bills', kind: 'essential', amount: '4200', frequency: 'monthly', evidence: 'estimated' },
      { id: 'fun', name: 'Travel and discretionary spending', kind: 'discretionary', amount: '1200', frequency: 'monthly', evidence: 'estimated' },
      { id: 'repairs', name: 'Home and vehicle reserve', kind: 'irregular', amount: '12000', frequency: 'annual', evidence: 'estimated' }],
    cash_flow_complete: true };
}
