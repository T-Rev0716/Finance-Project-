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
  preflight --db /data/advisorlens.db
      Exits non-zero unless nothing else can be using the database: every process
      under /proc could be inspected, the API is not running, no process holds the
      database or its journal files open, and SQLite's exclusive lock is free. Run it
      in the same command as `restore` (`preflight ... && restore ...`).

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
API_MARKER = b"uvicorn"  # How backend/Dockerfile starts the API.


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


def preflight(db_path: Path, proc: Path = Path("/proc")) -> dict:
    """Refuse unless nothing else can be using `db_path` right now.

    A process that cannot be inspected is a failure, never "not in use". Only a process
    that has already exited (its /proc entry is gone) is skipped. /proc shows this PID
    namespace only, so run this where the API runs."""
    if not db_path.is_file():
        raise BackupError(f"Database file not found: {db_path}")
    live = os.path.realpath(db_path)
    watched = {live, *(live + s for s in SIDECARS)}
    try:
        pids = sorted(p for p in proc.iterdir() if p.name.isdigit())
    except OSError as exc:
        raise BackupError(f"Cannot inspect processes under {proc} ({exc}).") from exc
    if str(os.getpid()) not in {p.name for p in pids}:
        raise BackupError(f"Cannot inspect processes under {proc}: this process is not listed there.")
    problems = []
    for pid_dir in pids:
        pid = pid_dir.name
        if pid == str(os.getpid()):
            continue
        try:
            argv = (pid_dir / "cmdline").read_bytes().split(b"\0")
            fds = list((pid_dir / "fd").iterdir())
        except FileNotFoundError:
            if pid_dir.exists():
                problems.append(f"cannot inspect process {pid}: its cmdline or fd list is missing")
            continue  # Otherwise it exited while we looked.
        except OSError as exc:
            problems.append(f"cannot inspect process {pid} ({exc})")
            continue
        if any(API_MARKER in arg for arg in argv):
            problems.append(f"the API is still running (process {pid}: {b' '.join(argv).decode(errors='replace').strip()})")
        for fd in fds:
            try:
                target = os.readlink(fd).removesuffix(" (deleted)")
            except FileNotFoundError:
                continue  # Closed while we looked.
            except OSError as exc:
                problems.append(f"cannot inspect {fd} ({exc})")
                continue
            if target in watched:
                problems.append(f"process {pid} has {target} open")
    if problems:
        raise BackupError("Database may still be in use: " + "; ".join(problems) + ".")
    try:  # Fails at once if any other connection holds a lock, even one /proc cannot show.
        with closing(sqlite3.connect(f"{Path(live).as_uri()}?mode=rw", uri=True, timeout=0, isolation_level=None)) as conn:
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("ROLLBACK")
    except sqlite3.Error as exc:
        raise BackupError(f"Could not get exclusive access to {db_path} ({exc}).") from exc
    return {"processes_checked": len(pids) - 1}


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
    p = sub.add_parser("preflight")
    p.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            counts = backup(args.db, args.out)
        elif args.command == "restore":
            counts = restore(args.db, args.source)
        elif args.command == "preflight":
            counts = preflight(args.db)
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
