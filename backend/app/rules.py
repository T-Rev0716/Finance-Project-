"""Deterministic portfolio review rules.

Each rule returns zero or more Flags. Every flag carries:
- rule_id and the exact threshold that was applied,
- evidence: the uploaded-data values that triggered it,
so every finding traces back to the CSV and a deterministic rule.

All messages use advisor-support language (review, evaluate, consider,
may indicate) and are checked by the compliance guard before returning.
"""

from dataclasses import dataclass, field, asdict

import pandas as pd

from . import compliance
from .ingestion import Portfolio

# Thresholds (fractions of total portfolio market value).
SINGLE_HOLDING_MAX_WEIGHT = 0.20
SECTOR_MAX_WEIGHT = 0.35
CASH_DRAG_MIN_WEIGHT = 0.10
CONSERVATIVE_EQUITY_MAX_WEIGHT = 0.60

CASH_ASSET_CLASS = "Cash"
EQUITY_ASSET_CLASS = "Equity"


@dataclass
class Flag:
    rule_id: str
    severity: str  # "high" | "medium" | "info"
    title: str
    message: str
    threshold: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(fraction: float) -> float:
    return round(fraction * 100, 2)


def rule_single_holding_concentration(portfolio: Portfolio) -> list[Flag]:
    """Any single non-cash holding above 20% of total portfolio value."""
    df = portfolio.holdings
    total = float(df["market_value"].sum())
    non_cash = df[df["asset_class"] != CASH_ASSET_CLASS]
    by_ticker = non_cash.groupby("ticker", sort=False)["market_value"].sum()

    flags = []
    for ticker, value in by_ticker.items():
        name = str(non_cash.loc[non_cash["ticker"] == ticker, "security_name"].iloc[0])
        weight = float(value) / total
        if weight > SINGLE_HOLDING_MAX_WEIGHT:
            flags.append(
                Flag(
                    rule_id="concentration_single_holding",
                    severity="high",
                    title=f"Concentration review: {ticker}",
                    message=(
                        f"{name} ({ticker}) represents {_pct(weight)}% of the portfolio, above the "
                        f"{_pct(SINGLE_HOLDING_MAX_WEIGHT)}% single-holding review threshold. This may "
                        "indicate concentration risk; consider reviewing position sizing with the client."
                    ),
                    threshold=f"single holding > {_pct(SINGLE_HOLDING_MAX_WEIGHT)}% of portfolio",
                    evidence={
                        "ticker": ticker,
                        "security_name": name,
                        "market_value": round(float(value), 2),
                        "portfolio_total": round(total, 2),
                        "weight_pct": _pct(weight),
                    },
                )
            )
    return flags


def rule_sector_concentration(portfolio: Portfolio) -> list[Flag]:
    """Any non-cash sector above 35% of total portfolio value."""
    df = portfolio.holdings
    total = float(df["market_value"].sum())
    non_cash = df[df["asset_class"] != CASH_ASSET_CLASS]
    by_sector = non_cash.groupby("sector", sort=False)["market_value"].sum()

    flags = []
    for sector, value in by_sector.items():
        weight = float(value) / total
        if weight > SECTOR_MAX_WEIGHT:
            tickers = sorted(non_cash.loc[non_cash["sector"] == sector, "ticker"].unique().tolist())
            flags.append(
                Flag(
                    rule_id="concentration_sector",
                    severity="medium",
                    title=f"Sector concentration review: {sector}",
                    message=(
                        f"The {sector} sector represents {_pct(weight)}% of the portfolio, above the "
                        f"{_pct(SECTOR_MAX_WEIGHT)}% sector review threshold. This may indicate sector "
                        "concentration; consider evaluating diversification across sectors."
                    ),
                    threshold=f"sector > {_pct(SECTOR_MAX_WEIGHT)}% of portfolio",
                    evidence={
                        "sector": str(sector),
                        "market_value": round(float(value), 2),
                        "portfolio_total": round(total, 2),
                        "weight_pct": _pct(weight),
                        "tickers": tickers,
                    },
                )
            )
    return flags


def rule_cash_drag(portfolio: Portfolio) -> list[Flag]:
    """Cash above 10% of total portfolio value."""
    df = portfolio.holdings
    total = float(df["market_value"].sum())
    cash_value = float(df.loc[df["asset_class"] == CASH_ASSET_CLASS, "market_value"].sum())
    weight = cash_value / total
    if weight <= CASH_DRAG_MIN_WEIGHT:
        return []
    return [
        Flag(
            rule_id="cash_drag",
            severity="medium",
            title="Cash allocation review",
            message=(
                f"Cash represents {_pct(weight)}% of the portfolio, above the "
                f"{_pct(CASH_DRAG_MIN_WEIGHT)}% review threshold. This may indicate cash drag; "
                "consider reviewing whether the cash level aligns with the client's goals and timeline."
            ),
            threshold=f"cash > {_pct(CASH_DRAG_MIN_WEIGHT)}% of portfolio",
            evidence={
                "cash_market_value": round(cash_value, 2),
                "portfolio_total": round(total, 2),
                "weight_pct": _pct(weight),
            },
        )
    ]


def rule_risk_tolerance_mismatch(portfolio: Portfolio) -> list[Flag]:
    """Conservative risk tolerance combined with a high equity allocation."""
    if portfolio.risk_tolerance != "Conservative":
        return []
    df = portfolio.holdings
    total = float(df["market_value"].sum())
    equity_value = float(df.loc[df["asset_class"] == EQUITY_ASSET_CLASS, "market_value"].sum())
    weight = equity_value / total
    if weight <= CONSERVATIVE_EQUITY_MAX_WEIGHT:
        return []
    return [
        Flag(
            rule_id="risk_tolerance_mismatch",
            severity="high",
            title="Risk tolerance alignment review",
            message=(
                f"The client's stated risk tolerance is Conservative, but equities represent "
                f"{_pct(weight)}% of the portfolio, above the {_pct(CONSERVATIVE_EQUITY_MAX_WEIGHT)}% "
                "review threshold for conservative profiles. This may indicate a mismatch between the "
                "portfolio and the client's risk profile; consider discussing whether the allocation "
                "profile remains aligned with the client's stated risk tolerance."
            ),
            threshold=(
                f"risk_tolerance == Conservative and equity > "
                f"{_pct(CONSERVATIVE_EQUITY_MAX_WEIGHT)}% of portfolio"
            ),
            evidence={
                "risk_tolerance": portfolio.risk_tolerance,
                "equity_market_value": round(equity_value, 2),
                "portfolio_total": round(total, 2),
                "equity_weight_pct": _pct(weight),
            },
        )
    ]


def rule_taxable_unrealized_loss(portfolio: Portfolio) -> list[Flag]:
    """Unrealized losses held in taxable accounts only.

    Compliance guardrail: retirement accounts are explicitly excluded —
    realized losses inside tax-advantaged accounts are not deductible, so
    tax review language must never attach to them.
    """
    df = portfolio.holdings
    taxable_losses = df[(~df["is_retirement_account"]) & (df["unrealized_gain_loss"] < 0)]

    flags = []
    for row in taxable_losses.itertuples():
        flags.append(
            Flag(
                rule_id="tax_review_taxable_loss",
                severity="info",
                title=f"Tax-related review consideration: {row.ticker}",
                message=(
                    f"{row.security_name} ({row.ticker}) in a {row.account_type} account shows an "
                    f"unrealized loss of ${abs(row.unrealized_gain_loss):,.2f}. This may indicate a "
                    "tax-related review consideration; consider evaluating it with the client and a "
                    "qualified tax professional. This is a data observation, not tax, legal, or "
                    "investment advice."
                ),
                threshold="account is taxable and market_value < cost_basis",
                evidence={
                    "ticker": row.ticker,
                    "security_name": row.security_name,
                    "account_type": row.account_type,
                    "is_retirement_account": bool(row.is_retirement_account),
                    "market_value": round(float(row.market_value), 2),
                    "cost_basis": round(float(row.cost_basis), 2),
                    "unrealized_gain_loss": round(float(row.unrealized_gain_loss), 2),
                },
            )
        )
    return flags


ALL_RULES = [
    rule_single_holding_concentration,
    rule_sector_concentration,
    rule_cash_drag,
    rule_risk_tolerance_mismatch,
    rule_taxable_unrealized_loss,
]

_SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}


def run_rules(portfolio: Portfolio) -> list[Flag]:
    """Run every rule and enforce the compliance language guard on the output."""
    flags: list[Flag] = []
    for rule in ALL_RULES:
        flags.extend(rule(portfolio))
    flags.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), f.rule_id, f.title))
    compliance.assert_compliant_flags(flags)
    return flags
