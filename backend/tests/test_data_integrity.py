"""Regression cases for invalid imports and cross-account exposure."""
import pytest
from fastapi.testclient import TestClient
from app import main
from app.analytics import build_summary
from app.ingestion import IngestionError, load_portfolio
from app.rules import rule_single_holding_concentration
from tests.conftest import api_client, make_csv

@pytest.mark.parametrize('column', ['shares', 'market_value', 'cost_basis'])
@pytest.mark.parametrize('value', ['inf', '-inf', 'NaN'])
def test_nonfinite_input_rejected(column, value):
    row = dict(zip(['ticker','security_name','asset_class','sector','shares','market_value','cost_basis','account_type','risk_tolerance','client_goal'],
                   ['AAPL','Apple','Equity','Technology','10','100','90','Taxable','Moderate','Growth']))
    row[column] = value
    with pytest.raises(IngestionError):
        load_portfolio(make_csv([','.join(row.values())]))

@pytest.mark.parametrize('column', ['security_name', 'asset_class', 'sector', 'client_goal'])
def test_required_text_cannot_be_blank(column):
    values = ['AAPL','Apple','Equity','Technology','10','100','90','Taxable','Moderate','Growth']
    columns = ['ticker','security_name','asset_class','sector','shares','market_value','cost_basis','account_type','risk_tolerance','client_goal']
    values[columns.index(column)] = ''
    with pytest.raises(IngestionError):
        load_portfolio(make_csv([','.join(values)]))


def test_same_security_aggregates_despite_name_and_case():
    portfolio = load_portfolio(make_csv([
        'aapl,Apple Inc,Equity,Technology,10,12000,10000,Taxable,Moderate,Growth',
        'AAPL,APPLE INC.,Equity,Technology,10,12000,11000,Roth IRA,Moderate,Growth',
        'CASH,Cash,Cash,Cash,76000,76000,76000,Taxable,Moderate,Growth',
    ]))
    flags = rule_single_holding_concentration(portfolio)
    assert len(flags) == 1
    assert flags[0].evidence['ticker'] == 'AAPL'
    assert flags[0].evidence['weight_pct'] == 24
    summary = build_summary(portfolio)
    apple = [h for h in summary['top_holdings'] if h['ticker'] == 'AAPL']
    assert len(apple) == 1
    assert apple[0]['market_value'] == 24000
    assert apple[0]['unrealized_gain_loss'] == 3000
    assert len(summary['holdings']) == 3  # Preserve original account rows.


def test_infinite_upload_returns_validation_error_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', tmp_path / 'test.db')
    with api_client() as client:
        response = client.post('/analyze/upload', files={'file': ('bad.csv', make_csv([
            'AAPL,Apple,Equity,Technology,10,inf,100,Taxable,Moderate,Growth'
        ]).encode(), 'text/csv')})
        assert response.status_code == 422
        assert client.get('/analyses').json()['analyses'] == []


def test_finite_rows_with_overflowing_total_rejected():
    with pytest.raises(IngestionError):
        load_portfolio(make_csv([
            'AAPL,Apple,Equity,Technology,1,1e308,1e308,Taxable,Moderate,Growth',
            'MSFT,Microsoft,Equity,Technology,1,1e308,1e308,Taxable,Moderate,Growth',
        ]))

@pytest.mark.parametrize('asset_class,sector', [('Cash','Technology'),('Equity','Healthcare')])
def test_conflicting_security_classification_rejected(asset_class, sector):
    with pytest.raises(IngestionError, match='conflicting'):
        load_portfolio(make_csv([
            'AAPL,Apple,Equity,Technology,1,100,90,Taxable,Moderate,Growth',
            f'aapl,Apple Inc,{asset_class},{sector},1,100,90,Roth IRA,Moderate,Growth',
        ]))


def test_sector_case_does_not_split_exposure():
    from app.rules import rule_sector_concentration
    portfolio = load_portfolio(make_csv([
        'AAPL,Apple,Equity,Technology,1,200,90,Taxable,Moderate,Growth',
        'MSFT,Microsoft,Equity,technology,1,200,90,Taxable,Moderate,Growth',
        'CASH,Cash,Cash,Cash,600,600,600,Taxable,Moderate,Growth',
    ]))
    flags = rule_sector_concentration(portfolio)
    assert len(flags) == 1
    assert flags[0].evidence['weight_pct'] == 40


def test_upload_reads_only_limit_plus_one():
    import asyncio
    from fastapi import HTTPException
    class OversizedUpload:
        filename = 'large.csv'
        async def read(self, size):
            assert size == main.MAX_UPLOAD_BYTES + 1
            return b'x' * size
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_upload(OversizedUpload()))
    assert exc.value.status_code == 413
