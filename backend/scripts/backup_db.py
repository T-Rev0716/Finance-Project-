#!/usr/bin/env python3
"""Back up or restore the AdvisorLens SQLite database.

  backup  --db /data/advisorlens.db --out /data/backups/advisorlens-YYYYmmdd.db
      Online backup (safe while the API is running), then integrity-checked.
  restore --db /data/advisorlens.db --from /data/backups/advisorlens-YYYYmmdd.db
      Stop the API first. Verifies the backup, keeps the current file as
      <db>.pre-restore-<timestamp>, then copies the backup into place.
  verify  --db FILE
      Integrity check plus row counts.
"""
import argparse
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

COUNTED_TABLES = ("analyses", "briefs", "finding_reviews", "households", "approved_reports", "audit_log")


def verify(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"Not found: {path}")
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Integrity check failed for {path}: {result}")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in COUNTED_TABLES if t in tables}


def backup(db: Path, out: Path) -> dict:
    if out.exists():
        raise SystemExit(f"Refusing to overwrite existing backup: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as source, closing(sqlite3.connect(out)) as target:
        source.backup(target)
    return verify(out)


def restore(db: Path, backup_file: Path) -> dict:
    counts = verify(backup_file)
    if db.exists():
        keep = db.with_name(f"{db.name}.pre-restore-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db, keep)
        print(f"Previous database kept at {keep}")
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    shutil.copy2(backup_file, db)
    verify(db)
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
    if args.command == "backup":
        counts = backup(args.db, args.out)
    elif args.command == "restore":
        counts = restore(args.db, args.source)
    else:
        counts = verify(args.db)
    print(f"{args.command} ok: " + ", ".join(f"{t}={n}" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
