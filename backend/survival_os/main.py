"""FastAPI application: local REST API, plus the built dashboard when present."""

import json
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

from . import __version__, admin, content, removable, telemetry

Pin = Field(pattern=r"^[0-9]{4,8}$")


class PinRequest(BaseModel):
    pin: str = Pin


class PinOnly(BaseModel):
    pin: str = Pin


class ContentRequest(BaseModel):
    action: Literal["install", "update", "remove", "validate"]
    id: str = Field(max_length=200)
    pin: str = Pin


class ImportRequest(BaseModel):
    path: str = Field(max_length=4096)
    category: str = Field(max_length=40)
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
    catalog_dir: Path | None = None,
    usb_helper: Callable[[str], bool] = removable.run_helper,
    usb_root: Path = removable.MOUNT_ROOT,
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

    def require_pin(pin: str) -> None:
        if not pins.is_set():
            raise HTTPException(409, "Set a PIN first")
        try:
            accepted = pins.verify(pin)
        except admin.PinLocked as locked:
            raise HTTPException(429, f"Too many attempts. Wait {locked.seconds} seconds.")
        if not accepted:
            raise HTTPException(403, "Wrong PIN")

    @app.post("/api/system/action", status_code=202, dependencies=[Depends(same_origin)])
    def system_action(body: ActionRequest) -> dict[str, str]:
        require_pin(body.pin)
        if not actions_enabled:
            raise HTTPException(503, "System actions are disabled on this development server")
        if not run_action(body.action):
            raise HTTPException(500, "The system refused the action")
        return {"status": "accepted", "action": body.action}

    library = Paths(state_dir)
    if catalog_dir is None:
        catalog_dir = Path(os.environ.get("SURVIVAL_CATALOG_DIR", "content-manifests"))
    stores = content.Paths(state_dir, catalog_dir)

    def start_worker(job_id: int) -> dict[str, int]:
        if not run_action("content"):
            raise HTTPException(500, "The content worker could not start")
        return {"job": job_id}

    def queue(action: str, target: str) -> dict[str, int]:
        db = content.connect(stores)
        try:
            job_id = content.enqueue(db, action, target)
        finally:
            db.close()
        return start_worker(job_id)

    @app.get("/api/content")
    def content_overview() -> dict:
        return {**content.overview(stores), "storage": content.summary(stores)}

    @app.post("/api/content/action", status_code=202, dependencies=[Depends(same_origin)])
    def content_action(body: ContentRequest) -> dict[str, int]:
        require_pin(body.pin)
        known = content.load_catalog(stores)
        if body.action in ("install", "update") and body.id not in known:
            raise HTTPException(404, "Not in the catalog")
        if body.action == "install":
            entry = known[body.id]
            try:
                content.check(stores, entry["budget_category"], entry["size_bytes"]["value"] or 0,
                              entry["size_bytes"]["value"] or 0)
            except content.Refused as refused:
                raise HTTPException(507, str(refused))
        return queue(body.action, body.id)

    @app.post("/api/content/check-updates", status_code=202, dependencies=[Depends(same_origin)])
    def content_updates(body: PinOnly) -> dict[str, int]:
        require_pin(body.pin)
        return queue("check-updates", "catalog")

    @app.post("/api/content/jobs/{job_id}/cancel", status_code=202,
              dependencies=[Depends(same_origin)])
    def content_cancel(job_id: int) -> dict[str, str]:
        db = content.connect(stores)
        try:
            db.execute("UPDATE jobs SET state=CASE state WHEN 'queued' THEN 'cancelled'"
                       " ELSE 'cancelling' END WHERE id=? AND state IN ('queued', 'running')",
                       (job_id,))
            db.commit()
        finally:
            db.close()
        return {"status": "accepted"}

    @app.get("/api/content/kiwix")
    def kiwix_books() -> dict:
        db = content.connect(stores)
        try:
            rows = db.execute("SELECT id, title, category, path FROM installed"
                              " WHERE format='zim' ORDER BY title").fetchall()
        finally:
            db.close()
        return {"books": [{"id": row["id"], "title": row["title"], "category": row["category"],
                           "name": Path(row["path"]).stem} for row in rows]}

    @app.get("/api/content/usb")
    def usb_files() -> dict:
        return {"mounted": usb_root.is_dir() and any(usb_root.iterdir()),
                "files": removable.scan(usb_root)}

    @app.post("/api/content/usb/{action}", status_code=202, dependencies=[Depends(same_origin)])
    def usb_mount(action: Literal["mount", "unmount"], body: PinOnly) -> dict[str, str]:
        require_pin(body.pin)
        if not usb_helper(action):
            raise HTTPException(422, "No removable drive could be read" if action == "mount"
                                else "The drive is busy")
        return {"status": "accepted"}

    @app.post("/api/content/import", status_code=202, dependencies=[Depends(same_origin)])
    def usb_import(body: ImportRequest) -> dict[str, int]:
        require_pin(body.pin)
        return queue("import", json.dumps({"path": body.path, "category": body.category}))

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
