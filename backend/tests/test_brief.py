import pytest

from app import compliance, db
from app.brief import (
    SECTION_ORDER,
    SECTION_TITLES,
    _walk_strings,
    brief_to_html,
    brief_to_markdown,
    generate_brief,
)
from app.service import analyze_csv
from tests.conftest import SAMPLES_DIR


def _analysis_for(tmp_path, csv_bytes: bytes, name: str) -> dict:
    db_path = tmp_path / "brief-test.db"
    result = analyze_csv(csv_bytes, source_name=name, db_path=db_path)
    return db.get_analysis(db_path, result["analysis_id"])


@pytest.fixture
def mismatch_brief(tmp_path):
    csv_bytes = (SAMPLES_DIR / "conservative_mismatch.csv").read_bytes()
    return generate_brief(_analysis_for(tmp_path, csv_bytes, "conservative_mismatch.csv"))


@pytest.fixture
def retiree_brief(tmp_path):
    csv_bytes = (SAMPLES_DIR / "retiree_cash_drag.csv").read_bytes()
    return generate_brief(_analysis_for(tmp_path, csv_bytes, "retiree_cash_drag.csv"))


@pytest.fixture
def clean_brief(tmp_path, simple_csv):
    return generate_brief(_analysis_for(tmp_path, simple_csv.encode(), "simple.csv"))


def test_all_required_sections_present(mismatch_brief, clean_brief):
    may_be_empty = {"key_review_items", "evidence_table"}  # legitimately [] when no rules fire
    for brief in (mismatch_brief, clean_brief):
        assert list(brief["sections"].keys()) == SECTION_ORDER
        for key in SECTION_ORDER:
            if key not in may_be_empty:
                assert brief["sections"][key], f"section {key} is empty"


def test_brief_metadata(mismatch_brief):
    assert mismatch_brief["generator"] == "deterministic-v1"
    assert mismatch_brief["analysis_id"] == 1
    assert mismatch_brief["source_name"] == "conservative_mismatch.csv"


def test_review_items_map_to_fired_rules_only(tmp_path):
    csv_bytes = (SAMPLES_DIR / "growth_concentrated.csv").read_bytes()
    analysis = _analysis_for(tmp_path, csv_bytes, "growth_concentrated.csv")
    brief = generate_brief(analysis)

    flag_rule_ids = [f["rule_id"] for f in analysis["flags"]]
    item_rule_ids = [i["rule_id"] for i in brief["sections"]["key_review_items"]]
    evidence_rule_ids = [r["rule_id"] for r in brief["sections"]["evidence_table"]]

    # Nothing invented: brief items are exactly the stored flags, in order.
    assert item_rule_ids == flag_rule_ids
    assert evidence_rule_ids == flag_rule_ids
    for row, flag in zip(brief["sections"]["evidence_table"], analysis["flags"]):
        assert row["evidence"] == flag["evidence"]
        assert row["threshold"] == flag["threshold"]


def test_clean_portfolio_brief_has_no_invented_findings(clean_brief):
    sections = clean_brief["sections"]
    assert sections["key_review_items"] == []
    assert sections["evidence_table"] == []
    assert "No deterministic review thresholds were exceeded" in sections["executive_summary"][2]


def test_no_banned_phrases_anywhere(mismatch_brief, retiree_brief, clean_brief):
    for brief in (mismatch_brief, retiree_brief, clean_brief):
        for text in _walk_strings(brief["sections"]):
            assert compliance.find_violations(text) == [], text
        assert compliance.find_violations(brief_to_markdown(brief)) == []
        assert compliance.find_violations(brief_to_html(brief)) == []


def test_tax_wording_uses_review_consideration_style(mismatch_brief):
    texts = list(_walk_strings(mismatch_brief["sections"]))
    tax_texts = [t for t in texts if "tax-related review consideration" in t]
    assert tax_texts, "expected tax-related review consideration wording"
    for text in texts:
        assert "tax-loss" not in text.lower()
        assert "tax loss" not in text.lower()
        assert "harvest" not in text.lower()

    titles = [i["title"] for i in mismatch_brief["sections"]["key_review_items"]]
    assert any(t.startswith("Tax-related review consideration:") for t in titles)
    assert not any("Tax review note" in t for t in titles)


def test_taxable_followup_uses_softened_wording(mismatch_brief):
    follow_ups = mismatch_brief["sections"]["follow_up_items"]
    assert any(
        "Encourage review with a qualified tax professional before any tax-related "
        "decisions are considered." in f
        for f in follow_ups
    )
    for f in follow_ups:
        assert "before any changes to taxable positions" not in f


def test_retirement_losses_produce_no_tax_items(retiree_brief):
    sections = retiree_brief["sections"]
    assert all(i["rule_id"] != "tax_review_taxable_loss" for i in sections["key_review_items"])
    for text in _walk_strings(
        {k: v for k, v in sections.items() if k != "data_assumptions"}
    ):
        assert "tax-loss" not in text.lower()
        assert "tax-related review consideration" not in text


def test_disclaimer_wording(mismatch_brief):
    disclaimer = mismatch_brief["sections"]["compliance_disclaimer"]
    assert "not tax, legal, or investment advice" in disclaimer


def test_markdown_render(mismatch_brief):
    md = brief_to_markdown(mismatch_brief)
    for title in SECTION_TITLES.values():
        assert f"## {title}" in md
    assert md.startswith("# Client Portfolio Review Brief")
    assert "`risk_tolerance_mismatch`" in md
    assert "not tax, legal, or investment advice" in md


def test_markdown_report_header_block(mismatch_brief):
    md = brief_to_markdown(mismatch_brief)
    assert f"**Analysis ID** | {mismatch_brief['analysis_id']}" in md
    assert f"**Source file** | {mismatch_brief['source_name']}" in md
    assert f"**Generated** | {mismatch_brief['generated_at']}" in md
    assert f"**Engine version** | {mismatch_brief['engine_version']}" in md


def test_markdown_evidence_readable_per_item(mismatch_brief):
    md = brief_to_markdown(mismatch_brief)
    assert "risk_tolerance: Conservative" in md
    assert "equity_weight_pct: 70" in md


def test_html_render(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    assert html.startswith("<!DOCTYPE html>")
    for title in SECTION_TITLES.values():
        assert f"<h2>{title}</h2>" in html
    assert "risk_tolerance_mismatch" in html
    assert "not tax, legal, or investment advice" in html
    # Evidence values escaped and present.
    assert "Johnson &amp; Johnson" in html


def test_html_report_header_block(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    assert "<dt>Analysis ID</dt>" in html
    assert f"<dd>{mismatch_brief['analysis_id']}</dd>" in html
    assert "<dt>Source file</dt>" in html
    assert "<dt>Generated</dt>" in html
    assert "<dt>Engine version</dt>" in html


def test_html_evidence_rendered_as_list_not_flattened_row(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    assert "<div class='evidence-item'>" in html
    assert "risk_tolerance: Conservative" in html
    # Old flattened single-cell format (key=value; key=value) should be gone.
    assert "risk_tolerance=" not in html


def test_html_print_media_rules_present(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    assert "@media print" in html
    assert "page-break-inside: avoid" in html


def test_html_tables_repeat_header_across_page_breaks(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    # thead/display:table-header-group is what makes Chromium repeat a table's
    # header row on every printed page instead of splitting it off page 1.
    assert "<thead>" in html
    assert "<tbody>" in html
    assert "thead { display: table-header-group; }" in html


def test_html_severity_color_scoped_to_label_not_whole_card(mismatch_brief):
    html = brief_to_html(mismatch_brief)
    # Regression: severity color/bold must not leak onto the review-item div
    # itself (which would recolor its whole message via inheritance). The
    # label span and the card wrapper must use distinct classes.
    assert "severity-label-high" in html
    assert "class='review-item sev-high'" in html
    assert "class='review-item severity-high'" not in html
    assert ".severity-high { color:" not in html


def test_brief_is_deterministic_apart_from_timestamp(tmp_path):
    csv_bytes = (SAMPLES_DIR / "growth_concentrated.csv").read_bytes()
    analysis = _analysis_for(tmp_path, csv_bytes, "growth_concentrated.csv")
    first = generate_brief(analysis)
    second = generate_brief(analysis)
    assert first["sections"] == second["sections"]


def test_unknown_generator_rejected(tmp_path, simple_csv):
    analysis = _analysis_for(tmp_path, simple_csv.encode(), "simple.csv")
    with pytest.raises(KeyError):
        generate_brief(analysis, generator="llm-v1")
