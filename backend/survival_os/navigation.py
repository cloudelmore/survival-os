"""Waypoints and routes, kept in the user's own database, with GPX import and export."""

import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MAX_GPX_BYTES = 8 * 1024 * 1024
MAX_POINTS = 200_000
GPX_NS = "http://www.topografix.com/GPX/1/1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS waypoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    elevation REAL,
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS route_points (
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    elevation REAL,
    PRIMARY KEY (route_id, position)
) WITHOUT ROWID;
"""


class BadGpx(Exception):
    """The file is not usable GPX. The message is shown to the user."""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def add_waypoint(db: sqlite3.Connection, name: str, lat: float, lon: float,
                 elevation: float | None = None, notes: str = "") -> int:
    cursor = db.execute(
        "INSERT INTO waypoints (name, lat, lon, elevation, notes, created_at) VALUES (?,?,?,?,?,?)",
        (name, lat, lon, elevation, notes, time.time()))
    db.commit()
    return cursor.lastrowid


def overview(db: sqlite3.Connection) -> dict:
    waypoints = [dict(row) for row in db.execute("SELECT * FROM waypoints ORDER BY id")]
    routes = []
    for row in db.execute("SELECT * FROM routes ORDER BY id").fetchall():
        points = db.execute("SELECT lat, lon FROM route_points WHERE route_id=? ORDER BY position",
                            (row["id"],)).fetchall()
        routes.append({"id": row["id"], "name": row["name"],
                       "points": [[point["lon"], point["lat"]] for point in points]})
    return {"waypoints": waypoints, "routes": routes}


def _point(element: ET.Element) -> tuple[float, float, float | None]:
    try:
        lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
        text = element.findtext("{*}ele")
        elevation = float(text) if text else None
    except (KeyError, ValueError) as error:
        raise BadGpx("A point in this file has no usable position") from error
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise BadGpx("A point in this file is outside the map")
    return lat, lon, elevation


def parse_gpx(data: bytes) -> dict:
    """Read waypoints, routes and tracks. Each track segment becomes one route."""
    if len(data) > MAX_GPX_BYTES:
        raise BadGpx("This GPX file is too large")
    # GPX has no use for these, and entity expansion can exhaust memory.
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        raise BadGpx("This file is not plain GPX")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise BadGpx("This file is not valid GPX") from error
    if root.tag.rsplit("}", 1)[-1] != "gpx":
        raise BadGpx("This file is not valid GPX")

    waypoints = [{"name": (item.findtext("{*}name") or "Waypoint").strip(),
                  "notes": (item.findtext("{*}desc") or "").strip(),
                  "point": _point(item)} for item in root.findall("{*}wpt")]
    routes = []
    for item in root.findall("{*}rte"):
        routes.append({"name": (item.findtext("{*}name") or "Route").strip(),
                       "points": [_point(point) for point in item.findall("{*}rtept")]})
    for item in root.findall("{*}trk"):
        name = (item.findtext("{*}name") or "Track").strip()
        segments = item.findall("{*}trkseg")
        for number, segment in enumerate(segments, 1):
            routes.append({"name": f"{name} {number}" if len(segments) > 1 else name,
                           "points": [_point(point) for point in segment.findall("{*}trkpt")]})
    routes = [route for route in routes if len(route["points"]) > 1]
    if sum(len(route["points"]) for route in routes) + len(waypoints) > MAX_POINTS:
        raise BadGpx("This GPX file has too many points")
    if not waypoints and not routes:
        raise BadGpx("This file has no waypoints or routes")
    return {"waypoints": waypoints, "routes": routes}


def import_gpx(db: sqlite3.Connection, data: bytes) -> dict[str, int]:
    parsed = parse_gpx(data)
    now = time.time()
    with db:
        for item in parsed["waypoints"]:
            lat, lon, elevation = item["point"]
            db.execute("INSERT INTO waypoints (name, lat, lon, elevation, notes, created_at)"
                       " VALUES (?,?,?,?,?,?)",
                       (item["name"], lat, lon, elevation, item["notes"], now))
        for route in parsed["routes"]:
            route_id = db.execute("INSERT INTO routes (name, created_at) VALUES (?,?)",
                                  (route["name"], now)).lastrowid
            db.executemany("INSERT INTO route_points VALUES (?,?,?,?,?)",
                           [(route_id, index, *point)
                            for index, point in enumerate(route["points"])])
    return {"waypoints": len(parsed["waypoints"]), "routes": len(parsed["routes"])}


def _point_xml(tag: str, lat: float, lon: float, elevation: float | None, inner: str = "") -> str:
    ele = f"<ele>{elevation!r}</ele>" if elevation is not None else ""
    return f'<{tag} lat="{lat!r}" lon="{lon!r}">{ele}{inner}</{tag}>'


def export_gpx(db: sqlite3.Connection) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<gpx version="1.1" creator="SURVIVAL OS" xmlns={quoteattr(GPX_NS)}>']
    for row in db.execute("SELECT * FROM waypoints ORDER BY id"):
        inner = f"<name>{escape(row['name'])}</name>"
        if row["notes"]:
            inner += f"<desc>{escape(row['notes'])}</desc>"
        lines.append(_point_xml("wpt", row["lat"], row["lon"], row["elevation"], inner))
    for route in db.execute("SELECT * FROM routes ORDER BY id").fetchall():
        points = db.execute("SELECT * FROM route_points WHERE route_id=? ORDER BY position",
                            (route["id"],)).fetchall()
        body = "".join(_point_xml("rtept", p["lat"], p["lon"], p["elevation"]) for p in points)
        lines.append(f"<rte><name>{escape(route['name'])}</name>{body}</rte>")
    lines.append("</gpx>")
    return "\n".join(lines).encode()
