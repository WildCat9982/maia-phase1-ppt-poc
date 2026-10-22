"""Maia for PowerPoint POC: FastAPI backend.

Run:  uvicorn backend.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from . import deck as deckio
from . import services
from .config import settings
from .llm import LLMError, Usage
from .schemas import Deck, NotesRequest, Outline, OutlineRequest

log = logging.getLogger("maia.ppt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

app = FastAPI(title="Maia for PowerPoint POC", version="0.1.0")


@app.middleware("http")
async def request_log(request: Request, call_next):
    """One log line per request: the POC's stand-in for Maia telemetry. No content is logged."""
    rid = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    response = await call_next(request)
    log.info("rid=%s %s %s status=%s ms=%d", rid, request.method, request.url.path,
             response.status_code, (time.perf_counter() - started) * 1000)
    response.headers["X-Request-Id"] = rid
    return response


@app.exception_handler(LLMError)
async def llm_error(_: Request, exc: LLMError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def _read_pptx(upload: UploadFile) -> bytes:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".pptx", ".potx"}:
        raise HTTPException(415, "Upload a .pptx or .potx file.")
    data = await upload.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    return data


def _pptx_response(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=PPTX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/health")
def health():
    return {"status": "ok", "provider": settings.llm_provider, "model": settings.llm_model,
            "base_url": settings.llm_base_url or "https://api.openai.com/v1",
            "mask_pii": settings.mask_pii}


@app.post("/api/ppt/extract", response_model=Deck)
async def extract(file: UploadFile = File(...)):
    data = await _read_pptx(file)
    try:
        return deckio.extract(data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read the presentation: {exc}") from exc


@app.post("/api/ppt/summarise")
async def summarise(deck: Deck):
    if not deck.slides:
        raise HTTPException(422, "The deck has no slides.")
    usage = Usage()
    summary = await services.summarise(deck, usage)
    return {"summary": summary, "usage": usage.as_dict()}


@app.post("/api/ppt/notes")
async def notes(req: NotesRequest):
    usage = Usage()
    result = await services.speaker_notes(req, usage)
    return {"notes": result.notes, "usage": usage.as_dict()}


@app.post("/api/ppt/notes/apply")
async def notes_apply(file: UploadFile = File(...), notes_json: str = Form(...)):
    """Write reviewed notes into a copy of the uploaded deck. Never edits the original."""
    data = await _read_pptx(file)
    try:
        notes = {int(k): str(v) for k, v in json.loads(notes_json).items()}
    except (ValueError, AttributeError) as exc:
        raise HTTPException(422, 'notes_json must be an object like {"1": "notes..."}') from exc
    stem = Path(file.filename or "deck").stem
    return _pptx_response(deckio.apply_notes(data, notes), f"{stem}-with-notes.pptx")


@app.post("/api/ppt/outline")
async def outline(req: OutlineRequest):
    usage = Usage()
    result = await services.outline(req, usage)
    return {"outline": result, "quality": deckio.check_outline(result), "usage": usage.as_dict()}


@app.post("/api/ppt/render")
async def render(outline_json: str = Form(...), template: UploadFile | None = File(None)):
    try:
        parsed = Outline.model_validate_json(outline_json)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid outline: {exc.errors()[:3]}") from exc
    template_bytes = None
    if template is not None and template.filename:
        template_bytes = await _read_pptx(template)
    elif settings.template_path:
        template_bytes = Path(settings.template_path).read_bytes()
    data = deckio.render(parsed, template_bytes)
    safe_name = "".join(c for c in parsed.title if c.isalnum() or c in " -_").strip()[:60] or "deck"
    return _pptx_response(data, f"{safe_name}.pptx")
