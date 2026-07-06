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
CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analyses(id),
    created_at TEXT NOT NULL,
    generator TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    brief_json TEXT NOT NULL
);
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
        conn.execute(
            "INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (?, ?, ?, ?)",
            (
                analysis_id,
                "brief_generated",
                json.dumps({"brief_id": brief_id, "generator": brief["generator"]}),
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


def list_analyses(db_path: Path | str, limit: int = 20) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source_name, file_sha256, engine_version,
                   risk_tolerance, client_goal, total_market_value, flag_count
            FROM analyses ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


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
