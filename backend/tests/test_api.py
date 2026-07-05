import pytest
from fastapi.testclient import TestClient

from app import main


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
