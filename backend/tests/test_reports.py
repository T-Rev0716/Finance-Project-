"""Approved client reports: explicit selection, exact preview, frozen exports."""
import hashlib
import io
import re
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import db, main

SAMPLE = "margaret_retiree_tech_heavy.csv"
CLIENT_TEXT = "We agreed to revisit position sizing at the next meeting."
CLIENT_TEXT_2 = "We will compare sector exposure before the next review."


def _profile(name="Fictional Margaret household", priorities="Keep retirement income steady."):
    return {
        "name": name, "as_of": "2026-11-08", "priorities": priorities,
        "risk_capacity_notes": "INTERNAL-CAPACITY-NOTE should never be exported.",
        "members": [{"id": "m", "name": "Margaret"}],
        "goals": [{"id": "g", "name": "Retirement income", "priority": "essential",
                   "target_date": "2027-01-01", "amount": "60000"}],
        "accounts": [
            {"id": "ira", "name": "Rollover IRA (manual)", "owner_ids": ["m"], "account_type": "Traditional IRA",
             "balance": "300000", "as_of": "2026-11-01", "evidence": "estimated"},
            {"id": "cash", "name": "Bank savings", "owner_ids": ["m"], "account_type": "Savings", "balance": None},
        ],
    }


def _pdf_text(body: bytes) -> str:
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(body)).pages)
    return re.sub(r"\s+", " ", text)


def _exports(client, report_id) -> dict:
    files = {fmt: client.get(f"/reports/{report_id}/{fmt}") for fmt in ("markdown", "html", "pdf")}
    assert all(r.status_code == 200 for r in files.values())
    return {fmt: r.content for fmt, r in files.items()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "reports.db"
    monkeypatch.setattr(main, "DB_PATH", path)
    client = TestClient(main.app)
    aid = client.post(f"/analyze/sample/{SAMPLE}").json()["analysis_id"]
    assert client.get(f"/analyses/{aid}/brief").status_code == 200
    items = client.get(f"/analyses/{aid}/reviews").json()["items"]
    for index, item in enumerate(items):  # Every finding carries a distinctive internal note.
        r = client.put(f"/analyses/{aid}/reviews/{item['finding_id']}", json={
            "status": "follow_up", "note": f"INTERNAL-NOTE-{index}", "expected_version": 0})
        assert r.status_code == 200
    household = client.post("/households", json=_profile()).json()
    assert client.post(f"/analyses/{aid}/household", json={
        "household_id": household["id"], "expected_version": household["version"]}).status_code == 201
    return client, path, aid, household


def _draft(client, aid, *, follow_ups=1, household=None):
    d = client.get(f"/analyses/{aid}/reports/draft").json()
    texts = [CLIENT_TEXT, CLIENT_TEXT_2]
    draft = {"brief_id": d["brief_id"], "client_summary": d["client_summary"],
             "follow_ups": [{"finding_id": r["finding_id"], "review_version": r["version"], "client_text": texts[i]}
                            for i, r in enumerate(d["reviews"][:follow_ups])]}
    if household:
        h = d["household"]
        draft["household"] = {"household_id": h["household_id"], "version": h["version"], **household}
    return draft


def _approve(client, aid, draft):
    preview = client.post(f"/analyses/{aid}/reports/preview", json=draft)
    assert preview.status_code == 200, preview.text
    approved = client.post(f"/analyses/{aid}/reports", json={
        "draft": draft, "preview_sha256": preview.json()["preview_sha256"]})
    assert approved.status_code == 201, approved.text
    return preview.json(), approved.json()


def test_draft_defaults_expose_notes_only_to_the_advisor_screen(env):
    client, _, aid, household = env
    d = client.get(f"/analyses/{aid}/reports/draft").json()
    assert d["brief_id"] is not None
    assert len(d["reviews"]) == 4 and all(r["internal_note"].startswith("INTERNAL-NOTE-") for r in d["reviews"])
    assert d["household"]["household_id"] == household["id"]
    assert "INTERNAL" not in d["client_summary"]


def test_unselected_notes_and_context_absent_from_preview_and_every_export(env):
    client, _, aid, _ = env
    draft = _draft(client, aid, follow_ups=2, household={"priorities": True, "goals": True, "accounts": True})
    preview, report = _approve(client, aid, draft)
    exports = _exports(client, report["id"])
    rendered = {"preview": preview["html"], "markdown": exports["markdown"].decode(),
                "html": exports["html"].decode(), "pdf": _pdf_text(exports["pdf"])}
    for fmt, text in rendered.items():
        for marker in ["INTERNAL-NOTE-0", "INTERNAL-NOTE-1", "INTERNAL-NOTE-2", "INTERNAL-NOTE-3", "INTERNAL-CAPACITY-NOTE"]:
            assert marker not in text, f"{marker} leaked into {fmt}"
        assert CLIENT_TEXT in text and CLIENT_TEXT_2 in text, fmt
        assert "Keep retirement income steady." in text, fmt


def test_nothing_optional_is_included_by_default(env):
    client, _, aid, _ = env
    draft = _draft(client, aid, follow_ups=0)
    _, report = _approve(client, aid, draft)
    markdown = _exports(client, report["id"])["markdown"].decode()
    assert "No follow-ups were selected for this report." in markdown
    assert "Household context" not in markdown and "Fictional Margaret household" not in markdown
    assert "INTERNAL" not in markdown
    assert report["sources"]["household"] is None and report["sources"]["reviews"] == []


def test_approval_saves_exactly_what_was_previewed(env):
    client, _, aid, _ = env
    draft = _draft(client, aid, household={"priorities": True})
    preview, report = _approve(client, aid, draft)
    assert report["content"] == preview["content"]
    assert report["sources"] == preview["sources"]
    assert report["content_sha256"] == preview["preview_sha256"]
    for fmt, body in _exports(client, report["id"]).items():
        assert hashlib.sha256(body).hexdigest() == report["files"][fmt]


def _assert_rejected(client, aid, draft, digest, path):
    before = client.get(f"/analyses/{aid}/reports").json()["reports"]
    r = client.post(f"/analyses/{aid}/reports", json={"draft": draft, "preview_sha256": digest})
    assert r.status_code == 409, r.text
    assert client.get(f"/analyses/{aid}/reports").json()["reports"] == before
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM approved_reports").fetchone()[0] == len(before)


def test_review_change_after_preview_requires_new_preview(env):
    client, path, aid, _ = env
    draft = _draft(client, aid)
    digest = client.post(f"/analyses/{aid}/reports/preview", json=draft).json()["preview_sha256"]
    fid = draft["follow_ups"][0]["finding_id"]
    assert client.put(f"/analyses/{aid}/reviews/{fid}", json={
        "status": "resolved", "note": "Changed after preview.", "expected_version": 1}).status_code == 200
    _assert_rejected(client, aid, draft, digest, path)


def test_new_brief_after_preview_requires_new_preview(env):
    client, path, aid, _ = env
    draft = _draft(client, aid)
    digest = client.post(f"/analyses/{aid}/reports/preview", json=draft).json()["preview_sha256"]
    assert client.post(f"/analyses/{aid}/brief").status_code == 200
    _assert_rejected(client, aid, draft, digest, path)


def test_draft_edited_after_preview_is_not_silently_approved(env):
    client, path, aid, _ = env
    draft = _draft(client, aid)
    digest = client.post(f"/analyses/{aid}/reports/preview", json=draft).json()["preview_sha256"]
    draft["client_summary"] += " An edit the advisor never previewed."
    _assert_rejected(client, aid, draft, digest, path)


def test_approved_report_unchanged_after_every_source_edit(env):
    client, path, aid, household = env
    draft = _draft(client, aid, follow_ups=2, household={"priorities": True, "goals": True, "accounts": True})
    _, report = _approve(client, aid, draft)
    before_record = client.get(f"/reports/{report['id']}").json()
    before_files = _exports(client, report["id"])

    for item in client.get(f"/analyses/{aid}/reviews").json()["items"]:
        assert client.put(f"/analyses/{aid}/reviews/{item['finding_id']}", json={
            "status": "resolved", "note": "Edited after approval.", "expected_version": item["version"]}).status_code == 200
    changed = _profile(name="Renamed later", priorities="Completely different priorities.")
    changed["accounts"][0]["balance"] = "1"
    assert client.put(f"/households/{household['id']}", json={
        "profile": changed, "expected_version": household["version"]}).status_code == 200
    assert client.post(f"/analyses/{aid}/brief").status_code == 200

    assert client.get(f"/reports/{report['id']}").json() == before_record
    assert _exports(client, report["id"]) == before_files
    assert "Renamed later" not in before_files["markdown"].decode()


def test_approved_records_and_files_cannot_be_modified(env):
    client, path, aid, _ = env
    _, report = _approve(client, aid, _draft(client, aid))
    with closing(sqlite3.connect(path)) as conn:
        for statement in [
            "UPDATE approved_reports SET content_json = '{}'",
            "DELETE FROM approved_reports",
            "UPDATE approved_report_files SET body = x'00'",
            "DELETE FROM approved_report_files",
        ]:
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(statement)
    assert client.get(f"/reports/{report['id']}").json()["content"] == report["content"]


def test_portfolio_and_household_inventory_are_kept_separate(env):
    client, _, aid, _ = env
    draft = _draft(client, aid, household={"accounts": True})
    _, report = _approve(client, aid, draft)
    exports = _exports(client, report["id"])
    for text in [exports["markdown"].decode(), exports["html"].decode(), _pdf_text(exports["pdf"])]:
        assert "This report analyzes only the holdings in the portfolio file margaret_retiree_tech_heavy.csv" in text
        assert "does not establish that this file includes every account the household holds" in text
        assert "Household account inventory (advisor-entered, not reconciled)" in text
        assert "Do not add them to the portfolio totals above." in text
        assert "Total value: $850,000.00" in text  # CSV total only, never CSV + manual balances.
        assert "$1,150,000" not in text
        assert "Not established" in text  # Unknown balance is not shown as zero.
    assert report["content"]["portfolio"]["total_market_value"] == 850000


def test_household_selection_must_match_attached_snapshot(env):
    client, _, aid, household = env
    draft = _draft(client, aid, household={"priorities": True})
    draft["household"]["version"] += 1
    assert client.post(f"/analyses/{aid}/reports/preview", json=draft).status_code == 409
    other = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    client.get(f"/analyses/{other}/brief")
    unattached = _draft(client, other, follow_ups=0)
    unattached["household"] = {"household_id": household["id"], "version": household["version"], "priorities": True}
    assert client.post(f"/analyses/{other}/reports/preview", json=unattached).status_code == 409


def test_follow_up_must_belong_to_analysis_and_be_current(env):
    client, _, aid, _ = env
    other = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    client.get(f"/analyses/{other}/brief")
    foreign = _draft(client, other)
    foreign["brief_id"] = _draft(client, aid)["brief_id"]
    assert client.post(f"/analyses/{aid}/reports/preview", json=foreign).status_code == 404
    stale = _draft(client, aid)
    stale["follow_ups"][0]["review_version"] = 0
    assert client.post(f"/analyses/{aid}/reports/preview", json=stale).status_code == 409


def test_direct_advice_wording_in_client_text_is_rejected(env):
    client, _, aid, _ = env
    draft = _draft(client, aid)
    draft["follow_ups"][0]["client_text"] = "You should sell half of your AAPL shares."
    r = client.post(f"/analyses/{aid}/reports/preview", json=draft)
    assert r.status_code == 422 and "sell" in r.json()["detail"]


def test_brief_history_is_preserved_and_reports_cite_their_brief(env):
    client, path, aid, _ = env
    first_brief = _draft(client, aid)["brief_id"]
    _, report = _approve(client, aid, _draft(client, aid))
    assert report["sources"]["brief_id"] == first_brief
    client.post(f"/analyses/{aid}/brief")
    with closing(sqlite3.connect(path)) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM briefs WHERE analysis_id = ? ORDER BY id", (aid,))]
    assert ids[0] == first_brief and len(ids) == 2  # Regeneration appends; nothing is overwritten.
    latest = db.get_latest_brief_record(path, aid)
    assert latest[0] == ids[1] and client.get(f"/analyses/{aid}/brief").json() == latest[1]
    assert client.get(f"/reports/{report['id']}").json()["sources"]["brief_id"] == first_brief


def test_multiple_approvals_are_kept_and_listed_per_analysis(env):
    client, _, aid, _ = env
    _, first = _approve(client, aid, _draft(client, aid, follow_ups=0))
    _, second = _approve(client, aid, _draft(client, aid, follow_ups=1))
    listed = client.get(f"/analyses/{aid}/reports").json()["reports"]
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    other = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    assert client.get(f"/analyses/{other}/reports").json()["reports"] == []


def test_missing_records_and_formats(env):
    client, _, aid, _ = env
    assert client.get("/analyses/999/reports/draft").status_code == 404
    assert client.get("/reports/999").status_code == 404
    assert client.get("/reports/999/pdf").status_code == 404
    assert client.get("/reports/1/docx").status_code == 422
    fresh = client.post("/analyze/sample/growth_concentrated.csv").json()["analysis_id"]
    d = client.get(f"/analyses/{fresh}/reports/draft").json()
    assert d["brief_id"] is None
    r = client.post(f"/analyses/{fresh}/reports/preview", json={"brief_id": 1, "client_summary": "x"})
    assert r.status_code == 409 and "Generate the review brief" in r.json()["detail"]
