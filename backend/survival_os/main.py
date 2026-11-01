"""FastAPI application: local REST API, plus the built dashboard when present."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from survival_search import extract, query, render
from survival_search.indexer import Paths

from . import __version__, admin, telemetry

Pin = Field(pattern=r"^[0-9]{4,8}$")


class PinRequest(BaseModel):
    pin: str = Pin


class ActionRequest(BaseModel):
    action: Literal["shutdown", "reboot", "maintenance"]
    pin: str = Pin


def same_origin(request: Request) -> None:
    """Stop other pages, such as archived web content in the kiosk, from driving admin actions."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in ("same-origin", "none"):
        raise HTTPException(403, "Cross-site request refused")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin request refused")


def create_app(
    static_dir: Path | None = None,
    state_dir: Path | None = None,
    collect: Callable[[], dict] = telemetry.collect,
    run_action: Callable[[str], bool] = admin.run_action,
    actions_enabled: bool | None = None,
) -> FastAPI:
    app = FastAPI(title="SURVIVAL OS", version=__version__, docs_url=None, redoc_url=None)

    if state_dir is None:
        state_dir = Path(os.environ.get("SURVIVAL_STATE_DIR", "state"))
    if actions_enabled is None:
        actions_enabled = os.environ.get("SURVIVAL_ACTIONS_ENABLED") == "1"
    pins = admin.PinStore(state_dir / "admin-pin.json")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict:
        return collect()

    @app.get("/api/admin/state")
    def admin_state() -> dict[str, bool]:
        return {"pin_set": pins.is_set(), "actions_enabled": actions_enabled}

    @app.post("/api/admin/pin", status_code=204, dependencies=[Depends(same_origin)])
    def set_pin(body: PinRequest) -> None:
        if pins.is_set():
            raise HTTPException(409, "A PIN is already set")
        pins.set_pin(body.pin)

    @app.post("/api/system/action", status_code=202, dependencies=[Depends(same_origin)])
    def system_action(body: ActionRequest) -> dict[str, str]:
        if not pins.is_set():
            raise HTTPException(409, "Set a PIN first")
        try:
            accepted = pins.verify(body.pin)
        except admin.PinLocked as locked:
            raise HTTPException(429, f"Too many attempts. Wait {locked.seconds} seconds.")
        if not accepted:
            raise HTTPException(403, "Wrong PIN")
        if not actions_enabled:
            raise HTTPException(503, "System actions are disabled on this development server")
        if not run_action(body.action):
            raise HTTPException(500, "The system refused the action")
        return {"status": "accepted", "action": body.action}

    library = Paths(state_dir)

    def stored_document(document_id: int) -> tuple[dict, Path]:
        doc = query.document(library, document_id)
        path = library.library / doc["path"] if doc else None
        if doc is None or not path.is_file():
            raise HTTPException(404, "Document not found")
        return doc, path

    @app.get("/api/library/search")
    def library_search(
        q: str = Query(max_length=500),
        format: str | None = None,
        category: str | None = None,
        limit: int = Query(20, ge=1, le=50),
        offset: int = Query(0, ge=0, le=5000),
    ) -> dict:
        return query.search(library, q, format, category, limit, offset)

    @app.get("/api/library/status")
    def library_status() -> dict:
        return query.status(library)

    @app.get("/api/library/documents")
    def library_documents(
        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
    ) -> dict:
        return {"documents": query.documents(library, limit, offset)}

    @app.post("/api/library/rescan", status_code=202, dependencies=[Depends(same_origin)])
    def library_rescan() -> dict[str, str]:
        library.rescan_flag.parent.mkdir(parents=True, exist_ok=True)
        library.rescan_flag.touch()
        return {"status": "accepted"}

    @app.get("/api/library/documents/{document_id}")
    def library_document(document_id: int) -> dict:
        return stored_document(document_id)[0]

    @app.get("/api/library/documents/{document_id}/view")
    def library_view(document_id: int, page: int = Query(1, ge=1)) -> dict:
        doc, path = stored_document(document_id)
        try:
            return render.view(path, doc, page)
        except LookupError:
            raise HTTPException(404, "No such page")
        except extract.ExtractionError as error:
            raise HTTPException(422, str(error))

    @app.get("/api/library/documents/{document_id}/asset")
    def library_asset(document_id: int, path: str = Query(max_length=1024)) -> Response:
        doc, stored = stored_document(document_id)
        if doc["format"] != "epub":
            raise HTTPException(404, "No such image")
        try:
            content, media_type = render.epub_asset(stored, path)
        except LookupError:
            raise HTTPException(404, "No such image")
        return Response(content, media_type=media_type)

    @app.get("/api/library/documents/{document_id}/file")
    def library_file(document_id: int) -> FileResponse:
        doc, path = stored_document(document_id)
        if doc["format"] != "pdf":
            raise HTTPException(404, "Only PDFs are served as files")
        # Only pdf.js fetches this. Opened directly, it must not run in the dashboard's origin.
        return FileResponse(path, media_type="application/pdf",
                            headers={"Content-Security-Policy": "sandbox"})

    if static_dir is None:
        static_dir = Path(os.environ.get("SURVIVAL_STATIC_DIR", "frontend/dist"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


app = create_app()
