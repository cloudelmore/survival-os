"""FastAPI application: local REST API, plus the built dashboard when present."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="SURVIVAL OS", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if static_dir is None:
        static_dir = Path(os.environ.get("SURVIVAL_STATIC_DIR", "frontend/dist"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


app = create_app()
