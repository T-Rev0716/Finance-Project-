"""Review workflow integration and transactional regression tests."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import db, main, reviews
from tests.conftest import make_csv


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / 'review.db'
    monkeypatch.setattr(main, 'DB_PATH', path)
    with TestClient(main.app) as client:
        analysis = client.post('/analyze/sample/growth_concentrated.csv').json()
        aid = analysis['analysis_id']
        queue = client.get(f'/analyses/{aid}/reviews').json()
        yield client, path, aid, queue['items'][0]['finding_id']


def write(client, aid, fid, status='discussed', note='Reviewed with client.', version=0):
    return client.put(f'/analyses/{aid}/reviews/{fid}', json={
        'status': status, 'note': note, 'expected_version': version,
    })


def test_initial_reviews_are_open_and_stable(setup):
    client, path, aid, fid = setup
    before = db.get_analysis(path, aid)
    one = client.get(f'/analyses/{aid}/reviews').json()
    two = client.get(f'/analyses/{aid}/reviews').json()
    assert one == two
    assert len(one['items']) == len(before['flags'])
    assert len({i['finding_id'] for i in one['items']}) == len(one['items'])
    assert all(i['status'] == 'open' and i['version'] == 0 and i['history'] == [] for i in one['items'])
    assert db.get_analysis(path, aid) == before  # Reads don't create events.


def test_persistence_history_and_original_findings(setup):
    client, path, aid, fid = setup
    before = db.get_analysis(path, aid)
    for version, status in enumerate(['discussed', 'follow_up', 'resolved', 'open']):
        assert write(client, aid, fid, status, f'Decision {version}', version).status_code == 200
    # New connection/service read simulates a reload/restart, not a UI cache.
    item = reviews.get_reviews(path, aid)['items'][0]
    assert item['status'] == 'open'
    assert item['version'] == 4
    assert [e['version'] for e in item['history']] == [4, 3, 2, 1]
    assert [e['note'] for e in item['history']] == ['Decision 3','Decision 2','Decision 1','Decision 0']
    after = db.get_analysis(path, aid)
    assert after['flags'] == before['flags']
    assert after['summary'] == before['summary']
    assert len([e for e in after['audit_log'] if e['event'] == 'finding_review_updated']) == 4


def test_notes_do_not_cross_analyses_or_findings(setup):
    client, path, aid, fid = setup
    other = client.post('/analyze/sample/growth_concentrated.csv').json()['analysis_id']
    assert write(client, aid, fid, note='Only this finding.').status_code == 200
    assert write(client, other, fid).status_code == 404
    assert all(i['version'] == 0 for i in reviews.get_reviews(path, other)['items'])
    assert all(i['version'] == 0 for i in reviews.get_reviews(path, aid)['items'][1:])


@pytest.mark.parametrize('payload', [
    {'status':'invalid','note':'text','expected_version':0},
    {'status':'resolved','note':'   ','expected_version':0},
    {'status':'open','note':'x'*4001,'expected_version':0},
    {'status':'open','note':'','expected_version':-1},
    {'status':'open','note':'','expected_version':'0'},
    {'status':'open','note':'','expected_version':True},
    {'status':'open','note':'','expected_version':0,'finding_id':'overwrite'},
    {'status':'open','note':''},
])
def test_validation_rejects_without_mutation(setup, payload):
    client, path, aid, fid = setup
    before = reviews.get_reviews(path, aid)
    assert client.put(f'/analyses/{aid}/reviews/{fid}', json=payload).status_code == 422
    assert reviews.get_reviews(path, aid) == before


def test_stale_update_does_not_overwrite_or_append_event(setup):
    client, path, aid, fid = setup
    assert write(client, aid, fid, note='First decision').status_code == 200
    assert write(client, aid, fid, note='Stale replacement').status_code == 409
    item = reviews.get_reviews(path, aid)['items'][0]
    assert item['note'] == 'First decision'
    assert len(item['history']) == 1


def test_two_concurrent_writers_only_one_wins(setup):
    _, path, aid, fid = setup
    def attempt(note):
        try:
            reviews.update_review(path, aid, fid, reviews.ReviewUpdate(status='discussed',note=note,expected_version=0))
            return 'saved'
        except reviews.ReviewConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ['One', 'Two'])) == ['conflict', 'saved']
    assert len(reviews.get_reviews(path, aid)['items'][0]['history']) == 1


def test_noop_save_does_not_duplicate_history(setup):
    client, path, aid, fid = setup
    first = write(client, aid, fid).json()
    second = write(client, aid, fid, version=1).json()
    assert first['version'] == second['version'] == 1
    assert len(reviews.get_reviews(path, aid)['items'][0]['history']) == 1


def test_unknown_records_are_not_created(setup):
    client, path, aid, fid = setup
    assert client.get('/analyses/99999/reviews').status_code == 404
    assert write(client, 99999, fid).status_code == 404
    assert write(client, aid, 'unknown').status_code == 404


def test_no_findings_empty_queue(setup, simple_csv):
    client, path, aid, fid = setup
    result = client.post('/analyze/upload', files={'file':('balanced.csv',simple_csv.encode(),'text/csv')}).json()
    assert client.get(f"/analyses/{result['analysis_id']}/reviews").json()['items'] == []


def test_internal_notes_do_not_enter_generated_briefs(setup):
    client, path, aid, fid = setup
    marker = 'PRIVATE_REVIEW_NOTE_123'
    write(client, aid, fid, note=marker)
    brief = client.get(f'/analyses/{aid}/brief').json()
    assert marker not in json.dumps(brief)
    assert marker not in client.get(f'/analyses/{aid}/brief/html').text


def test_audit_failure_rolls_back_state_and_history(setup):
    _, path, aid, fid = setup
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_review_audit BEFORE INSERT ON audit_log WHEN NEW.event = 'finding_review_updated' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        reviews.update_review(path, aid, fid, reviews.ReviewUpdate(status='discussed',note='Test',expected_version=0))
    item = reviews.get_reviews(path, aid)['items'][0]
    assert item['version'] == 0
    assert item['history'] == []


def test_legacy_database_gains_tables_without_rewriting_analysis(tmp_path):
    path = tmp_path / 'legacy.db'
    from app.service import analyze_csv
    source = make_csv(['AAPL,Apple,Equity,Technology,10,100,90,Taxable,Moderate,Growth'])
    aid = analyze_csv(source.encode(), 'old.csv', path)['analysis_id']
    original = db.get_analysis(path, aid)
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE finding_reviews')
        conn.execute('DROP TABLE review_events')
    assert reviews.get_reviews(path, aid)['items']
    assert db.get_analysis(path, aid) == original
