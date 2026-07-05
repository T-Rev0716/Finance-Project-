import pytest

from app import compliance
from app.ingestion import load_portfolio
from app.rules import run_rules
from app.service import DISCLAIMER


def test_banned_phrases_detected():
    assert compliance.find_violations("You should buy this stock") == ["buy"]
    assert compliance.find_violations("Sell it now, it's guaranteed and risk-free") == [
        "Sell",
        "guaranteed",
        "risk-free",
    ]
    assert compliance.find_violations("This will outperform, it's the best investment") == [
        "will outperform",
        "best investment",
    ]


def test_advisor_support_language_passes():
    compliance.assert_compliant_text(
        "Consider reviewing this position; it may indicate concentration risk."
    )


def test_word_boundaries_do_not_false_positive():
    # 'sell' inside 'counselling', 'buy' inside 'buyback' must not match.
    assert compliance.find_violations("counselling about buyback programs") == []


def test_assert_raises_on_violation():
    with pytest.raises(compliance.ComplianceError):
        compliance.assert_compliant_text("buy more of this")


def test_all_sample_flag_output_is_compliant(samples_dir):
    for path in samples_dir.glob("*.csv"):
        for flag in run_rules(load_portfolio(path.read_bytes())):
            compliance.assert_compliant_text(flag.title)
            compliance.assert_compliant_text(flag.message)
            compliance.assert_compliant_text(flag.threshold)


def test_disclaimer_is_compliant():
    compliance.assert_compliant_text(DISCLAIMER)
