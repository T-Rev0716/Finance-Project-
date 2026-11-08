"""SQLite persistence for analysis results and audit records.

Two tables:
- analyses: one row per completed analysis (summary + flags as JSON).
- audit_log: append-only events tied to an analysis, so every result can
  be traced back to its source file (by SHA-256) and engine version.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import ENGINE_VERSION

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "advisorlens.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source_name TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    risk_tolerance TEXT NOT NULL,
    client_goal TEXT NOT NULL,
    total_market_value REAL NOT NULL,
    flag_count INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER REFERENCES analyses(id),
    event TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finding_reviews (
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    finding_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','discussed','follow_up','resolved')),
    note TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, finding_id)
);
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    finding_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (analysis_id, finding_id, version)
);
CREATE TABLE IF NOT EXISTS households (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS household_versions (
    household_id INTEGER NOT NULL REFERENCES households(id),
    version INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (household_id, version)
);
CREATE TABLE IF NOT EXISTS analysis_households (
    analysis_id INTEGER PRIMARY KEY REFERENCES analyses(id),
    household_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    linked_at TEXT NOT NULL,
    FOREIGN KEY (household_id, version) REFERENCES household_versions(household_id, version)
);
CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    created_at TEXT NOT NULL,
    generator TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    brief_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approved_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    brief_id INTEGER NOT NULL REFERENCES briefs(id),
    household_id INTEGER,
    household_version INTEGER,
    content_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    approved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approved_report_files (
    report_id INTEGER NOT NULL REFERENCES approved_reports(id),
    format TEXT NOT NULL CHECK(format IN ('markdown', 'html', 'pdf')),
    body BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (report_id, format)
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_key TEXT NOT NULL,
    succeeded INTEGER NOT NULL CHECK(succeeded IN (0, 1)),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_by_time ON login_attempts (created_at);
CREATE TABLE IF NOT EXISTS revoked_sessions (
    session_key TEXT PRIMARY KEY,
    expires_at REAL NOT NULL,
    revoked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_epoch (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    not_before REAL NOT NULL,
    reason TEXT NOT NULL,
    set_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS approved_reports_no_update BEFORE UPDATE ON approved_reports
BEGIN SELECT RAISE(ABORT, 'Approved reports are immutable.'); END;
CREATE TRIGGER IF NOT EXISTS approved_reports_no_delete BEFORE DELETE ON approved_reports
BEGIN SELECT RAISE(ABORT, 'Approved reports are immutable.'); END;
CREATE TRIGGER IF NOT EXISTS approved_report_files_no_update BEFORE UPDATE ON approved_report_files
BEGIN SELECT RAISE(ABORT, 'Approved report files are immutable.'); END;
CREATE TRIGGER IF NOT EXISTS approved_report_files_no_delete BEFORE DELETE ON approved_report_files
BEGIN SELECT RAISE(ABORT, 'Approved report files are immutable.'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_analysis(
    db_path: Path | str,
    *,
    source_name: str,
    file_sha256_hex: str,
    risk_tolerance: str,
    client_goal: str,
    summary: dict,
    flags: list[dict],
    warnings: list[str],
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses (
                created_at, source_name, file_sha256, engine_version,
                risk_tolerance, client_goal, total_market_value, flag_count,
                summary_json, flags_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                source_name,
                file_sha256_hex,
                ENGINE_VERSION,
                risk_tolerance,
                client_goal,
                summary["total_market_value"],
                len(flags),
                json.dumps(summary),
                json.dumps(flags),
                json.dumps(warnings),
            ),
        )
        analysis_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)",
            (
                analysis_id,
                "analysis_completed",
                json.dumps(
                    {
                        "source_name": source_name,
                        "file_sha256": file_sha256_hex,
                        "engine_version": ENGINE_VERSION,
                        "flag_count": len(flags),
                        "rule_ids": sorted({f["rule_id"] for f in flags}),
                    }
                ),
                _now(),
            ),
        )
    return analysis_id


def log_event(db_path: Path | str, analysis_id: int | None, event: str, detail: dict) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)",
            (analysis_id, event, json.dumps(detail), _now()),
        )


def save_brief(db_path: Path | str, analysis_id: int, brief: dict) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO briefs (analysis_id, created_at, generator, engine_version, brief_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (analysis_id, _now(), brief["generator"], brief["engine_version"], json.dumps(brief)),
        )
        brief_id = int(cur.lastrowid)
        metadata = brief.get("generator_metadata") or {}
        conn.execute(
            "INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)",
            (
                analysis_id,
                "brief_generated",
                json.dumps(
                    {
                        "brief_id": brief_id,
                        "generator": brief["generator"],
                        # Records both LLM successes and fallbacks. Never
                        # includes prompts or secrets — prompt version only.
                        "requested_generator": metadata.get("requested_generator"),
                        "provider": metadata.get("provider"),
                        "model": metadata.get("model"),
                        "prompt_version": metadata.get("prompt_version"),
                        "validation_status": metadata.get("validation_status"),
                        "fallback_reason": metadata.get("fallback_reason"),
                    }
                ),
                _now(),
            ),
        )
    return brief_id


def get_latest_brief(db_path: Path | str, analysis_id: int) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT brief_json FROM briefs WHERE analysis_id = ? ORDER BY id DESC LIMIT 1",
            (analysis_id,),
        ).fetchone()
    return json.loads(row["brief_json"]) if row else None


def get_latest_brief_record(db_path: Path | str, analysis_id: int) -> tuple[int, dict] | None:
    """Latest brief with its row id, so a report can cite the exact brief it used."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, brief_json FROM briefs WHERE analysis_id = ? ORDER BY id DESC LIMIT 1",
            (analysis_id,),
        ).fetchone()
    return (int(row["id"]), json.loads(row["brief_json"])) if row else None


def list_analyses(db_path: Path | str, limit: int = 20) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.created_at, a.source_name, a.file_sha256, a.engine_version,
                   a.risk_tolerance, a.client_goal, a.total_market_value, a.flag_count,
                   EXISTS(SELECT 1 FROM briefs b WHERE b.analysis_id = a.id) AS has_brief
            FROM analyses a ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{**dict(r), "has_brief": bool(r["has_brief"])} for r in rows]


def get_analysis(db_path: Path | str, analysis_id: int) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row is None:
            return None
        audit = conn.execute(
            "SELECT event, detail_json, created_at FROM audit_log WHERE analysis_id = ? ORDER BY id",
            (analysis_id,),
        ).fetchall()
    result = dict(row)
    result["summary"] = json.loads(result.pop("summary_json"))
    result["flags"] = json.loads(result.pop("flags_json"))
    result["warnings"] = json.loads(result.pop("warnings_json"))
    result["audit_log"] = [
        {"event": a["event"], "detail": json.loads(a["detail_json"]), "created_at": a["created_at"]}
        for a in audit
    ]
    return result
