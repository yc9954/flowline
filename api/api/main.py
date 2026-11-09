"""Flowline board API. Run: `uv run uvicorn api.main:app --port 8787 --reload`."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Database
from .files import MissingFile
from .people import migrate_legacy_people
from .routers import boards, fleet, onboarding, plans, records, runs, suggestions


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        db.init()
        # First start on a deployment that predates boards-in-the-DB: data/people.json → board `northwind`.
        app.state.migration = migrate_legacy_people(db)
        app.state.db = db
        yield

    app = FastAPI(title="Flowline API", version="0.2.0", lifespan=lifespan)

    # Flat 404 bodies (not nested under "detail") so clients can switch on `state`.
    @app.exception_handler(MissingFile)
    async def _no_data(_request: Request, exc: MissingFile) -> JSONResponse:
        return JSONResponse(exc.detail(), status_code=404)

    @app.exception_handler(onboarding.BoardNotFound)
    async def _no_board(_request: Request, exc: onboarding.BoardNotFound) -> JSONResponse:
        return JSONResponse(exc.detail(), status_code=404)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(onboarding.router)
    app.include_router(records.router)
    app.include_router(boards.router)
    app.include_router(plans.router)
    app.include_router(suggestions.router)
    app.include_router(runs.router)
    app.include_router(fleet.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_board(app)
    return app


def _mount_board(app: FastAPI) -> None:
    """Serve board/dist at / with SPA fallback when it exists."""
    dist: Path = settings.board_dist
    index = dist / "index.html"
    app.state.board_dist_served = index.is_file()
    if not app.state.board_dist_served:
        @app.get("/", include_in_schema=False)
        def root() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "flowline-api",
                    "board": f"not built: {index} missing; run `pnpm build` in board/ or use the Vite dev server on :5173",
                    "docs": "/docs",
                }
            )
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, f"no API route for /{full_path}")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
