import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import compliance, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "api-test.db")
    return TestClient(main.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_samples(client):
    response = client.get("/samples")
    assert response.status_code == 200
    assert response.json()["samples"] == [
        "conservative_mismatch.csv",
        "growth_concentrated.csv",
        "margaret_retiree_tech_heavy.csv",
        "retiree_cash_drag.csv",
    ]


def test_analyze_sample_end_to_end(client):
    response = client.post("/analyze/sample/growth_concentrated.csv")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_market_value"] == 90000.0
    assert {f["rule_id"] for f in body["flags"]} == {
        "concentration_single_holding",
        "concentration_sector",
        "tax_review_taxable_loss",
    }
    assert body["disclaimer"]

    # The analysis was persisted and is retrievable.
    listed = client.get("/analyses").json()["analyses"]
    assert len(listed) == 1
    detail = client.get(f"/analyses/{body['analysis_id']}").json()
    assert detail["source_name"] == "growth_concentrated.csv"
    assert len(detail["audit_log"]) >= 1


def test_analyze_unknown_sample_404(client):
    assert client.post("/analyze/sample/nope.csv").status_code == 404


def test_analyze_sample_rejects_path_traversal(client):
    assert client.post("/analyze/sample/..%2Fsecrets.csv").status_code in (400, 404)


def test_upload_endpoint(client, simple_csv):
    response = client.post(
        "/analyze/upload",
        files={"file": ("my_portfolio.csv", simple_csv.encode(), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_name"] == "my_portfolio.csv"
    assert body["flags"] == []


def test_upload_invalid_csv_is_422_and_audited(client):
    response = client.post(
        "/analyze/upload",
        files={"file": ("bad.csv", b"ticker,shares\nVTI,10\n", "text/csv")},
    )
    assert response.status_code == 422
    assert "Missing required column" in response.json()["detail"]["errors"][0]


def test_missing_analysis_404(client):
    assert client.get("/analyses/12345").status_code == 404


def test_brief_endpoint_generates_and_caches(client):
    analysis_id = client.post("/analyze/sample/conservative_mismatch.csv").json()["analysis_id"]

    first = client.get(f"/analyses/{analysis_id}/brief")
    assert first.status_code == 200
    body = first.json()
    assert body["analysis_id"] == analysis_id
    assert list(body["sections"].keys())[0] == "executive_summary"

    # Second GET returns the stored brief (same generated_at), POST regenerates.
    second = client.get(f"/analyses/{analysis_id}/brief").json()
    assert second["generated_at"] == body["generated_at"]
    regenerated = client.post(f"/analyses/{analysis_id}/brief").json()
    assert regenerated["sections"] == body["sections"]

    # Brief generation is recorded in the audit log.
    detail = client.get(f"/analyses/{analysis_id}").json()
    events = [e["event"] for e in detail["audit_log"]]
    assert events.count("brief_generated") >= 2


def test_brief_markdown_export(client):
    analysis_id = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    response = client.get(f"/analyses/{analysis_id}/brief/markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("# Client Portfolio Review Brief")
    assert "## Compliance Disclaimer" in response.text


def test_brief_html_export(client):
    analysis_id = client.post("/analyze/sample/retiree_cash_drag.csv").json()["analysis_id"]
    response = client.get(f"/analyses/{analysis_id}/brief/html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!DOCTYPE html>")
    assert "<h2>Evidence Table</h2>" in response.text


def _pdf_text(response) -> str:
    reader = PdfReader(io.BytesIO(response.content))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_brief_pdf_export(client):
    analysis_id = client.post("/analyze/sample/conservative_mismatch.csv").json()["analysis_id"]
    response = client.get(f"/analyses/{analysis_id}/brief/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert f"analysis-{analysis_id}.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_brief_pdf_export_auto_generates_missing_brief(client):
    """Exports must auto-generate (and persist) a brief if one doesn't exist yet."""
    analysis_id = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    before = client.get("/analyses").json()["analyses"][0]
    assert before["has_brief"] is False

    response = client.get(f"/analyses/{analysis_id}/brief/pdf")
    assert response.status_code == 200

    after = client.get("/analyses").json()["analyses"][0]
    assert after["has_brief"] is True


def test_brief_pdf_export_contains_report_metadata(client):
    analysis_id = client.post("/analyze/sample/conservative_mismatch.csv").json()["analysis_id"]
    text = _pdf_text(client.get(f"/analyses/{analysis_id}/brief/pdf"))

    assert "Client Portfolio Review Brief" in text
    assert "Analysis ID" in text
    assert str(analysis_id) in text
    assert "conservative_mismatch.csv" in text
    assert "Engine version" in text
    assert "deterministic-v1" in text
    assert "Compliance Disclaimer" in text
    assert "not tax, legal, or investment advice" in text
    assert "risk_tolerance_mismatch" in text
    assert "tax_review_taxable_loss" in text
    assert "Evidence Table" in text


def test_brief_pdf_export_no_banned_phrases(client):
    analysis_id = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    text = _pdf_text(client.get(f"/analyses/{analysis_id}/brief/pdf"))
    assert compliance.find_violations(text) == []


def test_brief_endpoints_404_for_missing_analysis(client):
    assert client.get("/analyses/999/brief").status_code == 404
    assert client.post("/analyses/999/brief").status_code == 404
    assert client.get("/analyses/999/brief/markdown").status_code == 404
    assert client.get("/analyses/999/brief/html").status_code == 404
    assert client.get("/analyses/999/brief/pdf").status_code == 404


def test_list_analyses_reflects_brief_generation(client):
    analysis_id = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]

    before = client.get("/analyses").json()["analyses"][0]
    assert before["has_brief"] is False

    client.get(f"/analyses/{analysis_id}/brief")

    after = client.get("/analyses").json()["analyses"][0]
    assert after["has_brief"] is True
