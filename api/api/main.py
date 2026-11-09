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
from .routers import boards, fleet, plans, records, runs, suggestions


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        db.init()
        app.state.db = db
        yield

    app = FastAPI(title="Flowline API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
