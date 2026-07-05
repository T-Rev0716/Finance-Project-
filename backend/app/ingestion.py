"""CSV ingestion and validation for synthetic portfolio files.

A portfolio CSV must contain one row per holding with these columns:
ticker, security_name, asset_class, sector, shares, market_value,
cost_basis, account_type, risk_tolerance, client_goal.

Only synthetic sample data is supported in Phase 1 — no brokerage
connections and no real client data.
"""

from dataclasses import dataclass, field
from io import BytesIO, StringIO

import pandas as pd

REQUIRED_COLUMNS = [
    "ticker",
    "security_name",
    "asset_class",
    "sector",
    "shares",
    "market_value",
    "cost_basis",
    "account_type",
    "risk_tolerance",
    "client_goal",
]

NUMERIC_COLUMNS = ["shares", "market_value", "cost_basis"]

VALID_RISK_TOLERANCES = {"Conservative", "Moderate", "Aggressive"}

TAXABLE_ACCOUNT_TYPES = {"Taxable", "Individual", "Joint"}
RETIREMENT_ACCOUNT_TYPES = {"Traditional IRA", "Roth IRA", "401k", "403b", "Rollover IRA"}
VALID_ACCOUNT_TYPES = TAXABLE_ACCOUNT_TYPES | RETIREMENT_ACCOUNT_TYPES

# Canonical capitalization for a few values whose title-case form is wrong.
_ACCOUNT_TYPE_CANONICAL = {
    "traditional ira": "Traditional IRA",
    "roth ira": "Roth IRA",
    "rollover ira": "Rollover IRA",
    "401k": "401k",
    "401(k)": "401k",
    "403b": "403b",
    "403(b)": "403b",
}


class IngestionError(ValueError):
    """Raised when a portfolio CSV fails validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class Portfolio:
    """Validated portfolio data plus the client profile derived from it."""

    holdings: pd.DataFrame
    risk_tolerance: str
    client_goal: str
    source_name: str = "uploaded.csv"
    warnings: list[str] = field(default_factory=list)


def _normalize_account_type(value: str) -> str:
    return _ACCOUNT_TYPE_CANONICAL.get(value.strip().lower(), value.strip().title())


def load_portfolio(source, source_name: str = "uploaded.csv") -> Portfolio:
    """Parse and validate a portfolio CSV from a path, bytes, or file object."""
    if isinstance(source, bytes):
        source = BytesIO(source)
    elif isinstance(source, str) and "\n" in source:
        source = StringIO(source)

    try:
        df = pd.read_csv(source, skip_blank_lines=True)
    except Exception as exc:  # noqa: BLE001 - surface parse failures uniformly
        raise IngestionError([f"Could not parse CSV: {exc}"]) from exc

    df.columns = [str(c).strip().lower() for c in df.columns]

    errors: list[str] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise IngestionError([f"Missing required column(s): {', '.join(missing)}"])

    df = df[REQUIRED_COLUMNS].copy()
    if df.empty:
        raise IngestionError(["CSV contains no holdings rows."])

    for col in ["ticker", "security_name", "asset_class", "sector", "account_type", "risk_tolerance", "client_goal"]:
        df[col] = df[col].astype(str).str.strip()

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad_rows = df.index[df[col].isna()].tolist()
        for idx in bad_rows:
            errors.append(f"Row {idx + 2}: '{col}' is missing or not a number.")

    if not errors:
        for col in NUMERIC_COLUMNS:
            for idx in df.index[df[col] < 0].tolist():
                errors.append(f"Row {idx + 2}: '{col}' must not be negative.")

    for idx in df.index[df["ticker"].isin(["", "nan"])].tolist():
        errors.append(f"Row {idx + 2}: 'ticker' is empty.")

    df["asset_class"] = df["asset_class"].str.title()
    df["risk_tolerance"] = df["risk_tolerance"].str.title()
    df["account_type"] = df["account_type"].map(_normalize_account_type)

    for idx in df.index[~df["risk_tolerance"].isin(VALID_RISK_TOLERANCES)].tolist():
        errors.append(
            f"Row {idx + 2}: risk_tolerance '{df.at[idx, 'risk_tolerance']}' is not one of "
            f"{sorted(VALID_RISK_TOLERANCES)}."
        )
    for idx in df.index[~df["account_type"].isin(VALID_ACCOUNT_TYPES)].tolist():
        errors.append(
            f"Row {idx + 2}: account_type '{df.at[idx, 'account_type']}' is not one of "
            f"{sorted(VALID_ACCOUNT_TYPES)}."
        )

    if errors:
        raise IngestionError(errors)

    if float(df["market_value"].sum()) <= 0:
        raise IngestionError(["Total market value must be greater than zero."])

    df["unrealized_gain_loss"] = df["market_value"] - df["cost_basis"]
    df["is_retirement_account"] = df["account_type"].isin(RETIREMENT_ACCOUNT_TYPES)

    warnings: list[str] = []
    if df["risk_tolerance"].nunique() > 1:
        warnings.append(
            "Multiple risk_tolerance values found; using the first row's value for portfolio-level rules."
        )
    if df["client_goal"].nunique() > 1:
        warnings.append("Multiple client_goal values found; using the first row's value.")

    return Portfolio(
        holdings=df,
        risk_tolerance=str(df["risk_tolerance"].iloc[0]),
        client_goal=str(df["client_goal"].iloc[0]),
        source_name=source_name,
        warnings=warnings,
    )
