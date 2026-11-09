import sqlite3

import pytest

from app import db
from app.brief import generate_brief
from app.service import analyze_csv


def test_analyze_csv_persists_and_round_trips(tmp_path, simple_csv):
    db_path = tmp_path / "test.db"
    result = analyze_csv(simple_csv.encode(), source_name="simple.csv", db_path=db_path)

    assert result["analysis_id"] == 1
    assert result["file_sha256"] == db.file_sha256(simple_csv.encode())

    stored = db.get_analysis(db_path, 1)
    assert stored is not None
    assert stored["source_name"] == "simple.csv"
    assert stored["risk_tolerance"] == "Moderate"
    assert stored["total_market_value"] == 100000.0
    assert stored["summary"] == result["summary"]
    assert stored["flags"] == result["flags"]

    # Audit trail records the completion event with rule ids and file hash.
    events = [entry["event"] for entry in stored["audit_log"]]
    assert "analysis_completed" in events
    completed = next(e for e in stored["audit_log"] if e["event"] == "analysis_completed")
    assert completed["detail"]["file_sha256"] == result["file_sha256"]
    assert completed["detail"]["engine_version"] == result["engine_version"]


def test_list_analyses_orders_newest_first(tmp_path, simple_csv):
    db_path = tmp_path / "test.db"
    analyze_csv(simple_csv.encode(), source_name="first.csv", db_path=db_path)
    analyze_csv(simple_csv.encode(), source_name="second.csv", db_path=db_path)

    rows = db.list_analyses(db_path)
    assert [r["source_name"] for r in rows] == ["second.csv", "first.csv"]
    assert rows[0]["flag_count"] == 0


def test_get_missing_analysis_returns_none(tmp_path):
    assert db.get_analysis(tmp_path / "test.db", 999) is None


def test_list_analyses_reports_brief_status(tmp_path, simple_csv):
    db_path = tmp_path / "test.db"
    first = analyze_csv(simple_csv.encode(), source_name="first.csv", db_path=db_path)
    analyze_csv(simple_csv.encode(), source_name="second.csv", db_path=db_path)

    rows = {r["source_name"]: r for r in db.list_analyses(db_path)}
    assert rows["first.csv"]["has_brief"] is False
    assert rows["second.csv"]["has_brief"] is False

    analysis = db.get_analysis(db_path, first["analysis_id"])
    db.save_brief(db_path, first["analysis_id"], generate_brief(analysis))

    rows = {r["source_name"]: r for r in db.list_analyses(db_path)}
    assert rows["first.csv"]["has_brief"] is True
    assert rows["second.csv"]["has_brief"] is False


def test_every_connection_is_closed_after_use(tmp_path, simple_csv, monkeypatch):
    # `with conn:` only commits or rolls back. An unclosed connection keeps the database
    # file open until garbage collection, so an idle API would still hold the file a
    # restore swaps out (see DEPLOY.md, Backups and restore).
    opened = []
    real_connect = db._connect

    def tracking_connect(path):
        conn = real_connect(path)
        opened.append(conn)  # Keeps it alive: only an explicit close() can pass below.
        return conn

    monkeypatch.setattr(db, "_connect", tracking_connect)
    db_path = tmp_path / "test.db"
    analysis_id = analyze_csv(simple_csv.encode(), source_name="simple.csv", db_path=db_path)["analysis_id"]
    analysis = db.get_analysis(db_path, analysis_id)
    db.save_brief(db_path, analysis_id, generate_brief(analysis))
    db.get_latest_brief(db_path, analysis_id)
    db.get_latest_brief_record(db_path, analysis_id)
    db.list_analyses(db_path)
    db.log_event(db_path, analysis_id, "test_event", {})
    assert db.get_analysis(db_path, 999) is None  # Early-return path.

    assert len(opened) >= 8
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
