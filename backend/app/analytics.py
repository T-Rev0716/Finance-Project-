"""Deterministic portfolio summary calculations.

Every number here is computed directly from the uploaded CSV — no market
data lookups, no estimates. Percentages are of total portfolio market value.
"""

import pandas as pd

from .ingestion import Portfolio

TOP_HOLDINGS_COUNT = 5


def _round2(value: float) -> float:
    return round(float(value), 2)


def _allocation_by(df: pd.DataFrame, column: str, total_value: float) -> list[dict]:
    grouped = df.groupby(column, sort=False)["market_value"].sum().sort_values(ascending=False)
    return [
        {
            "name": str(name),
            "market_value": _round2(value),
            "weight_pct": _round2(value / total_value * 100),
        }
        for name, value in grouped.items()
    ]


def build_summary(portfolio: Portfolio) -> dict:
    """Compute total value, allocations, top holdings, and unrealized G/L."""
    df = portfolio.holdings
    total_value = float(df["market_value"].sum())
    total_cost = float(df["cost_basis"].sum())

    by_ticker = (
        df.groupby(["ticker", "security_name", "asset_class"], sort=False)[["market_value", "cost_basis"]]
        .sum()
        .reset_index()
        .sort_values("market_value", ascending=False)
    )
    top_holdings = [
        {
            "ticker": row.ticker,
            "security_name": row.security_name,
            "asset_class": row.asset_class,
            "market_value": _round2(row.market_value),
            "weight_pct": _round2(row.market_value / total_value * 100),
            "unrealized_gain_loss": _round2(row.market_value - row.cost_basis),
        }
        for row in by_ticker.head(TOP_HOLDINGS_COUNT).itertuples()
    ]

    holdings_detail = [
        {
            "ticker": row.ticker,
            "security_name": row.security_name,
            "asset_class": row.asset_class,
            "sector": row.sector,
            "account_type": row.account_type,
            "market_value": _round2(row.market_value),
            "weight_pct": _round2(row.market_value / total_value * 100),
            "cost_basis": _round2(row.cost_basis),
            "unrealized_gain_loss": _round2(row.unrealized_gain_loss),
        }
        for row in df.itertuples()
    ]

    return {
        "total_market_value": _round2(total_value),
        "total_cost_basis": _round2(total_cost),
        "total_unrealized_gain_loss": _round2(total_value - total_cost),
        "total_unrealized_gain_loss_pct": _round2((total_value - total_cost) / total_cost * 100)
        if total_cost > 0
        else None,
        "holdings_count": int(len(df)),
        "asset_allocation": _allocation_by(df, "asset_class", total_value),
        "sector_allocation": _allocation_by(df, "sector", total_value),
        "account_type_allocation": _allocation_by(df, "account_type", total_value),
        "top_holdings": top_holdings,
        "holdings": holdings_detail,
    }
