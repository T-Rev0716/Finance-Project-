"""End-to-end analysis pipeline: ingest -> summarize -> rules -> persist."""

from pathlib import Path

from . import ENGINE_VERSION, analytics, db, rules
from .ingestion import load_portfolio

DISCLAIMER = (
    "Prepared for advisor review using synthetic data and deterministic rules only. "
    "Every finding traces to the uploaded file. This is an advisor-support tool and "
    "does not provide investment, tax, or legal advice."
)


def analyze_csv(csv_bytes: bytes, source_name: str, db_path: Path | str) -> dict:
    """Run the full pipeline on raw CSV bytes and persist the result."""
    portfolio = load_portfolio(csv_bytes, source_name=source_name)
    summary = analytics.build_summary(portfolio)
    flags = [f.to_dict() for f in rules.run_rules(portfolio)]

    sha = db.file_sha256(csv_bytes)
    analysis_id = db.save_analysis(
        db_path,
        source_name=source_name,
        file_sha256_hex=sha,
        risk_tolerance=portfolio.risk_tolerance,
        client_goal=portfolio.client_goal,
        summary=summary,
        flags=flags,
        warnings=portfolio.warnings,
    )

    return {
        "analysis_id": analysis_id,
        "engine_version": ENGINE_VERSION,
        "source_name": source_name,
        "file_sha256": sha,
        "client_profile": {
            "risk_tolerance": portfolio.risk_tolerance,
            "client_goal": portfolio.client_goal,
        },
        "summary": summary,
        "flags": flags,
        "warnings": portfolio.warnings,
        "disclaimer": DISCLAIMER,
    }
