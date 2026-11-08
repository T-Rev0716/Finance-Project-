import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

REPO_ROOT = BACKEND_DIR.parent
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

# Explicit test-only credentials, set before the app is imported. Never used outside tests.
TEST_BACKEND_SECRET = "test-backend-secret-0123456789abcdefghijklmnop"
TEST_PASSWORD = "test-demo-password"
TEST_SESSION_ID = "test-session-0123456789abcdef"

from app import security  # noqa: E402

os.environ["ADVISORLENS_ENV"] = "test"
os.environ["ADVISORLENS_BACKEND_SECRET"] = TEST_BACKEND_SECRET
os.environ.pop("ADVISORLENS_BACKEND_SECRET_PREVIOUS", None)
os.environ["ADVISORLENS_DEMO_PASSWORD_HASH"] = security.hash_password(TEST_PASSWORD, n=2**12)

AUTH_HEADERS = {
    security.SECRET_HEADER: TEST_BACKEND_SECRET,
    security.SESSION_HEADER: TEST_SESSION_ID,
}


def api_client():
    """A client that calls the API the way the Next.js server does."""
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app, headers=AUTH_HEADERS)

HEADER = (
    "ticker,security_name,asset_class,sector,shares,market_value,"
    "cost_basis,account_type,risk_tolerance,client_goal"
)


def make_csv(rows: list[str]) -> str:
    """Build a portfolio CSV from raw holding rows (header added automatically)."""
    return "\n".join([HEADER, *rows]) + "\n"


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest.fixture
def simple_csv() -> str:
    """A small balanced portfolio (total 100,000) that triggers no flags."""
    return make_csv(
        [
            "VTI,Vanguard Total Stock Market ETF,Equity,Diversified,60,18000.00,15000.00,Taxable,Moderate,Growth",
            "VXUS,Vanguard Total Intl Stock ETF,Equity,Diversified International,300,18000.00,17000.00,Taxable,Moderate,Growth",
            "SCHD,Schwab US Dividend Equity ETF,Equity,Dividend Equity,650,18000.00,14000.00,Roth IRA,Moderate,Growth",
            "BND,Vanguard Total Bond Market ETF,Fixed Income,Bond,275,20000.00,21000.00,Traditional IRA,Moderate,Growth",
            "VCIT,Vanguard Interm-Term Corp Bond ETF,Fixed Income,Corporate Bond,220,18000.00,18000.00,Traditional IRA,Moderate,Growth",
            "SPAXX,Fidelity Government Money Market Fund,Cash,Cash,8000,8000.00,8000.00,Taxable,Moderate,Growth",
        ]
    )
