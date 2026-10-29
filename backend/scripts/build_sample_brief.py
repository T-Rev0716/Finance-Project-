#!/usr/bin/env python3
"""Regenerate the landing page's sample review brief from the real engine.

Runs data/samples/margaret_retiree_tech_heavy.csv through the same pipeline as
the API (ingest -> rules -> deterministic brief -> HTML -> PDF) and writes the
PDF plus a first-page preview image to frontend/public/samples/. Re-run after
changing rules or brief templates so the published sample stays in sync.

Usage:
  .venv/bin/python scripts/build_sample_brief.py

The preview image needs pdftoppm (poppler-utils).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402
from app.brief import brief_to_html, generate_brief  # noqa: E402
from app.pdf_export import html_to_pdf_bytes  # noqa: E402
from app.service import analyze_csv  # noqa: E402

SAMPLE = REPO_ROOT / "data" / "samples" / "margaret_retiree_tech_heavy.csv"
OUT_DIR = REPO_ROOT / "frontend" / "public" / "samples"
PDF_PATH = OUT_DIR / "margaret-review-brief.pdf"
PREVIEW_PATH = OUT_DIR / "margaret-review-brief-page1.png"


def main() -> int:
    if not shutil.which("pdftoppm"):
        print("pdftoppm not found; install poppler-utils to render the preview image.")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.db"
        result = analyze_csv(SAMPLE.read_bytes(), source_name=SAMPLE.name, db_path=db_path)
        analysis = db.get_analysis(db_path, result["analysis_id"])
        brief = generate_brief(analysis, generator="deterministic-v1")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_PATH.write_bytes(html_to_pdf_bytes(brief_to_html(brief)))
    subprocess.run(
        ["pdftoppm", "-png", "-r", "110", "-singlefile", "-f", "1", "-l", "1",
         str(PDF_PATH), str(PREVIEW_PATH.with_suffix(""))],
        check=True,
    )
    for path in (PDF_PATH, PREVIEW_PATH):
        print(f"Wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
