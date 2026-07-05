from app.analytics import build_summary
from app.ingestion import load_portfolio


def test_totals_and_gain_loss(simple_csv):
    summary = build_summary(load_portfolio(simple_csv))
    assert summary["total_market_value"] == 100000.0
    assert summary["total_cost_basis"] == 93000.0
    assert summary["total_unrealized_gain_loss"] == 7000.0
    assert summary["holdings_count"] == 6


def test_asset_allocation(simple_csv):
    summary = build_summary(load_portfolio(simple_csv))
    allocation = {a["name"]: a for a in summary["asset_allocation"]}
    assert allocation["Equity"]["market_value"] == 54000.0
    assert allocation["Equity"]["weight_pct"] == 54.0
    assert allocation["Fixed Income"]["weight_pct"] == 38.0
    assert allocation["Cash"]["weight_pct"] == 8.0
    # Sorted descending by market value.
    assert [a["name"] for a in summary["asset_allocation"]] == ["Equity", "Fixed Income", "Cash"]


def test_sector_allocation(simple_csv):
    summary = build_summary(load_portfolio(simple_csv))
    sectors = {s["name"]: s["weight_pct"] for s in summary["sector_allocation"]}
    assert sectors["Diversified"] == 18.0
    assert sectors["Bond"] == 20.0
    assert sectors["Corporate Bond"] == 18.0


def test_top_holdings(simple_csv):
    summary = build_summary(load_portfolio(simple_csv))
    top = summary["top_holdings"]
    assert top[0]["ticker"] == "BND"
    assert top[0]["weight_pct"] == 20.0
    assert top[0]["unrealized_gain_loss"] == -1000.0
    assert len(top) == 5


def test_weights_sum_to_100(simple_csv):
    summary = build_summary(load_portfolio(simple_csv))
    for key in ("asset_allocation", "sector_allocation", "account_type_allocation"):
        total = sum(item["weight_pct"] for item in summary[key])
        assert abs(total - 100.0) < 0.05, key
