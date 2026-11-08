"""Versioned synthetic household context. No financial advice or client authentication."""
from contextlib import closing
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import db

Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000_000, max_digits=15, decimal_places=2, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=120)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Member(Model):
    id: Text
    name: Text
    retirement_date: date | None = None


class Goal(Model):
    id: Text
    name: Text
    priority: Literal['essential', 'important', 'aspirational'] = 'important'
    target_date: date | None = None
    amount: Money | None = None


class Account(Model):
    id: Text
    name: Text
    owner_ids: list[Text] = Field(min_length=1, max_length=20)
    account_type: Literal['Taxable', 'Traditional IRA', 'Roth IRA', '401(k)', 'Savings', 'Other', 'Unknown'] = 'Unknown'
    balance: Money | None = None
    as_of: date | None = None
    evidence: Literal['estimated', 'confirmed'] = 'estimated'

    @model_validator(mode='after')
    def known_balance_has_date(self):
        if self.balance is not None and self.as_of is None:
            raise ValueError('A known account balance needs a valuation date.')
        if len(set(self.owner_ids)) != len(self.owner_ids):
            raise ValueError('An account owner may only appear once.')
        return self


class CashFlow(Model):
    id: Text
    name: Text
    kind: Literal['income', 'essential', 'discretionary', 'irregular']
    amount: Money | None = None
    frequency: Literal['monthly', 'annual'] = 'monthly'
    evidence: Literal['estimated', 'confirmed'] = 'estimated'


class Profile(Model):
    name: Text
    as_of: date
    members: list[Member] = Field(default_factory=list, max_length=20)
    goals: list[Goal] = Field(default_factory=list, max_length=50)
    accounts: list[Account] = Field(default_factory=list, max_length=100)
    cash_flows: list[CashFlow] = Field(default_factory=list, max_length=100)
    cash_flow_complete: bool = Field(default=False, strict=True)
    priorities: str = Field(default='', max_length=2000)
    risk_tolerance: Literal['unknown', 'conservative', 'moderate', 'aggressive'] = 'unknown'
    risk_capacity_notes: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_relationships(self):
        for rows in (self.members, self.goals, self.accounts, self.cash_flows):
            ids = [row.id for row in rows]
            if len(ids) != len(set(ids)):
                raise ValueError('Row IDs must be unique within each section.')
        members = {member.id for member in self.members}
        for account in self.accounts:
            if not set(account.owner_ids) <= members:
                raise ValueError('Account owners must belong to this household.')
        if self.cash_flow_complete and (not self.cash_flows or any(row.amount is None for row in self.cash_flows)):
            raise ValueError('Enter all cash-flow amounts before marking the inventory complete.')
        return self


class Update(Model):
    profile: Profile
    expected_version: int = Field(ge=1, strict=True)


class Link(Model):
    household_id: int = Field(ge=1, strict=True)
    expected_version: int = Field(ge=1, strict=True)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def summarize(profile: Profile) -> dict:
    annual = {kind: Decimal(0) for kind in ('income', 'essential', 'discretionary', 'irregular')}
    for row in profile.cash_flows:
        if row.amount is not None:
            annual[row.kind] += row.amount * (12 if row.frequency == 'monthly' else 1)
    expenses = sum((annual[k] for k in ('essential', 'discretionary', 'irregular')), Decimal(0))
    complete = profile.cash_flow_complete
    missing = []
    if not profile.members:
        missing.append('Add household members.')
    if not profile.goals:
        missing.append('Record the household’s goals.')
    for goal in profile.goals:
        if goal.amount is None or goal.target_date is None:
            missing.append(f'Confirm amount and timing: {goal.name}.')
    if not profile.accounts:
        missing.append('Add accounts and ownership.')
    for account in profile.accounts:
        if account.account_type == 'Unknown':
            missing.append(f'Confirm account type: {account.name}.')
        if account.balance is None:
            missing.append(f'Confirm balance: {account.name}.')
    if not complete:
        missing.append('Complete the income and spending inventory before interpreting a surplus or shortfall.')
    for row in profile.cash_flows:
        if row.amount is None:
            missing.append(f'Confirm cash flow: {row.name}.')
    if profile.risk_tolerance == 'unknown':
        missing.append('Discuss risk tolerance.')
    if not profile.risk_capacity_notes:
        missing.append('Document capacity for loss separately from risk tolerance.')
    balances = [a.balance for a in profile.accounts if a.balance is not None]
    dates = sorted({a.as_of.isoformat() for a in profile.accounts if a.balance is not None and a.as_of})
    return {
        'known_account_total': _money(sum(balances, Decimal(0))) if balances else None,
        'account_total_complete': bool(profile.accounts) and len(balances) == len(profile.accounts),
        'valuation_dates': dates, 'mixed_valuation_dates': len(dates) > 1,
        'annual_known': {k: _money(v) for k, v in annual.items()},
        'annual_known_expenses': _money(expenses),
        'monthly_net': _money((annual['income'] - expenses) / 12) if complete else None,
        'annual_net': _money(annual['income'] - expenses) if complete else None,
        'cash_flow_complete': complete,
        'estimated_items': sum(r.evidence == 'estimated' for r in [*profile.accounts, *profile.cash_flows]),
        'missing_information': missing,
    }


def _record(row) -> dict:
    profile = Profile.model_validate_json(row['profile_json'])
    return {'id': row['id'], 'version': row['version'], 'updated_at': row['updated_at'],
            'profile': profile.model_dump(mode='json'), 'summary': summarize(profile)}


def _find(conn, household_id):
    row = conn.execute('SELECT * FROM households WHERE id = ?', (household_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Household not found.')
    return row


def _event(conn, household_id, version, profile_json, now):
    conn.execute('INSERT INTO household_versions (household_id, version, profile_json, created_at) VALUES (?, ?, ?, ?)',
                 (household_id, version, profile_json, now))
    conn.execute('INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (NULL, ?, ?, ?)',
                 ('household_saved', json.dumps({'household_id': household_id, 'version': version}), now))


def create(db_path, profile: Profile) -> dict:
    with closing(db._connect(db_path)) as conn, conn:
        now = db._now()
        payload = profile.model_dump_json()
        hid = conn.execute('INSERT INTO households (version, profile_json, updated_at) VALUES (1, ?, ?)', (payload, now)).lastrowid
        _event(conn, hid, 1, payload, now)
        return _record(_find(conn, hid))


def update(db_path, household_id: int, request: Update) -> dict:
    with closing(db._connect(db_path)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _find(conn, household_id)
        if row['version'] != request.expected_version:
            raise HTTPException(409, 'This household was updated elsewhere. Your draft has not been saved. Load the latest version before trying again.')
        payload = request.profile.model_dump_json()
        if row['profile_json'] == payload:
            return _record(row)
        version, now = row['version'] + 1, db._now()
        conn.execute('UPDATE households SET version=?, profile_json=?, updated_at=? WHERE id=?', (version, payload, now, household_id))
        _event(conn, household_id, version, payload, now)
        return _record(_find(conn, household_id))


def get(db_path, household_id):
    with closing(db._connect(db_path)) as conn:
        return _record(_find(conn, household_id))


def _linked(conn, analysis_id):
    row = conn.execute('''SELECT h.household_id, h.version, h.linked_at, v.profile_json
        FROM analysis_households h JOIN household_versions v
        ON h.household_id=v.household_id AND h.version=v.version WHERE h.analysis_id=?''', (analysis_id,)).fetchone()
    if row is None:
        return None
    return {'household_id': row['household_id'], 'version': row['version'], 'linked_at': row['linked_at'],
            'profile': json.loads(row['profile_json'])}


def router(db_path_provider):
    api = APIRouter()

    @api.get('/households')
    def list_households():
        with closing(db._connect(db_path_provider())) as conn:
            rows = conn.execute('SELECT * FROM households ORDER BY id DESC').fetchall()
            return {'households': [{'id': r['id'], 'name': json.loads(r['profile_json'])['name'],
                                     'version': r['version']} for r in rows]}

    @api.post('/households', status_code=201)
    def new_household(profile: Profile):
        return create(db_path_provider(), profile)

    @api.get('/households/{household_id}')
    def read_household(household_id: int):
        return get(db_path_provider(), household_id)

    @api.put('/households/{household_id}')
    def save_household(household_id: int, request: Update):
        return update(db_path_provider(), household_id, request)

    @api.get('/households/{household_id}/versions')
    def history(household_id: int):
        with closing(db._connect(db_path_provider())) as conn:
            _find(conn, household_id)
            return {'versions': [{'version': r['version'], 'created_at': r['created_at'],
                                  'profile': json.loads(r['profile_json'])} for r in conn.execute(
                'SELECT * FROM household_versions WHERE household_id=? ORDER BY version DESC', (household_id,))]}

    @api.get('/analyses/{analysis_id}/household')
    def context(analysis_id: int):
        with closing(db._connect(db_path_provider())) as conn:
            if not conn.execute('SELECT id FROM analyses WHERE id=?', (analysis_id,)).fetchone():
                raise HTTPException(404, 'Analysis not found.')
            return {'context': _linked(conn, analysis_id)}

    @api.post('/analyses/{analysis_id}/household', status_code=201)
    def attach(analysis_id: int, request: Link):
        with closing(db._connect(db_path_provider())) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT id FROM analyses WHERE id=?', (analysis_id,)).fetchone():
                raise HTTPException(404, 'Analysis not found.')
            row = _find(conn, request.household_id)
            if row['version'] != request.expected_version:
                raise HTTPException(409, 'The household changed. Refresh the household list before attaching.')
            if _linked(conn, analysis_id):
                raise HTTPException(409, 'This analysis already has a household snapshot. Create a new analysis for different context.')
            now = db._now()
            conn.execute('INSERT INTO analysis_households (analysis_id, household_id, version, linked_at) VALUES (?, ?, ?, ?)',
                         (analysis_id, request.household_id, request.expected_version, now))
            conn.execute('INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)',
                         (analysis_id, 'household_context_attached', request.model_dump_json(), now))
            return {'context': _linked(conn, analysis_id)}

    return api
