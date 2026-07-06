import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import compliance, db, llm, main
from app.brief import FALLBACK_GENERATOR, generate_brief, resolve_generator
from app.llm_brief import build_input_packet, find_fact_errors, validate_llm_payload
from app.service import analyze_csv
from tests.conftest import SAMPLES_DIR


def _analysis_for(tmp_path, csv_bytes: bytes, name: str) -> dict:
    db_path = tmp_path / "llm-test.db"
    result = analyze_csv(csv_bytes, source_name=name, db_path=db_path)
    return db.get_analysis(db_path, result["analysis_id"])


@pytest.fixture
def analysis(tmp_path):
    csv_bytes = (SAMPLES_DIR / "conservative_mismatch.csv").read_bytes()
    return _analysis_for(tmp_path, csv_bytes, "conservative_mismatch.csv")


class StubProvider:
    """Returns a canned response, or raises it if given an exception."""

    name = "stub"

    def __init__(self, response):
        self.response = response

    def complete_json(self, system: str, user: str) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        if callable(self.response):
            return self.response(user)
        return self.response


def _stub(monkeypatch, response):
    monkeypatch.setattr(llm, "get_provider", lambda config: StubProvider(response))


def _valid_payload(packet: dict) -> dict:
    return {
        "executive_summary": [
            f"Advisor-support review of {packet['source_name']} "
            f"covering {packet['summary']['holdings_count']} holdings."
        ],
        "key_review_items": [
            {"rule_id": f["rule_id"], "narrative": f["message"]} for f in packet["flags"]
        ],
        "advisor_talking_points": ["Consider reviewing the flagged items with the client."],
        "client_discussion_questions": ["Have your goals changed since our last review?"],
        "follow_up_items": ["Document the discussion in the client file."],
    }


# --- 1-2: generator resolution (deterministic stays the default) ---


def test_no_env_resolves_deterministic(monkeypatch, analysis):
    monkeypatch.delenv("ADVISORLENS_BRIEF_GENERATOR", raising=False)
    monkeypatch.delenv("ADVISORLENS_LLM_PROVIDER", raising=False)
    assert resolve_generator() == "deterministic-v1"
    brief = generate_brief(analysis)
    assert brief["generator"] == "deterministic-v1"
    assert brief["generator_metadata"]["validation_status"] == "not_attempted"


def test_llm_config_alone_does_not_switch_default(monkeypatch):
    """Configured credentials must NOT flip the default — llm-v1 is opt-in only."""
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    monkeypatch.delenv("ADVISORLENS_BRIEF_GENERATOR", raising=False)
    assert resolve_generator() == "deterministic-v1"


def test_env_override_selects_llm(monkeypatch):
    monkeypatch.setenv("ADVISORLENS_BRIEF_GENERATOR", "llm-v1")
    assert resolve_generator() == "llm-v1"
    assert resolve_generator("deterministic-v1") == "deterministic-v1"  # explicit beats env


def test_llm_requested_but_unconfigured_falls_back(monkeypatch, analysis):
    monkeypatch.delenv("ADVISORLENS_LLM_PROVIDER", raising=False)
    brief = generate_brief(analysis, generator="llm-v1")
    assert brief["generator"] == FALLBACK_GENERATOR
    assert "configured" in brief["generator_metadata"]["fallback_reason"]


# --- 3: successful LLM path (mock provider, no keys) ---


def test_mock_provider_success(monkeypatch, analysis):
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    deterministic = generate_brief(analysis, generator="deterministic-v1")
    brief = generate_brief(analysis, generator="llm-v1")

    assert brief["generator"] == "llm-v1"
    metadata = brief["generator_metadata"]
    assert metadata["provider"] == "mock"
    assert metadata["model"] == "mock-echo-1"
    assert metadata["prompt_version"] == "brief-prompt-v1"
    assert metadata["validation_status"] == "passed"
    assert metadata["fallback_reason"] is None

    sections = brief["sections"]
    assert "mock language provider" in sections["executive_summary"][0]
    # Data-bearing sections are verbatim deterministic; review items keep
    # rule_id/severity/title.
    assert sections["evidence_table"] == deterministic["sections"]["evidence_table"]
    assert sections["portfolio_snapshot"] == deterministic["sections"]["portfolio_snapshot"]
    assert sections["data_assumptions"] == deterministic["sections"]["data_assumptions"]
    assert sections["compliance_disclaimer"] == deterministic["sections"]["compliance_disclaimer"]
    assert [i["rule_id"] for i in sections["key_review_items"]] == [
        f["rule_id"] for f in analysis["flags"]
    ]
    assert [i["severity"] for i in sections["key_review_items"]] == [
        f["severity"] for f in analysis["flags"]
    ]


# --- 4-9: failure modes all fall back safely ---


def _expect_fallback(monkeypatch, analysis, response, reason_fragment: str):
    _stub(monkeypatch, response)
    brief = generate_brief(analysis, generator="llm-v1")
    assert brief["generator"] == FALLBACK_GENERATOR
    metadata = brief["generator_metadata"]
    assert metadata["requested_generator"] == "llm-v1"
    assert metadata["validation_status"] == "failed"
    assert reason_fragment in metadata["fallback_reason"]
    # The fallback brief is a full, compliant deterministic brief.
    assert list(brief["sections"].keys())[0] == "executive_summary"
    return brief


def test_invalid_json_falls_back(monkeypatch, analysis):
    _expect_fallback(monkeypatch, analysis, "this is not json {", "invalid JSON")


def test_banned_phrase_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["advisor_talking_points"] = [
            "This may indicate an opportunity for tax-loss harvesting."
        ]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "banned phrase")


def test_invented_review_item_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["key_review_items"].append(
            {"rule_id": "momentum_risk_alert", "narrative": "A new risk was identified."}
        )
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "map exactly")


def test_dropped_rule_id_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["key_review_items"] = payload["key_review_items"][:-1]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "map exactly")


def test_tampered_evidence_falls_back(monkeypatch, analysis):
    """A response trying to emit its own evidence table is rejected outright."""

    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["evidence_table"] = [{"rule_id": "risk_tolerance_mismatch", "evidence": {"x": 1}}]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "unexpected keys")


def test_provider_exception_falls_back(monkeypatch, analysis):
    _expect_fallback(
        monkeypatch, analysis, llm.LLMProviderError("LLM request failed: timeout"), "timeout"
    )


# --- Fact-token guard ---


def test_hallucinated_ticker_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["advisor_talking_points"] = ["Consider reviewing the TSLA position."]
        return json.dumps(payload)

    brief = _expect_fallback(monkeypatch, analysis, respond, "TSLA")
    assert "does not appear in the analysis data" in brief["generator_metadata"]["fallback_reason"]


def test_hallucinated_dollar_amount_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["executive_summary"] = ["Total portfolio value is $999,999.99."]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "$999,999.99")


def test_hallucinated_percentage_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["executive_summary"] = ["Equity exposure is 42.5% of the portfolio."]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "42.5%")


def test_hallucinated_rule_id_in_narrative_falls_back(monkeypatch, analysis):
    def respond(user):
        payload = _valid_payload(json.loads(user))
        payload["follow_up_items"] = ["Review the momentum_risk_alert output with the client."]
        return json.dumps(payload)

    _expect_fallback(monkeypatch, analysis, respond, "momentum_risk_alert")


def test_fact_guard_accepts_packet_facts(analysis):
    packet = build_input_packet(analysis)
    texts = [
        "Equities represent 70.0% of the $250,000.00 portfolio.",
        "Exxon Mobil Corp (XOM) shows an unrealized loss of $2,500.00.",
        "See rule risk_tolerance_mismatch for the threshold applied.",
    ]
    assert find_fact_errors(texts, packet) == []


def test_word_boundaries_in_llm_banned_list():
    assert compliance.find_llm_violations("Top holdings; the account holds shares.") == []
    assert compliance.find_llm_violations("You should hold this position.") == ["hold"]
    assert compliance.find_llm_violations("Consider tax-loss harvesting now.") == [
        "tax-loss harvesting"
    ]


def test_validate_payload_reports_missing_keys(analysis):
    packet = build_input_packet(analysis)
    errors = validate_llm_payload({"executive_summary": ["x"]}, packet)
    assert any("missing keys" in e for e in errors)


# --- 10: storage + audit metadata for success and fallback ---


def test_stored_brief_and_audit_include_llm_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    db_path = tmp_path / "store.db"
    csv_bytes = (SAMPLES_DIR / "growth_concentrated.csv").read_bytes()
    result = analyze_csv(csv_bytes, source_name="growth_concentrated.csv", db_path=db_path)
    analysis = db.get_analysis(db_path, result["analysis_id"])

    llm_brief_record = generate_brief(analysis, generator="llm-v1")
    db.save_brief(db_path, analysis["id"], llm_brief_record)

    monkeypatch.delenv("ADVISORLENS_LLM_PROVIDER", raising=False)
    fallback_record = generate_brief(analysis, generator="llm-v1")
    db.save_brief(db_path, analysis["id"], fallback_record)

    stored = db.get_latest_brief(db_path, analysis["id"])
    assert stored["generator"] == FALLBACK_GENERATOR
    assert stored["generator_metadata"]["fallback_reason"]

    events = [
        e for e in db.get_analysis(db_path, analysis["id"])["audit_log"]
        if e["event"] == "brief_generated"
    ]
    assert len(events) == 2
    success, fallback = events[0]["detail"], events[1]["detail"]
    assert success["generator"] == "llm-v1"
    assert success["provider"] == "mock"
    assert success["model"] == "mock-echo-1"
    assert success["prompt_version"] == "brief-prompt-v1"
    assert success["validation_status"] == "passed"
    assert fallback["generator"] == FALLBACK_GENERATOR
    assert fallback["validation_status"] == "failed"
    assert fallback["fallback_reason"]


# --- 11-12: API + exports ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "llm-api-test.db")
    return TestClient(main.app)


def test_health_reports_generator_state(client, monkeypatch):
    monkeypatch.delenv("ADVISORLENS_LLM_PROVIDER", raising=False)
    body = client.get("/health").json()
    assert body["default_brief_generator"] == "deterministic-v1"
    assert body["llm_configured"] is False
    assert body["llm_model"] is None

    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    body = client.get("/health").json()
    assert body["default_brief_generator"] == "deterministic-v1"  # still opt-in
    assert body["llm_configured"] is True
    assert body["llm_model"] == "mock-echo-1"


def test_api_regenerate_with_llm_generator(client, monkeypatch):
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    analysis_id = client.post("/analyze/sample/conservative_mismatch.csv").json()["analysis_id"]

    # Default GET stays deterministic even with LLM configured.
    default_brief = client.get(f"/analyses/{analysis_id}/brief").json()
    assert default_brief["generator"] == "deterministic-v1"

    response = client.post(f"/analyses/{analysis_id}/brief?generator=llm-v1")
    assert response.status_code == 200
    body = response.json()
    assert body["generator"] == "llm-v1"
    assert body["generator_metadata"]["model"] == "mock-echo-1"

    assert client.post(f"/analyses/{analysis_id}/brief?generator=nope").status_code == 400


def test_exports_work_for_llm_and_fallback_briefs(client, monkeypatch):
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    analysis_id = client.post("/analyze/sample/conservative_mismatch.csv").json()["analysis_id"]
    client.post(f"/analyses/{analysis_id}/brief?generator=llm-v1")

    markdown = client.get(f"/analyses/{analysis_id}/brief/markdown")
    assert markdown.status_code == 200
    assert "| **Generator** | llm-v1 |" in markdown.text
    assert "| **Model** | mock-echo-1 (mock) |" in markdown.text
    assert "risk_tolerance_mismatch" in markdown.text
    assert "not tax, legal, or investment advice" in markdown.text

    html = client.get(f"/analyses/{analysis_id}/brief/html")
    assert html.status_code == 200
    assert "<dd>llm-v1</dd>" in html.text
    assert "<dt>Model</dt>" in html.text

    # Force a fallback brief (LLM requested, provider now unconfigured) and
    # verify the PDF export still carries rule IDs and the disclaimer.
    monkeypatch.delenv("ADVISORLENS_LLM_PROVIDER", raising=False)
    fallback = client.post(f"/analyses/{analysis_id}/brief?generator=llm-v1").json()
    assert fallback["generator"] == FALLBACK_GENERATOR

    pdf = client.get(f"/analyses/{analysis_id}/brief/pdf")
    assert pdf.status_code == 200
    text = "\n".join(
        page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages
    )
    assert FALLBACK_GENERATOR in text
    assert "risk_tolerance_mismatch" in text
    assert "not tax, legal, or investment advice" in text


# --- 13: eval fixtures — mocked LLM output stays grounded on every sample ---


@pytest.mark.parametrize(
    "sample",
    ["growth_concentrated.csv", "conservative_mismatch.csv", "retiree_cash_drag.csv", "clean"],
)
def test_eval_fixtures_grounded_and_compliant(tmp_path, monkeypatch, sample, simple_csv):
    monkeypatch.setenv("ADVISORLENS_LLM_PROVIDER", "mock")
    if sample == "clean":
        csv_bytes, name = simple_csv.encode(), "simple.csv"
    else:
        csv_bytes, name = (SAMPLES_DIR / sample).read_bytes(), sample
    analysis = _analysis_for(tmp_path, csv_bytes, name)

    brief = generate_brief(analysis, generator="llm-v1")
    assert brief["generator"] == "llm-v1"

    sections = brief["sections"]
    assert [i["rule_id"] for i in sections["key_review_items"]] == [
        f["rule_id"] for f in analysis["flags"]
    ]
    assert [row["evidence"] for row in sections["evidence_table"]] == [
        f["evidence"] for f in analysis["flags"]
    ]
    assert "not tax, legal, or investment advice" in sections["compliance_disclaimer"]

    from app.brief import _walk_strings

    for text in _walk_strings(sections):
        assert compliance.find_violations(text) == [], text
    narrative = [
        *sections["executive_summary"],
        *(i["message"] for i in sections["key_review_items"]),
        *sections["advisor_talking_points"],
        *sections["client_discussion_questions"],
        *sections["follow_up_items"],
    ]
    for text in narrative:
        assert compliance.find_llm_violations(text) == [], text
