"""FastAPI application: local REST API, plus the built dashboard when present."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

    if static_dir is None:
        static_dir = Path(os.environ.get("SURVIVAL_STATIC_DIR", "frontend/dist"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


app = create_app()
