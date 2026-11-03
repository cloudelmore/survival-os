"""FastAPI application: local REST API, plus the built dashboard when present."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from survival_search import extract, query, render
from survival_search.indexer import Paths

from . import __version__, admin, assistant, content, navigation, pmtiles, removable, telemetry

Pin = Field(pattern=r"^[0-9]{4,8}$")
# An archive's tile type says what it is: photos are JPEG, terrain is WebP, streets are vectors.
MAP_KINDS = {pmtiles.JPEG: "imagery", pmtiles.WEBP: "terrain"}
TILE_TYPES = {pmtiles.JPEG: "image/jpeg", pmtiles.WEBP: "image/webp"}


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


class WaypointRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    notes: str = Field("", max_length=2000)


class GpxImportRequest(BaseModel):
    path: str = Field(max_length=4096)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


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
        # Replacing or deleting the model must not happen beneath a running server.
        if body.id in assistant.PACKAGES and body.action in ("update", "remove") and actions_enabled:
            run_action("ai-stop")
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

    navigation_db = state_dir / "personal" / "navigation.db"

    def nav():
        db = navigation.connect(navigation_db)
        try:
            yield db
        finally:
            db.close()

    def map_rows() -> dict[str, Path]:
        db = content.connect(stores)
        try:
            rows = db.execute("SELECT id, path FROM installed WHERE format='pmtiles'"
                              " ORDER BY bytes DESC").fetchall()
        finally:
            db.close()
        return {row["id"]: state_dir / row["path"] for row in rows}

    @app.get("/api/maps")
    def maps() -> dict:
        db = content.connect(stores)
        try:
            titles = {row["id"]: dict(row) for row in db.execute(
                "SELECT id, title, version FROM installed WHERE format='pmtiles'")}
        finally:
            db.close()
        found = []
        for key, path in map_rows().items():
            if not path.is_file():
                continue
            with path.open("rb") as handle:
                header = pmtiles.parse_header(handle.read(pmtiles.HEADER_BYTES))
            found.append({**titles[key], "kind": MAP_KINDS.get(header.tile_type, "base"),
                          "bbox": [value / 10_000_000 for value in header.bounds],
                          "max_zoom": header.max_zoom})
        return {"maps": found}

    tile_files: dict[str, pmtiles.TileFile] = {}

    @app.get("/api/maps/{item}/tile/{z}/{x}/{y}")
    def map_tile(item: str, z: int, x: int, y: int) -> Response:
        path = map_rows().get(item)
        if path is None or not path.is_file():
            raise HTTPException(404, "Map not found")
        reader = tile_files.get(item)
        if reader is None or reader.stamp != path.stat().st_mtime_ns:
            reader = tile_files[item] = pmtiles.TileFile(path)
        data = reader.tile(z, x, y) if 0 <= x < 1 << z and 0 <= y < 1 << z else None
        if data is None:
            raise HTTPException(404, "No tile there")
        return Response(data, media_type=TILE_TYPES.get(reader.header.tile_type,
                                                        "application/octet-stream"))

    @app.get("/api/maps/{item}/file")
    def map_file(item: str) -> FileResponse:
        db = content.connect(stores)
        try:
            row = db.execute("SELECT path FROM installed WHERE id=? AND format='pmtiles'",
                             (item,)).fetchone()
        finally:
            db.close()
        path = state_dir / row["path"] if row else None
        if path is None or not path.is_file():
            raise HTTPException(404, "Map not found")
        return FileResponse(path, media_type="application/octet-stream")

    @app.get("/api/navigation")
    def navigation_overview(db=Depends(nav)) -> dict:
        return navigation.overview(db)

    @app.post("/api/navigation/waypoints", status_code=201, dependencies=[Depends(same_origin)])
    def waypoint_add(body: WaypointRequest, db=Depends(nav)) -> dict[str, int]:
        return {"id": navigation.add_waypoint(db, body.name, body.lat, body.lon, notes=body.notes)}

    @app.delete("/api/navigation/waypoints/{item}", status_code=204,
                dependencies=[Depends(same_origin)])
    def waypoint_delete(item: int, db=Depends(nav)) -> None:
        db.execute("DELETE FROM waypoints WHERE id=?", (item,))
        db.commit()

    @app.delete("/api/navigation/routes/{item}", status_code=204,
                dependencies=[Depends(same_origin)])
    def route_delete(item: int, db=Depends(nav)) -> None:
        db.execute("DELETE FROM routes WHERE id=?", (item,))
        db.commit()

    @app.get("/api/navigation/export.gpx")
    def gpx_export(db=Depends(nav)) -> Response:
        return Response(navigation.export_gpx(db), media_type="application/gpx+xml", headers={
            "Content-Disposition": 'attachment; filename="survival-os-navigation.gpx"'})

    @app.get("/api/navigation/usb")
    def gpx_files() -> dict:
        found = sorted(usb_root.rglob("*.[gG][pP][xX]")) if usb_root.is_dir() else []
        return {"files": [path.relative_to(usb_root).as_posix() for path in found
                          if path.is_file() and not path.is_symlink()]}

    @app.post("/api/navigation/import", dependencies=[Depends(same_origin)])
    def gpx_import(body: GpxImportRequest, db=Depends(nav)) -> dict[str, int]:
        path = (usb_root / body.path).resolve()
        if not path.is_relative_to(usb_root.resolve()) or not path.is_file():
            raise HTTPException(404, "That file is no longer on the drive")
        if path.stat().st_size > navigation.MAX_GPX_BYTES:
            raise HTTPException(422, "This GPX file is too large")
        try:
            return navigation.import_gpx(db, path.read_bytes())
        except navigation.BadGpx as error:
            raise HTTPException(422, str(error))

    @app.post("/api/navigation/export-usb", status_code=202, dependencies=[Depends(same_origin)])
    def gpx_to_usb(body: PinOnly, db=Depends(nav)) -> dict[str, str]:
        require_pin(body.pin)
        outbox = state_dir / "personal" / "outbox.gpx"
        outbox.write_bytes(navigation.export_gpx(db))
        if not usb_helper("export"):
            raise HTTPException(422, "The file could not be written to the drive")
        return {"status": "accepted"}

    def stored_document(document_id: int) -> tuple[dict, Path]:
        doc = query.document(library, document_id)
        path = library.library / doc["path"] if doc else None
        if doc is None or not path.is_file():
            raise HTTPException(404, "Document not found")
        return doc, path

    model_gate = assistant.Gate()

    @app.get("/api/ai/status")
    def ai_status() -> dict:
        return assistant.status(stores)

    def switch_model(action: str, pin: str) -> None:
        require_pin(pin)
        if not actions_enabled:
            raise HTTPException(503, "System actions are disabled on this development server")
        if not run_action(action):
            raise HTTPException(500, "The system refused the action")

    @app.post("/api/ai/start", status_code=202, dependencies=[Depends(same_origin)])
    def ai_start(body: PinOnly) -> None:
        if len(assistant.installed(stores)) != len(assistant.PACKAGES):
            raise HTTPException(409, "Install the AI runtime and model first")
        switch_model("ai-start", body.pin)

    @app.post("/api/ai/stop", status_code=202, dependencies=[Depends(same_origin)])
    def ai_stop(body: PinOnly) -> None:
        switch_model("ai-stop", body.pin)

    @app.post("/api/ai/ask", dependencies=[Depends(same_origin)])
    def ai_ask(body: QuestionRequest) -> StreamingResponse:
        events = assistant.ask(library, body.question, assistant.model_ready())
        try:
            return StreamingResponse(model_gate.stream(events), media_type="application/x-ndjson")
        except assistant.Busy:
            raise HTTPException(429, "The model is answering another question")

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
