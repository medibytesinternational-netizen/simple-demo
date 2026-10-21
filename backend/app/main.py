from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import background
from .api import router
from .db import SessionLocal, init_db
from .seed import ensure_seed
from .services import identity
from .services.credits import CreditsExhausted
from .services.llm import DraftGenerationError
from .services.timeline import EncounterLocked


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_seed(db)
    finally:
        db.close()
    tasks = background.start()
    try:
        yield
    finally:
        await background.stop(tasks)


app = FastAPI(title="MediBytes ARD Demo", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.middleware("http")
async def identity_middleware(request: Request, call_next):
    """Read who is acting and which patient is open from the headers the browser sends."""
    try:
        tokens = identity.set_context(request.headers.get("x-user-id"), request.headers.get("x-patient-id"))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    try:
        return await call_next(request)
    finally:
        identity.reset_context(tokens)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(EncounterLocked)
async def encounter_locked_handler(request: Request, exc: EncounterLocked):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(CreditsExhausted)
async def credits_exhausted_handler(request: Request, exc: CreditsExhausted):
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(DraftGenerationError)
async def draft_generation_handler(request: Request, exc: DraftGenerationError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"ok": True, "product": "MediBytes ARD"}


FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
