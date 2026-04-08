"""SurveyMAE Web Frontend.

FastAPI thin-layer serving:
  POST /api/upload          → save PDF, start evaluation in background
  GET  /api/run/{id}/status → file-existence-based step progress
  GET  /api/run/{id}/files/{path} → serve any JSON under the run directory
  GET  /api/runs            → list all completed / in-progress runs
  GET  /run/{id}            → SPA entry for a specific historical run
  GET  /                    → SPA entry (upload page)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("surveymae.web")

# ── paths ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_STATIC_DIR = _HERE / "static"


def _detect_project_root() -> Path:
    """Detect project root, handling both main repo and git worktree layouts.

    Worktree layout:  .../SurveyMAE/worktrees/frontend/src/web/app.py
    Main repo layout: .../SurveyMAE/src/web/app.py
    """
    parts = _HERE.resolve().parts
    if "worktrees" in parts:
        idx = parts.index("worktrees")
        return Path(*parts[:idx])
    return _HERE.parent.parent  # src/web → src → project root


_PROJECT_ROOT = _detect_project_root()
_UPLOADS_DIR  = _PROJECT_ROOT / "uploads"
_RUNS_DIR     = _PROJECT_ROOT / "output" / "runs"

# ── in-memory eval registry ──────────────────────────────────────────────────
# eval_id → {"status": str, "error": str|None}
_evals: dict[str, dict] = {}

# ── step detection ───────────────────────────────────────────────────────────
_STEP_FILES: list[tuple[int, str]] = [
    (1, "tools/extraction.json"),
    (2, "tools/validation.json"),
    (2, "tools/c6_alignment.json"),
    (2, "tools/analysis.json"),
    (2, "tools/graph_analysis.json"),
    (2, "tools/key_papers.json"),
    (3, "nodes/03_evidence_dispatch.json"),
    (4, "nodes/04_verifier.json"),
    (4, "nodes/04_expert.json"),
    (4, "nodes/04_reader.json"),
    (5, "nodes/05_corrector.json"),
    (6, "nodes/06_aggregator.json"),
    (7, "run_summary.json"),
]

_STEP_LABELS = {
    1: "PDF 解析",
    2: "证据收集",
    3: "证据分发",
    4: "Agent 评估",
    5: "校正投票",
    6: "评分聚合",
    7: "报告生成",
}


def _find_inner_run_dir(outer_dir: Path) -> Optional[Path]:
    """Return the single inner run directory inside the outer bundle dir."""
    candidates = [
        d for d in outer_dir.iterdir()
        if d.is_dir() and d.name not in ("logs", "reports")
    ]
    return candidates[0] if candidates else None


def _get_paper_id(inner_dir: Path) -> Optional[str]:
    """Read paper_id from index.json."""
    index_path = inner_dir / "index.json"
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        papers = data.get("papers", {})
        return next(iter(papers), None)
    except Exception:
        return None


def _check_completed(paper_dir: Path, inner_dir: Optional[Path] = None) -> list[str]:
    """Return list of relative paths for existing output files."""
    done = []
    for _, rel in _STEP_FILES:
        if (paper_dir / rel).exists():
            done.append(rel)
        elif rel == "run_summary.json" and inner_dir and (inner_dir / rel).exists():
            # Backward-compat: older runs saved run_summary.json to inner run root
            done.append(rel)
    return done


def _infer_step(completed: list[str]) -> int:
    best = 0
    for step, rel in _STEP_FILES:
        if rel in completed:
            best = max(best, step)
    return best


# ── background task ──────────────────────────────────────────────────────────

async def _run_eval(eval_id: str, pdf_path: str) -> None:
    """Run the evaluation pipeline as a background task."""
    # Reset the global ResultStore so a fresh one is created for this run
    try:
        import src.graph.builder as _builder
        _builder._result_store = None
    except Exception:
        pass

    _evals[eval_id]["status"] = "running"
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent.parent / ".env")
        from src.main import run_evaluation
        _report, _run_dir = await run_evaluation(pdf_path, output_dir="./output")
        _evals[eval_id]["status"] = "done"
    except Exception as exc:
        logger.exception("Evaluation failed for eval_id=%s", eval_id)
        _evals[eval_id]["status"] = "error"
        _evals[eval_id]["error"] = str(exc)


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="SurveyMAE Web")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/run/{eval_id:path}")
async def run_view(eval_id: str) -> FileResponse:
    """SPA entry for viewing a specific historical run."""
    return FileResponse(str(_STATIC_DIR / "index.html"))


# ── upload ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_pdf(file: UploadFile, background_tasks: BackgroundTasks) -> JSONResponse:
    """Accept a PDF, save it, start background evaluation, return eval_id."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    uid = uuid4().hex[:12]
    pdf_path = _UPLOADS_DIR / f"{uid}.pdf"
    pdf_path.write_bytes(await file.read())

    # Pre-compute outer_run_id using the same formula as src/main.py
    pdf_hash = hashlib.md5(str(pdf_path.resolve()).encode()).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    eval_id = f"{ts}_{pdf_hash}"

    _evals[eval_id] = {"status": "starting", "error": None, "filename": file.filename}
    background_tasks.add_task(_run_eval, eval_id, str(pdf_path.resolve()))

    return JSONResponse({"eval_id": eval_id, "filename": file.filename})


# ── status ────────────────────────────────────────────────────────────────────

@app.get("/api/run/{eval_id}/status")
async def get_status(eval_id: str) -> JSONResponse:
    """Return step-completion status for the given eval."""
    outer_dir = _RUNS_DIR / eval_id

    if not outer_dir.exists():
        info = _evals.get(eval_id, {})
        return JSONResponse({
            "eval_id": eval_id,
            "status": info.get("status", "not_found"),
            "current_step": 0,
            "total_steps": 7,
            "finished": False,
            "paper_id": None,
            "inner_run_id": None,
            "completed_files": [],
        })

    inner_dir = _find_inner_run_dir(outer_dir)
    if not inner_dir:
        return JSONResponse({
            "eval_id": eval_id,
            "status": "initializing",
            "current_step": 0,
            "total_steps": 7,
            "finished": False,
            "paper_id": None,
            "inner_run_id": None,
            "completed_files": [],
        })

    paper_id = _get_paper_id(inner_dir)
    if not paper_id:
        return JSONResponse({
            "eval_id": eval_id,
            "status": "running",
            "current_step": 1,
            "total_steps": 7,
            "finished": False,
            "paper_id": None,
            "inner_run_id": inner_dir.name,
            "completed_files": [],
        })

    paper_dir = inner_dir / "papers" / paper_id
    completed = _check_completed(paper_dir, inner_dir)
    step = _infer_step(completed)
    finished = "run_summary.json" in completed

    eval_status = _evals.get(eval_id, {}).get("status", "running")
    if finished:
        eval_status = "done"
    elif eval_status not in ("error",):
        eval_status = "running"

    return JSONResponse({
        "eval_id": eval_id,
        "inner_run_id": inner_dir.name,
        "paper_id": paper_id,
        "completed_files": completed,
        "current_step": step,
        "total_steps": 7,
        "finished": finished,
        "status": eval_status,
        "error": _evals.get(eval_id, {}).get("error"),
        "step_labels": _STEP_LABELS,
    })


# ── file serving ──────────────────────────────────────────────────────────────

@app.get("/api/run/{eval_id}/files/{path:path}")
async def get_file(eval_id: str, path: str) -> FileResponse:
    """Serve any JSON file under output/runs/{eval_id}/{inner_run}/{path}."""
    outer_dir = _RUNS_DIR / eval_id
    if not outer_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found.")

    inner_dir = _find_inner_run_dir(outer_dir)
    if not inner_dir:
        raise HTTPException(status_code=404, detail="Run directory not ready.")

    file_path = inner_dir / path
    # Backward-compat: run_summary.json may be at papers/{paper_id}/ or at run root
    if not file_path.exists() and path.endswith("run_summary.json"):
        alt = inner_dir / "run_summary.json"
        if alt.exists():
            file_path = alt
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    # Determine media type based on file extension
    media_type = "application/json"
    if file_path.suffix.lower() == ".pdf":
        media_type = "application/pdf"

    return FileResponse(str(file_path), media_type=media_type)


@app.get("/api/run/{eval_id}/pdf")
async def get_pdf(eval_id: str) -> FileResponse:
    """Serve the original PDF file for the given eval.

    Reads the source_path from papers/{paper_id}/source.json which contains
    the absolute path to the original PDF file.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"PDF request for eval_id: {eval_id}")

    outer_dir = _RUNS_DIR / eval_id
    logger.info(f"Looking for run dir: {outer_dir}")
    if not outer_dir.exists():
        logger.error(f"Run not found: {outer_dir}")
        raise HTTPException(status_code=404, detail=f"Run not found: {eval_id}")

    inner_dir = _find_inner_run_dir(outer_dir)
    logger.info(f"Inner dir: {inner_dir}")
    if not inner_dir:
        raise HTTPException(status_code=404, detail="Run directory not ready.")

    paper_id = _get_paper_id(inner_dir)
    logger.info(f"Paper ID: {paper_id}")
    if not paper_id:
        raise HTTPException(status_code=404, detail="Paper not found.")

    # Read source.json to get the original PDF path
    source_json_path = inner_dir / "papers" / paper_id / "source.json"
    logger.info(f"Looking for source.json: {source_json_path}")
    if source_json_path.exists():
        try:
            data = json.loads(source_json_path.read_text(encoding="utf-8"))
            source_path = data.get("source_path")
            logger.info(f"Source path from JSON: {source_path}")

            if source_path:
                pdf_path = Path(source_path)
                logger.info(f"Checking if PDF exists: {pdf_path}")
                if pdf_path.exists():
                    logger.info(f"Serving PDF: {pdf_path}")
                    return FileResponse(str(pdf_path), media_type="application/pdf")
                else:
                    logger.error(f"PDF path does not exist: {pdf_path}")
        except Exception as e:
            logger.error(f"Error reading source.json: {e}")
    else:
        logger.error(f"source.json not found: {source_json_path}")

    # Fallback: try to find PDF in the paper directory
    paper_dir = inner_dir / "papers" / paper_id
    pdf_candidates = list(paper_dir.glob("*.pdf"))
    logger.info(f"PDF candidates in paper dir: {pdf_candidates}")

    if pdf_candidates:
        return FileResponse(str(pdf_candidates[0]), media_type="application/pdf")

    raise HTTPException(status_code=404, detail="PDF not found for this run.")


# ── runs list ─────────────────────────────────────────────────────────────────

@app.get("/api/runs")
async def list_runs() -> JSONResponse:
    """List all available run bundles, newest first."""
    if not _RUNS_DIR.exists():
        return JSONResponse({"runs": []})

    runs = []
    for outer_dir in sorted(_RUNS_DIR.iterdir(), reverse=True):
        if not outer_dir.is_dir():
            continue
        inner_dir = _find_inner_run_dir(outer_dir)
        if not inner_dir:
            continue
        paper_id = _get_paper_id(inner_dir)
        entry: dict = {"eval_id": outer_dir.name, "inner_run_id": inner_dir.name}
        if paper_id:
            entry["paper_id"] = paper_id
            summary_path = inner_dir / "papers" / paper_id / "run_summary.json"
            if summary_path.exists():
                try:
                    s = json.loads(summary_path.read_text(encoding="utf-8"))
                    entry["overall_score"] = s.get("overall_score")
                    entry["grade"] = s.get("grade")
                    entry["timestamp"] = s.get("timestamp")
                    entry["source"] = Path(s.get("source", "")).name
                    entry["finished"] = True
                except Exception:
                    pass
        runs.append(entry)

    return JSONResponse({"runs": runs})


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=False)
