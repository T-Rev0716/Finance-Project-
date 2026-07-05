import pytest

from app.ingestion import IngestionError, load_portfolio
from tests.conftest import make_csv


def test_loads_valid_csv(simple_csv):
    portfolio = load_portfolio(simple_csv, source_name="simple.csv")
    assert len(portfolio.holdings) == 6
    assert portfolio.risk_tolerance == "Moderate"
    assert portfolio.client_goal == "Growth"
    assert portfolio.warnings == []
    # Derived columns exist and are correct.
    bnd = portfolio.holdings[portfolio.holdings["ticker"] == "BND"].iloc[0]
    assert bnd["unrealized_gain_loss"] == -1000.0
    assert bool(bnd["is_retirement_account"]) is True
    vti = portfolio.holdings[portfolio.holdings["ticker"] == "VTI"].iloc[0]
    assert bool(vti["is_retirement_account"]) is False


def test_loads_all_sample_files(samples_dir):
    files = sorted(samples_dir.glob("*.csv"))
    assert len(files) == 3
    for path in files:
        portfolio = load_portfolio(path.read_bytes(), source_name=path.name)
        assert len(portfolio.holdings) > 0
        assert portfolio.risk_tolerance in {"Conservative", "Moderate", "Aggressive"}


def test_missing_column_rejected():
    csv = "ticker,shares\nVTI,10\n"
    with pytest.raises(IngestionError) as exc:
        load_portfolio(csv)
    assert "Missing required column" in str(exc.value)


def test_non_numeric_market_value_rejected():
    csv = make_csv(
        ["VTI,Vanguard,Equity,Diversified,10,not_a_number,1000,Taxable,Moderate,Growth"]
    )
    with pytest.raises(IngestionError) as exc:
        load_portfolio(csv)
    assert "market_value" in str(exc.value)


def test_negative_market_value_rejected():
    csv = make_csv(["VTI,Vanguard,Equity,Diversified,10,-5000,1000,Taxable,Moderate,Growth"])
    with pytest.raises(IngestionError) as exc:
        load_portfolio(csv)
    assert "must not be negative" in str(exc.value)


def test_unknown_risk_tolerance_rejected():
    csv = make_csv(["VTI,Vanguard,Equity,Diversified,10,5000,1000,Taxable,YOLO,Growth"])
    with pytest.raises(IngestionError) as exc:
        load_portfolio(csv)
    assert "risk_tolerance" in str(exc.value)


def test_unknown_account_type_rejected():
    csv = make_csv(["VTI,Vanguard,Equity,Diversified,10,5000,1000,Margin,Moderate,Growth"])
    with pytest.raises(IngestionError) as exc:
        load_portfolio(csv)
    assert "account_type" in str(exc.value)


def test_empty_file_rejected():
    header_only = make_csv([])
    with pytest.raises(IngestionError) as exc:
        load_portfolio(header_only)
    assert "no holdings" in str(exc.value)


def test_case_insensitive_normalization():
    csv = make_csv(["vti,Vanguard,equity,Diversified,10,5000,1000,taxable,moderate,growth"])
    portfolio = load_portfolio(csv)
    row = portfolio.holdings.iloc[0]
    assert row["asset_class"] == "Equity"
    assert row["account_type"] == "Taxable"
    assert portfolio.risk_tolerance == "Moderate"


def test_mixed_risk_tolerance_warns():
    csv = make_csv(
        [
            "VTI,Vanguard,Equity,Diversified,10,5000,1000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,10,5000,1000,Taxable,Aggressive,Growth",
        ]
    )
    portfolio = load_portfolio(csv)
    assert portfolio.risk_tolerance == "Moderate"
    assert any("Multiple risk_tolerance" in w for w in portfolio.warnings)
