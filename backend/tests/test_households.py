"""Household data contract, calculations, history and cross-analysis boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import closing
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app import db, households, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', tmp_path/'test.db')
    return TestClient(main.app)


@pytest.fixture
def profile():
    return {
        'name': 'Fictional household', 'as_of': '2026-11-07',
        'members': [{'id':'a','name':'Avery'}, {'id':'b','name':'Morgan'}],
        'goals': [{'id':'g','name':'Retire','target_date':'2030-01-01','amount':None}],
        'accounts': [{'id':'joint','name':'Joint','owner_ids':['a','b'],'balance':'1000.01','as_of':'2026-11-07'},
                     {'id':'ira','name':'IRA','owner_ids':['a'],'balance':None}],
        'cash_flows': [
            {'id':'i','name':'Net pay','kind':'income','amount':'5000.01','frequency':'monthly'},
            {'id':'e','name':'Bills','kind':'essential','amount':'3000','frequency':'monthly'},
            {'id':'r','name':'Repairs','kind':'irregular','amount':'12000','frequency':'annual'}],
        'cash_flow_complete':True,
    }


def make(client, profile):
    r=client.post('/households',json=profile)
    assert r.status_code==201, r.text
    return r.json()


def test_cash_flow_decimal_conversion_and_joint_account_once(client,profile):
    record=make(client,profile)
    s=record['summary']
    assert s['known_account_total']=='1000.01'
    assert s['account_total_complete'] is False
    assert s['annual_known']['income']=='60000.12'
    assert s['annual_known_expenses']=='48000.00'
    assert s['monthly_net']=='1000.01'
    assert s['annual_net']=='12000.12'
    assert record['profile']['goals'][0]['amount'] is None


def test_unknown_not_zero_and_incomplete_never_shows_surplus(client,profile):
    profile['cash_flow_complete']=False
    profile['cash_flows'][1]['amount']=None
    record=make(client,profile)
    assert record['summary']['monthly_net'] is None
    assert record['summary']['annual_net'] is None
    assert any('Bills' in item for item in record['summary']['missing_information'])
    profile['cash_flows'][1]['amount']='0'
    profile['cash_flow_complete']=True
    record=make(client,profile)
    assert record['summary']['monthly_net']=='4000.01'


def test_empty_household_is_valid_incomplete_context(client):
    r=make(client,{'name':'New household','as_of':'2026-11-07'})
    assert r['summary']['account_total_complete'] is False
    assert r['summary']['monthly_net'] is None
    assert len(r['summary']['missing_information'])>=5


@pytest.mark.parametrize('amount', ['-1','NaN','Infinity','0.001','1000000000001',True,''])
def test_invalid_money_rejected_without_writes(client,profile,amount):
    profile['cash_flows'][0]['amount']=amount
    assert client.post('/households',json=profile).status_code==422
    assert client.get('/households').json()['households']==[]


@pytest.mark.parametrize('mutation', [
    lambda p: p['accounts'][0].update(owner_ids=['stranger']),
    lambda p: p['accounts'][0].update(owner_ids=['a','a']),
    lambda p: p['accounts'][0].update(owner_ids=[]),
    lambda p: p['accounts'][0].update(as_of=None),
    lambda p: p['members'].append(deepcopy(p['members'][0])),
    lambda p: p['cash_flows'][0].update(amount=None),
    lambda p: p.update(cash_flows=[]),
    lambda p: p.update(name='  '),
    lambda p: p.update(as_of='2026-02-30'),
    lambda p: p.update(unrecognized='unexpected'),
    lambda p: p.update(cash_flow_complete='true'),
])
def test_invalid_relationships_and_fields(client,profile,mutation):
    mutation(profile)
    assert client.post('/households',json=profile).status_code==422


def test_mixed_dates_and_negative_cash_flow(client,profile):
    profile['accounts'][1].update(balance='10',as_of='2026-10-01')
    profile['cash_flows'][0]['amount']='1000'
    record=make(client,profile)
    assert record['summary']['mixed_valuation_dates'] is True
    assert record['summary']['account_total_complete'] is True
    assert record['summary']['monthly_net']=='-3000.00'


def test_update_persists_history_and_noop_has_no_revision(client,profile):
    first=make(client,profile)
    path=f"/households/{first['id']}"
    profile['name']='Updated household'
    second=client.put(path,json={'profile':profile,'expected_version':1}).json()
    assert second['version']==2
    assert client.get(path).json()==second
    assert client.put(path,json={'profile':profile,'expected_version':2}).json()['version']==2
    versions=client.get(path+'/versions').json()['versions']
    assert len(versions)==2
    assert versions[-1]['profile']['name']=='Fictional household'
    assert client.put(path,json={'profile':profile,'expected_version':1}).status_code==409


def test_two_writers_only_one_wins(client,profile):
    first=make(client,profile)
    def write(name):
        p=deepcopy(profile);p['name']=name
        return client.put(f"/households/{first['id']}",json={'profile':p,'expected_version':1}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write,['First','Second']))==[200,409]
    assert len(client.get(f"/households/{first['id']}/versions").json()['versions'])==2


def test_context_is_frozen_and_analysis_and_brief_unchanged(client,profile):
    hid=make(client,profile)['id']
    aid=client.post('/analyze/sample/growth_concentrated.csv').json()['analysis_id']
    before=client.get(f'/analyses/{aid}').json()
    brief=client.get(f'/analyses/{aid}/brief').json()
    assert client.get(f'/analyses/{aid}/household').json()=={'context':None}
    path=f'/analyses/{aid}/household'
    r=client.post(path,json={'household_id':hid,'expected_version':1})
    assert r.status_code==201
    profile['name']='New identity';profile['priorities']='INTERNAL_PRIVATE_SENTINEL'
    client.put(f'/households/{hid}',json={'profile':profile,'expected_version':1})
    context=client.get(path).json()['context']
    assert context['profile']['name']=='Fictional household'
    assert context['version']==1
    assert client.post(path,json={'household_id':hid,'expected_version':2}).status_code==409
    after=client.get(f'/analyses/{aid}').json()
    for key in ['flags','summary','engine_version','risk_tolerance','client_goal']:
        assert after[key]==before[key]
    assert client.get(f'/analyses/{aid}/brief').json()==brief
    assert 'INTERNAL_PRIVATE_SENTINEL' not in json.dumps(client.post(f'/analyses/{aid}/brief').json())
    aid2=client.post('/analyze/sample/growth_concentrated.csv').json()['analysis_id']
    assert client.get(f'/analyses/{aid2}/household').json()['context'] is None


def test_attach_stale_version_and_missing_records(client,profile):
    hid=make(client,profile)['id']
    aid=client.post('/analyze/sample/growth_concentrated.csv').json()['analysis_id']
    assert client.post(f'/analyses/{aid}/household',json={'household_id':hid,'expected_version':2}).status_code==409
    assert client.post(f'/analyses/{aid}/household',json={'household_id':999,'expected_version':1}).status_code==404
    assert client.post('/analyses/999/household',json={'household_id':hid,'expected_version':1}).status_code==404
    assert client.get('/analyses/999/household').status_code==404
    assert client.get('/households/999').status_code==404
    assert client.get('/households/999/versions').status_code==404
    assert client.put('/households/999',json={'profile':profile,'expected_version':1}).status_code==404


def test_foreign_household_member_cannot_be_account_owner(client,profile):
    make(client,profile)
    profile['members']=[{'id':'c','name':'Another household member'}]
    assert client.post('/households',json=profile).status_code==422


def test_atomic_rollback_on_history_failure(client,profile):
    hid=make(client,profile)['id']
    with closing(db._connect(main.DB_PATH)) as conn, conn:
        conn.execute("CREATE TRIGGER fail_history BEFORE INSERT ON household_versions BEGIN SELECT RAISE(ABORT,'fail'); END")
    profile['name']='Should not persist'
    with pytest.raises(sqlite3.IntegrityError):
        households.update(main.DB_PATH,hid,households.Update(profile=households.Profile(**profile),expected_version=1))
    assert client.get(f'/households/{hid}').json()['version']==1
    assert client.get(f'/households/{hid}').json()['profile']['name']=='Fictional household'


def test_additive_schema_preserves_legacy_analysis(tmp_path):
    path=tmp_path/'legacy.db'
    # Existing analyses and reviews are untouched when the household schema is added.
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE analyses (id INTEGER PRIMARY KEY, marker TEXT)')
        conn.execute("INSERT INTO analyses VALUES (7,'historical')")
    with closing(db._connect(path)) as conn:
        assert conn.execute('SELECT marker FROM analyses WHERE id=7').fetchone()[0]=='historical'
        assert conn.execute('SELECT COUNT(*) FROM households').fetchone()[0]==0
