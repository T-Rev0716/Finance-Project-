"""AdvisorLens API — Phase 1.

Synthetic-data portfolio analysis only: no brokerage links, no market data
APIs, no authentication. Results and audit records are stored in SQLite.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import ENGINE_VERSION, db, reviews, households
from .brief import GENERATORS, brief_to_html, brief_to_markdown, generate_brief, resolve_generator
from .ingestion import IngestionError
from .llm import LLMConfig
from .pdf_export import PdfRenderError, html_to_pdf_bytes
from .service import analyze_csv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES_DIR = Path(os.environ.get("ADVISORLENS_SAMPLES_DIR", REPO_ROOT / "data" / "samples"))
DB_PATH = Path(os.environ.get("ADVISORLENS_DB", db.DEFAULT_DB_PATH))

MAX_UPLOAD_BYTES = 1_000_000  # synthetic CSVs are tiny; reject anything larger

app = FastAPI(title="AdvisorLens API", version=ENGINE_VERSION)

# Deployed frontend origins (e.g. a Vercel URL) go in ADVISORLENS_CORS_ORIGINS as a
# comma-separated list; localhost stays allowed so local dev keeps working.
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("ADVISORLENS_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", *_extra_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    llm_config = LLMConfig.from_env()
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "default_brief_generator": resolve_generator(),
        "llm_configured": llm_config.is_configured,
        "llm_model": llm_config.model if llm_config.is_configured else None,
    }


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
    data = await file.read(MAX_UPLOAD_BYTES + 1)
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


def _get_or_generate_brief(
    analysis_id: int, regenerate: bool = False, generator: str | None = None
) -> dict:
    if not regenerate:
        stored = db.get_latest_brief(DB_PATH, analysis_id)
        if stored is not None:
            return stored
    analysis = db.get_analysis(DB_PATH, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found.")
    brief = generate_brief(analysis, generator=generator)
    db.save_brief(DB_PATH, analysis_id, brief)
    return brief


@app.get("/analyses/{analysis_id}/brief")
def get_brief(analysis_id: int) -> dict:
    """Return the brief for an analysis, generating and storing it on first request."""
    return _get_or_generate_brief(analysis_id)


@app.post("/analyses/{analysis_id}/brief")
def regenerate_brief(analysis_id: int, generator: str | None = None) -> dict:
    """Force regeneration of the brief (stored as a new brief record).

    Optional `generator` query param requests a specific generator
    (e.g. llm-v1); omitted, the deterministic default applies.
    """
    if generator is not None and generator not in GENERATORS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown generator '{generator}'. Available: {sorted(GENERATORS)}.",
        )
    return _get_or_generate_brief(analysis_id, regenerate=True, generator=generator)


@app.get("/analyses/{analysis_id}/brief/markdown")
def export_brief_markdown(analysis_id: int) -> PlainTextResponse:
    brief = _get_or_generate_brief(analysis_id)
    return PlainTextResponse(
        brief_to_markdown(brief),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="review-brief-analysis-{analysis_id}.md"'
        },
    )


@app.get("/analyses/{analysis_id}/brief/html")
def export_brief_html(analysis_id: int) -> HTMLResponse:
    brief = _get_or_generate_brief(analysis_id)
    return HTMLResponse(brief_to_html(brief))


@app.get("/analyses/{analysis_id}/brief/pdf")
def export_brief_pdf(analysis_id: int) -> Response:
    brief = _get_or_generate_brief(analysis_id)
    try:
        pdf_bytes = html_to_pdf_bytes(brief_to_html(brief))
    except PdfRenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="review-brief-analysis-{analysis_id}.pdf"'
        },
    )


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


@app.get("/analyses/{analysis_id}/reviews")
def get_finding_reviews(analysis_id: int) -> dict:
    try:
        return reviews.get_reviews(DB_PATH, analysis_id)
    except reviews.ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/analyses/{analysis_id}/reviews/{finding_id}")
def save_finding_review(analysis_id: int, finding_id: str, update: reviews.ReviewUpdate) -> dict:
    try:
        return reviews.update_review(DB_PATH, analysis_id, finding_id, update)
    except reviews.ReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except reviews.ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


app.include_router(households.router(lambda: DB_PATH))
