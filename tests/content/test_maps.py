import gzip
import http.server
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from survival_os import acquire, content, navigation, pmtiles
from survival_os.acquire import Worker
from survival_os.content import Paths, Refused
from survival_os.main import create_app
from survival_os.pmtiles import Header

REPO = Path(__file__).resolve().parents[2]
BBOX = (-84.0, 34.0, -76.0, 36.0)


def tile_bytes(key: int) -> bytes:
    return gzip.compress(f"tile {key}".encode() * 40, mtime=0)


def world(max_zoom: int = 6, shared: int = 7) -> bytes:
    """A synthetic source: every tile to max_zoom, the first `shared` ids in one ocean run."""
    ocean = gzip.compress(b"ocean" * 40, mtime=0)
    last = (4 ** (max_zoom + 1) - 1) // 3
    entries = [(0, shared, 0, len(ocean))]
    data = bytearray(ocean)
    for key in range(shared, last):
        tile = tile_bytes(key)
        entries.append((key, 1, len(data), len(tile)))
        data += tile
    root, leaves = pmtiles._directories(entries)
    # Force leaves, so walking them is tested even for a small source.
    if not leaves:
        chunks = [entries[i:i + 50] for i in range(0, len(entries), 50)]
        index = []
        for chunk in chunks:
            raw = pmtiles.compress(pmtiles.write_directory(chunk))
            index.append((chunk[0][0], 0, len(leaves), len(raw)))
            leaves += raw
        root = pmtiles.compress(pmtiles.write_directory(index))
    metadata = pmtiles.compress(json.dumps({"name": "test"}).encode())
    root_at = pmtiles.HEADER_BYTES
    metadata_at = root_at + len(root)
    leaf_at = metadata_at + len(metadata)
    tile_at = leaf_at + len(leaves)
    header = Header(root_at, len(root), metadata_at, len(metadata), leaf_at, len(leaves), tile_at,
                    len(data), last, len(entries), len(entries), True, 2, 2, 1, 0, max_zoom,
                    (-1800000000, -850000000, 1800000000, 850000000), 0, (0, 0))
    return pmtiles.pack_header(header) + root + metadata + leaves + bytes(data)


class Memory:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def read(self, offset: int, length: int) -> bytes:
        self.calls += 1
        return self.data[offset:offset + length]


def read_tile(path: Path, key: int) -> bytes | None:
    data = path.read_bytes()
    header = pmtiles.parse_header(data)
    directory = pmtiles.read_directory(gzip.decompress(
        data[header.root_offset:header.root_offset + header.root_length]))
    while True:
        match = None
        for entry in directory:
            if entry[0] <= key:
                match = entry
        if match is None:
            return None
        if match[1] == 0:
            start = header.leaf_offset + match[2]
            directory = pmtiles.read_directory(gzip.decompress(data[start:start + match[3]]))
            continue
        if key >= match[0] + match[1]:
            return None
        start = header.tile_offset + match[2]
        return data[start:start + match[3]]


def extract(source: bytes, path: Path, bbox=BBOX, max_zoom=6) -> pmtiles.Plan:
    reader = Memory(source)
    plan = pmtiles.make_plan(reader, bbox, max_zoom)
    with path.open("wb") as output:
        output.write(bytes(pmtiles.ROOT_BYTES))
        pmtiles.download_tiles(reader, plan, output, 0)
    pmtiles.finish(plan, path, bbox, max_zoom)
    return plan


def test_tile_ids_follow_the_published_hilbert_order():
    assert pmtiles.tile_id(0, 0, 0) == 0
    assert [pmtiles.tile_id(1, x, y) for x, y in ((0, 0), (0, 1), (1, 1), (1, 0))] == [1, 2, 3, 4]
    assert pmtiles.tile_id(2, 0, 0) == 5
    assert pmtiles.tile_id(2, 3, 0) == 20
    for z in (3, 5):
        ids = {pmtiles.tile_id(z, x, y) for x in range(1 << z) for y in range(1 << z)}
        base = (4 ** z - 1) // 3
        assert ids == set(range(base, base + 4 ** z))


def test_header_and_directory_round_trip():
    source = world()
    assert pmtiles.pack_header(pmtiles.parse_header(source)) == source[:pmtiles.HEADER_BYTES]
    entries = [(0, 5, 0, 10), (5, 1, 10, 3), (9, 2, 100, 4)]
    assert pmtiles.read_directory(pmtiles.write_directory(entries)) == entries


def test_extract_keeps_region_tiles_and_drops_the_rest(tmp_path):
    path = tmp_path / "region.pmtiles"
    extract(world(), path)
    assert pmtiles.check_archive(path) > 0
    left, top, _, _ = pmtiles.tile_range(6, BBOX)
    inside = pmtiles.tile_id(6, left, top)
    assert read_tile(path, inside) == tile_bytes(inside)
    assert read_tile(path, pmtiles.tile_id(6, 60, 10)) is None
    # Low zooms stay, so the map still opens zoomed out.
    assert read_tile(path, pmtiles.tile_id(0, 0, 0)) is not None


def test_small_requests_only_for_the_region(tmp_path):
    source = world()
    reader = Memory(source)
    plan = pmtiles.make_plan(reader, (-79.0, 35.0, -78.0, 36.0), 6)
    assert plan.tile_bytes < pmtiles.parse_header(source).tile_length / 10


def test_a_damaged_tile_is_refused(tmp_path):
    source = bytearray(world())
    header = pmtiles.parse_header(bytes(source))
    plan = pmtiles.make_plan(Memory(bytes(source)), BBOX, 6)
    offset = plan.chunks()[-1]
    source[header.tile_offset + offset[0] + offset[1] - 6] ^= 0xff
    reader = Memory(bytes(source))
    with (tmp_path / "x").open("wb") as output, pytest.raises(ValueError):
        pmtiles.download_tiles(reader, pmtiles.make_plan(reader, BBOX, 6), output, 0)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        if self.path == "/builds.json":
            body = json.dumps(server.builds).encode()
            self.send_response(200)
        elif self.path == "/gone.pmtiles":
            body = b"gone"
            self.send_response(404)
        else:
            server.reads += 1
            if server.fail_at is not None and server.reads >= server.fail_at:
                server.fail_at = None
                self.close_connection = True
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = self.headers["Range"][6:].split("-")
            body = server.source[int(start):int(end) + 1]
            self.send_response(206)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.source = world()
    server.reads = 0
    server.fail_at = None
    server.builds = [{"key": "20261030.pmtiles", "version": "4.1.0"},
                     {"key": "20261031.pmtiles", "version": "4.2.0"},
                     {"key": "20261101.pmtiles", "version": "5.0.0"}]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


@pytest.fixture
def worker(tmp_path, monkeypatch, site):
    base = f"http://127.0.0.1:{site.server_address[1]}"
    monkeypatch.setattr(acquire, "MAP_BUILDS_URL", f"{base}/builds.json")
    monkeypatch.setattr(acquire, "MAP_BUILD_BASE", f"{base}/")
    monkeypatch.setattr(acquire, "RETRY_WAIT", 0)
    monkeypatch.setattr(acquire, "RETRIES", 2)
    catalog = tmp_path / "manifests"
    (catalog / "catalog").mkdir(parents=True)
    (catalog / "budgets.json").write_text((REPO / "content-manifests/budgets.json").read_text())
    entry = {"id": "map-test", "title": "Test map", "format": "pmtiles", "budget_category": "maps",
             "destination": "maps/test.pmtiles", "extract": {"bbox": list(BBOX), "max_zoom": 6},
             "size_bytes": {"value": 1000, "status": "unverified"},
             "publication_date": {"value": "2026-11-01"}}
    (catalog / "catalog/map-test.json").write_text(json.dumps(entry))
    state = tmp_path / "state"
    state.mkdir()
    return Worker(Paths(state, catalog))


def job(worker):
    return content.enqueue(worker.db, "install", "map-test")


def state_of(worker, job_id):
    return worker.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def test_newest_build_with_a_matching_layout_is_chosen(worker):
    assert acquire.latest_map_build()["version"] == "20261031"


def test_install_records_a_usable_map(worker):
    job_id = job(worker)
    worker.run()
    assert state_of(worker, job_id)["state"] == "done"
    row = worker.db.execute("SELECT * FROM installed WHERE id='map-test'").fetchone()
    assert row["version"] == "20261031"
    assert row["path"] == "maps/test.pmtiles"
    assert pmtiles.check_archive(worker.paths.state / row["path"]) > 0
    assert not list(worker.paths.partial.iterdir())
    assert acquire.sha256_file(worker.paths.state / row["path"]) == row["sha256"]


def test_interrupted_install_resumes_without_refetching(worker, site, monkeypatch):
    monkeypatch.setattr(pmtiles, "MERGE_GAP", 0)
    monkeypatch.setattr(pmtiles, "MAX_REQUEST", 512)
    monkeypatch.setattr(acquire, "RETRIES", 1)
    counter = Memory(site.source)
    plan = pmtiles.make_plan(counter, BBOX, 6)
    requests = len(list(pmtiles.requests(plan.chunks())))
    assert requests > 3
    site.fail_at = counter.calls + requests // 2 + 1
    job_id = job(worker)
    worker.run()
    assert state_of(worker, job_id)["state"] == "failed"
    assert (worker.paths.partial / "test.pmtiles.part").stat().st_size > pmtiles.ROOT_BYTES
    site.reads = 0
    worker.db.execute("UPDATE jobs SET state='queued', error=NULL WHERE id=?", (job_id,))
    worker.db.commit()
    worker.run()
    assert state_of(worker, job_id)["state"] == "done"
    # Directories are read again, but tiles already saved are not.
    assert site.reads <= counter.calls + requests - requests // 2
    whole = worker.paths.state / "maps/test.pmtiles"
    left, top, _, _ = pmtiles.tile_range(6, BBOX)
    inside = pmtiles.tile_id(6, left, top)
    assert read_tile(whole, inside) == tile_bytes(inside)
    assert pmtiles.check_archive(whole) > 0


def test_lost_build_starts_over_from_the_newest(worker):
    part = worker.paths.partial / "test.pmtiles.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(bytes(pmtiles.ROOT_BYTES + 5))
    base = acquire.MAP_BUILD_BASE
    part.with_suffix(".json").write_text(json.dumps({"version": "old", "url": f"{base}gone.pmtiles"}))
    job_id = job(worker)
    worker.run()
    assert state_of(worker, job_id)["state"] == "done"
    assert worker.db.execute("SELECT version FROM installed").fetchone()["version"] == "20261031"


def test_map_ceiling_is_enforced_with_the_real_size(worker, monkeypatch):
    def refuse(*args):
        raise Refused("Maps would pass its 85 GB ceiling")
    monkeypatch.setattr(content, "check", refuse)
    job_id = job(worker)
    worker.run()
    assert state_of(worker, job_id)["state"] == "failed"
    assert not (worker.paths.state / "maps/test.pmtiles").exists()


def test_map_is_served_with_range_requests(worker):
    worker.run_job(state_of(worker, job(worker)))
    client = TestClient(create_app(state_dir=worker.paths.state, catalog_dir=worker.paths.catalog))
    assert client.get("/api/maps").json()["maps"][0]["id"] == "map-test"
    response = client.get("/api/maps/map-test/file", headers={"Range": "bytes=0-126"})
    assert response.status_code == 206
    assert response.content[:7] == b"PMTiles"
    assert client.get("/api/maps/nothing/file").status_code == 404


def test_tile_lookup_reads_an_installed_map(worker):
    worker.run_job(state_of(worker, job(worker)))
    reader = pmtiles.TileFile(worker.paths.state / "maps/test.pmtiles")
    left, top, _, _ = pmtiles.tile_range(6, BBOX)
    assert reader.tile(6, left, top) == tile_bytes(pmtiles.tile_id(6, left, top))
    assert reader.tile(6, 60, 10) is None
    client = TestClient(create_app(state_dir=worker.paths.state, catalog_dir=worker.paths.catalog))
    tile = client.get(f"/api/maps/map-test/tile/6/{left}/{top}")
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "application/octet-stream"
    assert client.get("/api/maps/map-test/tile/6/60/10").status_code == 404
    assert client.get("/api/maps/map-test/tile/6/999/10").status_code == 404
    found = client.get("/api/maps").json()["maps"][0]
    assert found["kind"] == "base"
    assert found["bbox"] == list(BBOX)


def test_webp_tiles_are_checked():
    good = b"RIFF" + (8).to_bytes(4, "little") + b"WEBP" + bytes(4)
    pmtiles.check_tile(good, 1, pmtiles.WEBP)
    with pytest.raises(ValueError):
        pmtiles.check_tile(good[:-2], 1, pmtiles.WEBP)
    with pytest.raises(ValueError):
        pmtiles.check_tile(b"junkjunkjunkjunk", 1, pmtiles.WEBP)


def test_named_source_uses_its_version_record(worker, site, monkeypatch):
    base = acquire.MAP_BUILD_BASE
    site.builds = {"version": "0.0.13"}
    entry = {"extract": {"source": f"{base}planet.pmtiles", "version_url": f"{base}builds.json"}}
    assert acquire.latest_extract(entry) == {"version": "0.0.13", "url": f"{base}planet.pmtiles"}


GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
<wpt lat="35.5" lon="-80.25"><ele>210.5</ele><name>Cabin &amp; well</name><desc>Spring</desc></wpt>
<rte><name>Ridge</name><rtept lat="35.1" lon="-80.1"/><rtept lat="35.2" lon="-80.2"/></rte>
<trk><name>Walk</name><trkseg><trkpt lat="36" lon="-79"><ele>5</ele></trkpt>
<trkpt lat="36.1" lon="-79.1"/></trkseg><trkseg><trkpt lat="1" lon="2"/><trkpt lat="3" lon="4"/></trkseg></trk>
</gpx>"""


def test_gpx_round_trip_is_lossless(tmp_path):
    first = navigation.connect(tmp_path / "a.db")
    assert navigation.import_gpx(first, GPX) == {"waypoints": 1, "routes": 3}
    exported = navigation.export_gpx(first)
    second = navigation.connect(tmp_path / "b.db")
    navigation.import_gpx(second, exported)
    assert navigation.export_gpx(second) == exported
    a, b = navigation.overview(first), navigation.overview(second)
    assert a["routes"] == b["routes"]
    item = b["waypoints"][0]
    assert (item["name"], item["lat"], item["lon"], item["elevation"], item["notes"]) == \
        ("Cabin & well", 35.5, -80.25, 210.5, "Spring")
    assert [route["name"] for route in b["routes"]] == ["Ridge", "Walk 1", "Walk 2"]


def test_gpx_v1_0_is_read(tmp_path):
    data = GPX.replace(b"topografix.com/GPX/1/1", b"topografix.com/GPX/1/0")
    assert navigation.parse_gpx(data)["waypoints"][0]["name"] == "Cabin & well"


@pytest.mark.parametrize("data", [
    b"not xml",
    b"<html></html>",
    b'<gpx><wpt lat="99" lon="0"/></gpx>',
    b'<gpx><wpt lon="0"/></gpx>',
    b"<gpx></gpx>",
    b'<!DOCTYPE gpx [<!ENTITY a "b">]><gpx>&a;</gpx>',
    b"<gpx>" + b" " * navigation.MAX_GPX_BYTES,
])
def test_bad_gpx_is_refused(data):
    with pytest.raises(navigation.BadGpx):
        navigation.parse_gpx(data)


def test_navigation_api(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "walk.gpx").write_bytes(GPX)
    (usb / "bad.gpx").write_bytes(b"nope")
    catalog = REPO / "content-manifests"
    client = TestClient(create_app(state_dir=tmp_path / "s", catalog_dir=catalog, usb_root=usb))
    made = client.post("/api/navigation/waypoints", json={"name": "A", "lat": 1, "lon": 2}).json()
    assert client.post("/api/navigation/waypoints",
                       json={"name": "B", "lat": 100, "lon": 2}).status_code == 422
    assert client.get("/api/navigation/usb").json()["files"] == ["bad.gpx", "walk.gpx"]
    assert client.post("/api/navigation/import", json={"path": "walk.gpx"}).json() == \
        {"waypoints": 1, "routes": 3}
    assert client.post("/api/navigation/import", json={"path": "bad.gpx"}).status_code == 422
    assert client.post("/api/navigation/import", json={"path": "../x.gpx"}).status_code == 404
    data = client.get("/api/navigation").json()
    assert len(data["waypoints"]) == 2
    assert client.get("/api/navigation/export.gpx").content.count(b"<wpt") == 2
    client.delete(f"/api/navigation/waypoints/{made['id']}")
    client.delete(f"/api/navigation/routes/{data['routes'][0]['id']}")
    data = client.get("/api/navigation").json()
    assert (len(data["waypoints"]), len(data["routes"])) == (1, 2)
    assert client.post("/api/navigation/waypoints", json={"name": "C", "lat": 1, "lon": 2},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
