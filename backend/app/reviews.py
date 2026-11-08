"""Analysis-scoped advisor decisions, separate from immutable engine findings.

This local synthetic-data workflow is not an authentication/authorization layer.
"""
import hashlib
import json
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import db

ReviewStatus = Literal['open', 'discussed', 'follow_up', 'resolved']


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: ReviewStatus
    note: str = Field(default='', max_length=4000)
    expected_version: int = Field(ge=0, strict=True)

    @model_validator(mode='after')
    def resolution_needs_reason(self):
        if self.status == 'resolved' and not self.note:
            raise ValueError('Add a decision note before resolving a finding.')
        return self


class ReviewNotFound(Exception):
    pass


class ReviewConflict(Exception):
    pass


def finding_ids(analysis: dict) -> list[str]:
    # Original index distinguishes even identical rule/evidence rows. Stored
    # findings are immutable; identities are stable across reloads and restarts.
    return [hashlib.sha256(json.dumps(
        [analysis['id'], index, flag], sort_keys=True, separators=(',', ':')
    ).encode()).hexdigest()[:24] for index, flag in enumerate(analysis['flags'])]


def _analysis(db_path, analysis_id):
    analysis = db.get_analysis(db_path, analysis_id)
    if analysis is None:
        raise ReviewNotFound('Analysis not found.')
    return analysis


def get_reviews(db_path, analysis_id: int) -> dict:
    analysis = _analysis(db_path, analysis_id)
    with closing(db._connect(db_path)) as conn:
        conn.execute('BEGIN')
        states = {r['finding_id']: dict(r) for r in conn.execute(
            'SELECT * FROM finding_reviews WHERE analysis_id = ?', (analysis_id,))}
        events = [dict(r) for r in conn.execute(
            'SELECT finding_id, status, note, version, created_at FROM review_events '
            'WHERE analysis_id = ? ORDER BY id DESC', (analysis_id,))]
    items = []
    for finding_id, flag in zip(finding_ids(analysis), analysis['flags']):
        state = states.get(finding_id, {})
        items.append({
            'finding_id': finding_id, 'flag': flag,
            'status': state.get('status', 'open'), 'note': state.get('note', ''),
            'version': state.get('version', 0), 'updated_at': state.get('updated_at'),
            'history': [e for e in events if e['finding_id'] == finding_id],
        })
    return {'analysis_id': analysis_id, 'items': items}


def update_review(db_path, analysis_id: int, finding_id: str, update: ReviewUpdate) -> dict:
    analysis = _analysis(db_path, analysis_id)
    if finding_id not in finding_ids(analysis):
        raise ReviewNotFound('Finding does not belong to this analysis.')
    with closing(db._connect(db_path)) as conn, conn:
        # Serialize writers, then check the version inside the same transaction.
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute(
            'SELECT * FROM finding_reviews WHERE analysis_id = ? AND finding_id = ?',
            (analysis_id, finding_id)).fetchone()
        version = current['version'] if current else 0
        if version != update.expected_version:
            raise ReviewConflict('This finding was updated elsewhere. Reload its latest review before saving.')
        if current and current['status'] == update.status and current['note'] == update.note:
            return dict(current)  # No fabricated duplicate audit event.
        version += 1
        now = db._now()
        conn.execute('''INSERT INTO finding_reviews
            (analysis_id, finding_id, status, note, version, updated_at) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(analysis_id, finding_id) DO UPDATE SET
            status=excluded.status, note=excluded.note, version=excluded.version,
            updated_at=excluded.updated_at''',
            (analysis_id, finding_id, update.status, update.note, version, now))
        conn.execute('''INSERT INTO review_events
            (analysis_id, finding_id, status, note, version, created_at) VALUES (?, ?, ?, ?, ?, ?)''',
            (analysis_id, finding_id, update.status, update.note, version, now))
        conn.execute('INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)',
            (analysis_id, 'finding_review_updated', json.dumps({
                'finding_id': finding_id, 'version': version, 'status': update.status,
                'previous_status': current['status'] if current else 'open',
            }), now))
    return {'finding_id': finding_id, 'status': update.status, 'note': update.note,
            'version': version, 'updated_at': now}
