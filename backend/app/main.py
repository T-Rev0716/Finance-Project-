"""AdvisorLens API — Phase 1.

Synthetic-data portfolio analysis only: no brokerage links, no market data
APIs, no authentication. Results and audit records are stored in SQLite.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import ENGINE_VERSION, db
from .ingestion import IngestionError
from .service import analyze_csv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES_DIR = Path(os.environ.get("ADVISORLENS_SAMPLES_DIR", REPO_ROOT / "data" / "samples"))
DB_PATH = Path(os.environ.get("ADVISORLENS_DB", db.DEFAULT_DB_PATH))

MAX_UPLOAD_BYTES = 1_000_000  # synthetic CSVs are tiny; reject anything larger

app = FastAPI(title="AdvisorLens API", version=ENGINE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine_version": ENGINE_VERSION}


@app.get("/samples")
def list_samples() -> dict:
    samples = sorted(p.name for p in SAMPLES_DIR.glob("*.csv"))
    return {"samples": samples}


@app.post("/analyze/sample/{name}")
def analyze_sample(name: str) -> dict:
    if "/" in name or "\\" in name or not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid sample name.")
    path = SAMPLES_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Sample '{name}' not found.")
    return _analyze(path.read_bytes(), source_name=name)


@app.post("/analyze/upload")
async def analyze_upload(file: UploadFile) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large for Phase 1 (limit 1 MB).")
    return _analyze(data, source_name=file.filename or "uploaded.csv")


@app.get("/analyses")
def list_analyses(limit: int = 20) -> dict:
    return {"analyses": db.list_analyses(DB_PATH, limit=min(limit, 100))}


@app.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: int) -> dict:
    result = db.get_analysis(DB_PATH, analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found.")
    return result


def _analyze(data: bytes, source_name: str) -> dict:
    try:
        return analyze_csv(data, source_name=source_name, db_path=DB_PATH)
    except IngestionError as exc:
        db.log_event(
            DB_PATH,
            None,
            "ingestion_rejected",
            {"source_name": source_name, "errors": exc.errors},
        )
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
