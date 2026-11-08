#!/usr/bin/env python3
"""Back up or restore the AdvisorLens SQLite database.

  backup  --db /data/advisorlens.db --out /data/backups/advisorlens-YYYYmmdd.db
      Online backup (safe while the API is running), validated before it is kept.
  restore --db /data/advisorlens.db --from /data/backups/advisorlens-YYYYmmdd.db
      Stop the API first. Validates the backup, keeps the current file as
      <db>.pre-restore-<timestamp>, then swaps the restored copy in. Every session
      issued before the restore is invalidated: the backup's sign-out list is older
      than the live one, so everyone signs in again.
  verify  --db FILE
      Integrity and schema check plus row counts.

Sources are opened read-only and must already exist, so a mistyped path fails instead
of creating an empty database. Nothing is written to a destination until the new
content has been validated as an AdvisorLens database.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db, security  # noqa: E402

# Tables every AdvisorLens database has had since the first release. Newer tables may be
# absent from older backups; the API creates them on startup.
CORE_TABLES = ("analyses", "briefs", "audit_log")
COUNTED_TABLES = ("analyses", "briefs", "finding_reviews", "households", "approved_reports", "audit_log")
SIDECARS = ("-journal", "-wal", "-shm")


class BackupError(Exception):
    pass


def _reference_schema() -> dict[str, set[str]]:
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(db._SCHEMA)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: {c[1] for c in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise BackupError(f"Database file not found: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def validate(path: Path) -> dict:
    """Integrity check plus the AdvisorLens schema; returns row counts."""
    with closing(_open_readonly(path)) as conn:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"{path} is not a readable SQLite database ({exc}).") from exc
        if integrity != "ok":
            raise BackupError(f"Integrity check failed for {path}: {integrity}")
        missing = [t for t in CORE_TABLES if t not in tables]
        if missing:
            raise BackupError(f"{path} is not an AdvisorLens database (missing tables: {', '.join(missing)}).")
        for table, expected in _reference_schema().items():
            if table in tables:
                columns = {c[1] for c in conn.execute(f'PRAGMA table_info("{table}")')}
                if expected - columns:
                    raise BackupError(f"{path}: table {table} is missing columns {sorted(expected - columns)}.")
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in COUNTED_TABLES if t in tables}


def _copy_validated(source: Path, target: Path) -> dict:
    """Online-copy `source` into a fresh `target`, removing `target` again on any failure."""
    target.unlink(missing_ok=True)
    try:
        with closing(_open_readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
        return validate(target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def backup(db_path: Path, out: Path) -> dict:
    validate(db_path)
    if out.exists():
        raise BackupError(f"Refusing to overwrite existing backup: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    counts = _copy_validated(db_path, partial)
    os.replace(partial, out)
    return counts


def restore(db_path: Path, source: Path) -> dict:
    if not db_path.parent.is_dir():
        raise BackupError(f"Directory not found: {db_path.parent}")
    if db_path.exists() and source.resolve() == db_path.resolve():
        raise BackupError("The backup and the live database are the same file.")
    counts = validate(source)
    staged = db_path.with_name(db_path.name + ".restore-staging")
    _copy_validated(source, staged)
    try:
        restored_at = time.time()
        with closing(db._connect(staged)) as conn, conn:  # Adds any tables newer than the backup.
            security.invalidate_sessions_before(conn, restored_at, f"database restored from {source.name}")
            conn.execute("INSERT INTO audit_log (analysis_id, event, detail_json, created_at) VALUES (NULL, ?, ?, ?)",
                         ("database_restored", json.dumps({"source": source.name, "sessions_invalidated_before": restored_at}),
                          db._now()))
        validate(staged)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    if db_path.exists():
        keep = db_path.with_name(f"{db_path.name}.pre-restore-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db_path, keep)
        for suffix in SIDECARS:  # A stale journal must not be applied to the restored file.
            sidecar = Path(f"{db_path}{suffix}")
            if sidecar.exists():
                os.replace(sidecar, Path(f"{keep}{suffix}"))
        print(f"Previous database kept at {keep}")
    os.replace(staged, db_path)
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--db", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("restore")
    r.add_argument("--db", type=Path, required=True)
    r.add_argument("--from", dest="source", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            counts = backup(args.db, args.out)
        elif args.command == "restore":
            counts = restore(args.db, args.source)
        else:
            counts = validate(args.db)
    except BackupError as exc:
        print(f"{args.command} failed: {exc} Nothing was changed.", file=sys.stderr)
        return 1
    print(f"{args.command} ok: " + ", ".join(f"{t}={n}" for t, n in counts.items()))
    if args.command == "restore":
        print("All sessions issued before this restore are now invalid; everyone signs in again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
