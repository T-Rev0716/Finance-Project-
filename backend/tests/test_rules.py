from app.ingestion import load_portfolio
from app.rules import run_rules
from tests.conftest import make_csv


def _rule_ids(csv: str) -> list[str]:
    return [f.rule_id for f in run_rules(load_portfolio(csv))]


def test_clean_portfolio_has_no_flags(simple_csv):
    assert run_rules(load_portfolio(simple_csv)) == []


# --- Rule 1: single holding > 20% ---

def test_single_holding_concentration_triggers():
    csv = make_csv(
        [
            "NVDA,NVIDIA Corp,Equity,Technology,100,25000,10000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,20000,19500,Taxable,Moderate,Growth",
            "SPAXX,Money Market,Cash,Cash,15000,15000,15000,Taxable,Moderate,Growth",
        ]
    )
    flags = run_rules(load_portfolio(csv))
    concentration = [f for f in flags if f.rule_id == "concentration_single_holding"]
    assert len(concentration) == 1
    assert concentration[0].evidence["ticker"] == "NVDA"
    assert concentration[0].evidence["weight_pct"] == 25.0
    assert concentration[0].severity == "high"


def test_single_holding_at_exactly_20_pct_does_not_trigger():
    csv = make_csv(
        [
            "NVDA,NVIDIA Corp,Equity,Technology,100,20000,10000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,20000,19500,Taxable,Moderate,Growth",
            "SPAXX,Money Market,Cash,Cash,20000,20000,20000,Taxable,Moderate,Growth",
        ]
    )
    assert "concentration_single_holding" not in _rule_ids(csv)


def test_cash_position_exempt_from_holding_concentration():
    csv = make_csv(
        [
            "SPAXX,Money Market,Cash,Cash,30000,30000,30000,Taxable,Aggressive,Growth",
            "VTI,Vanguard Total Stock,Equity,Diversified,100,19000,15000,Taxable,Aggressive,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,17000,16500,Taxable,Aggressive,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,17000,16500,Taxable,Aggressive,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,17000,16500,Taxable,Aggressive,Growth",
        ]
    )
    ids = _rule_ids(csv)
    assert "concentration_single_holding" not in ids
    assert "cash_drag" in ids  # cash is 30%, still caught by the cash rule


def test_same_ticker_across_accounts_is_aggregated():
    csv = make_csv(
        [
            "NVDA,NVIDIA Corp,Equity,Technology,50,12000,6000,Taxable,Moderate,Growth",
            "NVDA,NVIDIA Corp,Equity,Technology,50,12000,6000,Roth IRA,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,19000,18500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,19000,18500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,19000,18500,Taxable,Moderate,Growth",
            "SPAXX,Money Market,Cash,Cash,19000,19000,19000,Taxable,Moderate,Growth",
        ]
    )
    flags = [f for f in run_rules(load_portfolio(csv)) if f.rule_id == "concentration_single_holding"]
    assert len(flags) == 1
    assert flags[0].evidence["weight_pct"] == 24.0  # 24k of 100k, aggregated


# --- Rule 2: sector > 35% ---

def test_sector_concentration_triggers():
    csv = make_csv(
        [
            "MSFT,Microsoft,Equity,Technology,10,20000,15000,Taxable,Moderate,Growth",
            "AAPL,Apple,Equity,Technology,10,20000,15000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,20000,19500,Taxable,Moderate,Growth",
        ]
    )
    flags = [f for f in run_rules(load_portfolio(csv)) if f.rule_id == "concentration_sector"]
    assert len(flags) == 1
    assert flags[0].evidence["sector"] == "Technology"
    assert flags[0].evidence["weight_pct"] == 40.0
    assert flags[0].evidence["tickers"] == ["AAPL", "MSFT"]


def test_sector_at_exactly_35_pct_does_not_trigger():
    csv = make_csv(
        [
            "MSFT,Microsoft,Equity,Technology,10,17500,15000,Taxable,Moderate,Growth",
            "AAPL,Apple,Equity,Technology,10,17500,15000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,20000,19500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,15000,14500,Taxable,Moderate,Growth",
            "SPAXX,Money Market,Cash,Cash,10000,10000,10000,Taxable,Moderate,Growth",
        ]
    )
    assert "concentration_sector" not in _rule_ids(csv)


# --- Rule 3: cash > 10% ---

def test_cash_drag_triggers():
    csv = make_csv(
        [
            "SPAXX,Money Market,Cash,Cash,15000,15000,15000,Taxable,Moderate,Growth",
            "VTI,Vanguard Total Stock,Equity,Diversified,100,17000,15000,Taxable,Moderate,Growth",
            "SCHD,Schwab Dividend,Equity,Dividend Equity,100,17000,15000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,17000,16500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,17000,16500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,17000,16500,Taxable,Moderate,Growth",
        ]
    )
    flags = [f for f in run_rules(load_portfolio(csv)) if f.rule_id == "cash_drag"]
    assert len(flags) == 1
    assert flags[0].evidence["weight_pct"] == 15.0


def test_cash_at_exactly_10_pct_does_not_trigger():
    csv = make_csv(
        [
            "SPAXX,Money Market,Cash,Cash,10000,10000,10000,Taxable,Moderate,Growth",
            "VTI,Vanguard Total Stock,Equity,Diversified,100,18000,15000,Taxable,Moderate,Growth",
            "SCHD,Schwab Dividend,Equity,Dividend Equity,100,18000,15000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,18000,17500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,18000,17500,Taxable,Moderate,Growth",
            "VGIT,Vanguard Govt Bond,Fixed Income,Government Bond,100,18000,17500,Taxable,Moderate,Growth",
        ]
    )
    assert "cash_drag" not in _rule_ids(csv)


# --- Rule 4: conservative + high equity ---

def test_conservative_high_equity_triggers():
    csv = make_csv(
        [
            "VTI,Vanguard Total Stock,Equity,Diversified,100,19000,15000,Taxable,Conservative,Income",
            "SCHD,Schwab Dividend,Equity,Diversified,100,18000,15000,Taxable,Conservative,Income",
            "VXUS,Vanguard Intl,Equity,Diversified International,100,18000,15000,Taxable,Conservative,Income",
            "JNJ,Johnson & Johnson,Equity,Healthcare,100,15000,12000,Taxable,Conservative,Income",
            "BND,Vanguard Bond,Fixed Income,Bond,100,15000,14500,Taxable,Conservative,Income",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,15000,14500,Taxable,Conservative,Income",
        ]
    )
    flags = [f for f in run_rules(load_portfolio(csv)) if f.rule_id == "risk_tolerance_mismatch"]
    assert len(flags) == 1
    assert flags[0].evidence["equity_weight_pct"] == 70.0
    assert flags[0].severity == "high"


def test_moderate_high_equity_does_not_trigger():
    csv = make_csv(
        [
            "VTI,Vanguard Total Stock,Equity,Diversified,100,19000,15000,Taxable,Moderate,Growth",
            "SCHD,Schwab Dividend,Equity,Diversified,100,18000,15000,Taxable,Moderate,Growth",
            "VXUS,Vanguard Intl,Equity,Diversified International,100,18000,15000,Taxable,Moderate,Growth",
            "JNJ,Johnson & Johnson,Equity,Healthcare,100,15000,12000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,15000,14500,Taxable,Moderate,Growth",
            "VCIT,Vanguard Corp Bond,Fixed Income,Corporate Bond,100,15000,14500,Taxable,Moderate,Growth",
        ]
    )
    assert "risk_tolerance_mismatch" not in _rule_ids(csv)


def test_conservative_low_equity_does_not_trigger():
    csv = make_csv(
        [
            "VTI,Vanguard Total Stock,Equity,Diversified,100,40000,35000,Taxable,Conservative,Income",
            "BND,Vanguard Bond,Fixed Income,Bond,100,60000,59000,Taxable,Conservative,Income",
        ]
    )
    assert "risk_tolerance_mismatch" not in _rule_ids(csv)


# --- Rules 5 & 6: taxable loss note; retirement accounts excluded ---

def test_taxable_unrealized_loss_triggers():
    csv = make_csv(
        [
            "XOM,Exxon Mobil,Equity,Energy,100,10000,12000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,90000,89000,Taxable,Moderate,Growth",
        ]
    )
    flags = [f for f in run_rules(load_portfolio(csv)) if f.rule_id == "tax_review_taxable_loss"]
    assert len(flags) == 1
    assert flags[0].evidence["ticker"] == "XOM"
    assert flags[0].evidence["unrealized_gain_loss"] == -2000.0
    assert flags[0].evidence["is_retirement_account"] is False
    # Wording policy: consideration-style language, never loss-harvesting phrasing.
    assert flags[0].title == "Tax-related review consideration: XOM"
    assert "Tax review note" not in flags[0].title
    assert "tax-related review consideration" in flags[0].message
    assert "tax-loss" not in flags[0].message.lower()
    assert "harvest" not in flags[0].message.lower()
    assert "not tax, legal, or investment advice" in flags[0].message


def test_retirement_loss_never_triggers_tax_language():
    csv = make_csv(
        [
            "XOM,Exxon Mobil,Equity,Energy,100,10000,12000,Traditional IRA,Moderate,Growth",
            "AGG,iShares Bond,Fixed Income,Bond,100,40000,42000,Roth IRA,Moderate,Growth",
            "VTI,Vanguard Total Stock,Equity,Diversified,100,50000,45000,401k,Moderate,Growth",
        ]
    )
    flags = run_rules(load_portfolio(csv))
    assert all(f.rule_id != "tax_review_taxable_loss" for f in flags)
    for flag in flags:
        assert "tax-loss" not in flag.message.lower()
        assert "tax loss" not in flag.message.lower()


def test_taxable_gain_does_not_trigger_tax_note():
    csv = make_csv(
        [
            "VTI,Vanguard Total Stock,Equity,Diversified,100,15000,10000,Taxable,Moderate,Growth",
            "BND,Vanguard Bond,Fixed Income,Bond,100,85000,84000,Taxable,Moderate,Growth",
        ]
    )
    assert "tax_review_taxable_loss" not in _rule_ids(csv)


# --- Sample files: expected flag sets, end to end ---

def test_growth_concentrated_sample(samples_dir):
    portfolio = load_portfolio((samples_dir / "growth_concentrated.csv").read_bytes())
    ids = {f.rule_id for f in run_rules(portfolio)}
    assert ids == {"concentration_single_holding", "concentration_sector", "tax_review_taxable_loss"}


def test_conservative_mismatch_sample(samples_dir):
    portfolio = load_portfolio((samples_dir / "conservative_mismatch.csv").read_bytes())
    flags = run_rules(portfolio)
    ids = {f.rule_id for f in flags}
    assert ids == {"risk_tolerance_mismatch", "tax_review_taxable_loss"}
    tax_flags = [f for f in flags if f.rule_id == "tax_review_taxable_loss"]
    assert [f.evidence["ticker"] for f in tax_flags] == ["XOM"]  # IRA losses excluded


def test_retiree_cash_drag_sample(samples_dir):
    portfolio = load_portfolio((samples_dir / "retiree_cash_drag.csv").read_bytes())
    ids = {f.rule_id for f in run_rules(portfolio)}
    assert ids == {"cash_drag"}


def test_flags_are_deterministic(samples_dir):
    path = samples_dir / "growth_concentrated.csv"
    first = [f.to_dict() for f in run_rules(load_portfolio(path.read_bytes()))]
    second = [f.to_dict() for f in run_rules(load_portfolio(path.read_bytes()))]
    assert first == second


def test_every_flag_has_traceable_evidence(samples_dir):
    for path in samples_dir.glob("*.csv"):
        for flag in run_rules(load_portfolio(path.read_bytes())):
            assert flag.rule_id
            assert flag.threshold
            assert flag.evidence, f"{flag.rule_id} has no evidence"
            assert flag.severity in {"high", "medium", "info"}
