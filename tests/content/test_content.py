import hashlib
import importlib.machinery
import importlib.util
import http.server
import json
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from survival_os import acquire, content, removable
from survival_os.acquire import Worker
from survival_os.content import Paths, Refused
from survival_os.main import create_app

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = bytes(range(256)) * 40000  # 10 MB


class Server(http.server.ThreadingHTTPServer):
    payload = PAYLOAD
    cut_after: int | None = None
    ranges = True
    declare_length = True
    requests: list[str | None]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server: Server = self.server
        requested = self.headers.get("Range")
        server.requests.append(requested)
        start = int(requested[6:-1]) if requested and server.ranges else 0
        body = server.payload[start:]
        self.send_response(206 if start else 200)
        if start:
            self.send_header("Content-Range", f"bytes {start}-/{len(server.payload)}")
        if server.declare_length:
            self.send_header("Content-Length", str(len(body)))
        else:
            self.close_connection = True
        self.end_headers()
        if server.cut_after is not None:
            limit, server.cut_after = server.cut_after, None
            self.wfile.write(body[:limit])
            return
        self.wfile.write(body)


@pytest.fixture
def server():
    server = Server(("127.0.0.1", 0), Handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def entry(url: str, **overrides) -> dict:
    field = lambda value: {"value": value, "status": "verified", "verified_at": "2026-11-01"}
    item = {
        "id": "sample", "title": "Sample", "publisher": "Test", "format": "pdf",
        "budget_category": "radio", "destination": "radio/sample.pdf", "source_url": field(url),
        "license": field("CC0"), "publication_date": field("2026-01-01"),
        "size_bytes": field(len(PAYLOAD)), "sha256": field(hashlib.sha256(PAYLOAD).hexdigest()),
        "redistribution": {"base_image_allowed": False},
    }
    return {**item, **overrides}


@pytest.fixture
def paths(tmp_path, monkeypatch) -> Paths:
    catalog = tmp_path / "catalog-root"
    (catalog / "catalog").mkdir(parents=True)
    (catalog / "budgets.json").write_text((REPO / "content-manifests/budgets.json").read_text())
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(acquire, "RETRY_WAIT", 0)
    monkeypatch.setattr(acquire, "PROGRESS_INTERVAL", 0)
    return Paths(state, catalog)


def publish(paths: Paths, item: dict) -> None:
    (paths.catalog / "catalog" / f"{item['id']}.json").write_text(json.dumps(item))


def job(paths: Paths, action: str = "install", target: str = "sample") -> dict:
    db = content.connect(paths)
    content.enqueue(db, action, target)
    Worker(paths).run()
    row = dict(db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone())
    db.close()
    return row


def url(server: Server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/sample.pdf"


def part_of(paths: Paths) -> Path:
    return paths.partial / "sample.pdf.part"


def test_install_verifies_and_records(paths, server):
    publish(paths, entry(url(server)))
    assert job(paths)["state"] == "done"
    final = paths.library / "radio" / "sample.pdf"
    assert final.read_bytes() == PAYLOAD
    assert not part_of(paths).exists()
    installed = content.overview(paths)["entries"][0]["installed"]
    assert installed["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()


def test_interrupted_download_resumes_and_passes_the_checksum(paths, server):
    publish(paths, entry(url(server)))
    server.cut_after = 3_000_000
    assert job(paths)["state"] == "done"
    assert server.requests == [None, "bytes=3000000-"]
    assert (paths.library / "radio" / "sample.pdf").read_bytes() == PAYLOAD


def test_resume_of_corrupt_partial_fails_the_checksum(paths, server):
    publish(paths, entry(url(server)))
    part_of(paths).parent.mkdir(parents=True)
    part_of(paths).write_bytes(b"x" * 1_000_000)
    finished = job(paths)
    assert finished["state"] == "failed" and "Checksum failed" in finished["error"]
    assert server.requests == ["bytes=1000000-"]
    assert not part_of(paths).exists()
    assert not (paths.library / "radio" / "sample.pdf").exists()


def test_server_that_ignores_ranges_restarts_cleanly(paths, server):
    publish(paths, entry(url(server)))
    server.ranges = False
    part_of(paths).parent.mkdir(parents=True)
    part_of(paths).write_bytes(PAYLOAD[:1000])
    assert job(paths)["state"] == "done"
    assert (paths.library / "radio" / "sample.pdf").read_bytes() == PAYLOAD


def test_stream_without_a_length_still_installs(paths, server):
    publish(paths, entry(url(server)))
    server.declare_length = False
    assert job(paths)["state"] == "done"
    assert (paths.library / "radio" / "sample.pdf").read_bytes() == PAYLOAD


def test_wrong_size_on_the_server_is_refused(paths, server):
    publish(paths, entry(url(server)))
    server.payload = PAYLOAD[:-1]
    finished = job(paths)
    assert finished["state"] == "failed" and "size" in finished["error"]


def test_power_cut_job_continues_on_next_start(paths, server):
    publish(paths, entry(url(server)))
    db = content.connect(paths)
    content.enqueue(db, "install", "sample")
    db.execute("UPDATE jobs SET state='running'")
    db.commit()
    part_of(paths).parent.mkdir(parents=True)
    part_of(paths).write_bytes(PAYLOAD[:5000])
    Worker(paths).run()
    assert db.execute("SELECT state FROM jobs").fetchone()[0] == "done"
    assert server.requests == ["bytes=5000-"]


def limit(monkeypatch, headroom: int) -> None:
    monkeypatch.setattr(content, "capacity", lambda path: {
        "usable": 10**12, "available": 150 * 10**9 + headroom, "floor": 150 * 10**9,
        "headroom": headroom})


def test_floor_blocks_before_any_download(paths, server, monkeypatch):
    publish(paths, entry(url(server)))
    limit(monkeypatch, len(PAYLOAD) - 1)
    finished = job(paths)
    assert finished["state"] == "failed" and "15% free floor" in finished["error"]
    assert server.requests == []


def test_operation_that_exactly_fits_is_allowed(paths, server, monkeypatch):
    publish(paths, entry(url(server)))
    limit(monkeypatch, len(PAYLOAD))
    assert job(paths)["state"] == "done"


def test_resume_only_needs_the_remaining_bytes(paths, server, monkeypatch):
    publish(paths, entry(url(server)))
    part_of(paths).parent.mkdir(parents=True)
    part_of(paths).write_bytes(PAYLOAD[:9_000_000])
    limit(monkeypatch, len(PAYLOAD) - 9_000_000)
    assert job(paths)["state"] == "done"


def test_download_stops_if_room_runs_out_midway(paths, server, monkeypatch):
    publish(paths, entry(url(server)))
    calls = iter([len(PAYLOAD), len(PAYLOAD)])
    real = lambda path: {"usable": 10**12, "available": 2 * 10**11, "floor": 15 * 10**10,
                         "headroom": next(calls, 0)}
    monkeypatch.setattr(content, "capacity", real)
    finished = job(paths)
    assert finished["state"] == "failed" and "floor" in finished["error"]
    assert part_of(paths).exists()


def test_category_ceiling_blocks(paths, server):
    publish(paths, entry(url(server), size_bytes={"value": 21 * content.GB, "status": "verified",
                                                  "verified_at": "2026-11-01"}))
    with pytest.raises(Refused, match="10 GB ceiling"):
        content.check(paths, "radio", 0, 21 * content.GB)


def test_each_file_counts_in_one_category_only(paths, server):
    publish(paths, entry(url(server)))
    job(paths)
    used = content.category_usage(paths)
    assert used["radio"] >= len(PAYLOAD)
    assert used["radio"] < len(PAYLOAD) * 1.01
    assert sum(value for key, value in used.items() if key != "radio") == 0
    rows = content.summary(paths)
    assert sum(item["used_bytes"] for item in rows["categories"]) == rows["used"]


def test_remove_frees_the_file_and_validate_detects_damage(paths, server):
    publish(paths, entry(url(server)))
    job(paths)
    final = paths.library / "radio" / "sample.pdf"
    assert job(paths, "validate")["state"] == "done"
    final.write_bytes(b"damaged")
    assert "damaged" in job(paths, "validate")["error"]
    assert job(paths, "remove")["state"] == "done"
    assert not final.exists()
    assert content.overview(paths)["entries"][0]["installed"] is None


def test_update_replaces_the_old_version(paths, server):
    publish(paths, entry(url(server)))
    job(paths)
    fresh = PAYLOAD[::-1]
    server.payload = fresh
    publish(paths, entry(url(server), sha256={
        "value": hashlib.sha256(fresh).hexdigest(), "status": "verified",
        "verified_at": "2026-11-01"}))
    db = content.connect(paths)
    db.execute("INSERT INTO updates VALUES ('sample', '2027-01-01', ?, ?)",
               (url(server), len(fresh)))
    db.commit()
    assert job(paths, "update")["state"] == "done"
    installed = content.overview(paths)["entries"][0]
    assert installed["installed"]["version"] == "2027-01-01" and installed["update"] is None
    assert (paths.library / "radio" / "sample.pdf").read_bytes() == fresh


def test_meta4_supplies_size_and_checksum(monkeypatch):
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return (
            b'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="a.zim">'
            b'<size>123</size><hash type="md5">x</hash><hash type="sha-256">abc</hash>'
            b'</file></metalink>')
    monkeypatch.setattr(acquire, "fetch", lambda url: Reply())
    source = acquire.resolve_source(entry("https://x.example/a.zim.meta4"))
    assert (source.url, source.size, source.sha256) == ("https://x.example/a.zim", 123, "abc")


def usb_file(root: Path, name: str, data: bytes) -> None:
    root.mkdir(exist_ok=True)
    (root / name).write_bytes(data)


def import_job(paths, root, name, category="radio"):
    worker = Worker(paths)
    db = content.connect(paths)
    job_id = content.enqueue(db, "import", name)
    removable.import_file(worker, job_id, json.dumps({"path": name, "category": category}), root)
    return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def test_import_copies_then_skips_an_identical_file(paths, tmp_path):
    usb = tmp_path / "usb"
    usb_file(usb, "manual.pdf", b"manual")
    usb_file(usb, "again.pdf", b"manual")
    import_job(paths, usb, "manual.pdf")
    assert (paths.library / "radio" / "manual.pdf").read_bytes() == b"manual"
    assert "Already installed" in import_job(paths, usb, "again.pdf")["error"]
    assert not (paths.library / "radio" / "again.pdf").exists()


def test_import_cannot_leave_the_drive(paths, tmp_path):
    usb = tmp_path / "usb"
    usb_file(usb, "a.pdf", b"a")
    (tmp_path / "secret.pdf").write_bytes(b"s")
    with pytest.raises(Refused):
        import_job(paths, usb, "../secret.pdf")


def test_import_respects_the_floor(paths, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    usb_file(usb, "a.pdf", b"abc")
    limit(monkeypatch, 2)
    with pytest.raises(Refused, match="floor"):
        import_job(paths, usb, "a.pdf")


def test_scan_ignores_other_files(tmp_path):
    usb_file(tmp_path, "book.zim", b"z")
    usb_file(tmp_path, "note.txt", b"t")
    usb_file(tmp_path, "tool.exe", b"e")
    assert [item["path"] for item in removable.scan(tmp_path)] == ["book.zim", "note.txt"]


@pytest.fixture
def api(paths, server, tmp_path):
    publish(paths, entry(url(server)))
    calls: list[str] = []

    def run_action(action):
        calls.append(action)
        return True

    client = TestClient(create_app(
        static_dir=tmp_path / "none", state_dir=paths.state, catalog_dir=paths.catalog,
        run_action=run_action, actions_enabled=True, usb_helper=lambda action: action == "mount",
        usb_root=tmp_path / "usb"))
    client.post("/api/admin/pin", json={"pin": "1234"})
    client.calls = calls
    return client


def test_api_install_needs_the_pin_and_starts_the_worker(api):
    body = {"action": "install", "id": "sample", "pin": "9999"}
    assert api.post("/api/content/action", json=body).status_code == 403
    assert api.calls == []
    assert api.post("/api/content/action", json={**body, "pin": "1234"}).status_code == 202
    assert api.calls == ["content"]


def test_api_refuses_past_the_floor_with_no_job(api, monkeypatch, paths):
    limit(monkeypatch, 1)
    response = api.post("/api/content/action",
                        json={"action": "install", "id": "sample", "pin": "1234"})
    assert response.status_code == 507 and "15% free floor" in response.json()["detail"]
    assert api.calls == [] and api.get("/api/content").json()["jobs"] == []


def test_api_shows_usage_licences_and_verification(api):
    data = api.get("/api/content").json()
    assert len(data["storage"]["categories"]) == 13
    assert data["entries"][0]["license_status"] == "verified"


def test_api_refuses_cross_site_content_changes(api):
    response = api.post("/api/content/action", headers={"Sec-Fetch-Site": "cross-site"},
                        json={"action": "remove", "id": "sample", "pin": "1234"})
    assert response.status_code == 403
    assert api.post("/api/content/usb/mount", headers={"Origin": "http://127.0.0.1:8083"},
                    json={"pin": "1234"}).status_code == 403


def test_api_cancel_keeps_a_queued_job_from_running(api, paths):
    api.post("/api/content/action", json={"action": "install", "id": "sample", "pin": "1234"})
    job_id = api.get("/api/content").json()["jobs"][0]["id"]
    api.post(f"/api/content/jobs/{job_id}/cancel")
    assert api.get("/api/content").json()["jobs"][0]["state"] == "cancelled"


def usb_helper():
    loader = importlib.machinery.SourceFileLoader("survival_usb", str(REPO / "installers/survival-usb"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("survival_usb", loader))
    loader.exec_module(module)
    return module


SYSTEM = {"path": "/dev/sda", "type": "disk", "tran": "usb", "fstype": None, "mountpoint": None,
          "children": [
              {"path": "/dev/sda1", "type": "part", "tran": None, "fstype": "vfat",
               "mountpoint": "/boot/firmware"},
              {"path": "/dev/sda2", "type": "part", "tran": None, "fstype": "ext4",
               "mountpoint": "/"}]}


def stick(path="/dev/sdb", tran="usb", fstype="exfat"):
    return {"path": path, "type": "disk", "tran": tran, "fstype": None, "mountpoint": None,
            "children": [{"path": f"{path}1", "type": "part", "tran": None, "fstype": fstype,
                          "mountpoint": None}]}


def test_usb_helper_never_picks_the_system_disk():
    assert usb_helper().choose([SYSTEM]) is None


def test_usb_helper_picks_the_stick_after_the_system_disk():
    assert usb_helper().choose([SYSTEM, stick()]) == "/dev/sdb1"


def test_usb_helper_ignores_internal_disks_and_unknown_filesystems():
    assert usb_helper().choose([stick("/dev/nvme0n1", tran="nvme")]) is None
    assert usb_helper().choose([stick(fstype="LVM2_member")]) is None


def test_usb_helper_handles_a_stick_with_no_partition_table():
    disk = {"path": "/dev/sdb", "type": "disk", "tran": "usb", "fstype": "vfat",
            "mountpoint": None}
    assert usb_helper().choose([SYSTEM, disk]) == "/dev/sdb"


def test_archive_keeps_only_the_wanted_files(paths, tmp_path, server):
    bundle = tmp_path / "repo.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("repo-abc/docs/start.mdx",
                         '---\ntitle: Getting Started\n---\nimport X from "y";\n<Tabs>\nHello mesh\n')
        archive.writestr("repo-abc/static/photo.webp", b"image")
        archive.writestr("repo-abc/static/guide.pdf", b"pdf")
        archive.writestr("repo-abc/package.json", b"{}")
    server.payload = bundle.read_bytes()
    publish(paths, entry(url(server), destination="radio/sample-docs",
                         archive={"keep": ["docs/*.mdx", "static/*.pdf"]},
                         format="markdown",
                         size_bytes={"value": len(server.payload), "status": "verified",
                                     "verified_at": "2026-11-01"},
                         sha256={"value": hashlib.sha256(server.payload).hexdigest(),
                                 "status": "verified", "verified_at": "2026-11-01"}))
    assert job(paths)["state"] == "done"
    folder = paths.library / "radio" / "sample-docs"
    assert sorted(item.name for item in folder.rglob("*") if item.is_file()) == [
        "guide.pdf", "start.md"]
    assert (folder / "docs" / "start.md").read_text() == "# Getting Started\n\nHello mesh\n"
    assert not list(paths.partial.iterdir())
    assert job(paths, "validate")["state"] == "done"
    assert job(paths, "remove")["state"] == "done"
    assert not folder.exists()


@pytest.mark.parametrize("kind", ["firmware", "software"])
def test_downloads_are_stored_outside_the_library(paths, server, kind):
    publish(paths, entry(url(server), format=kind, destination=f"{kind}/fw.zip"))
    assert job(paths)["state"] == "done"
    assert (paths.content / kind / "fw.zip").read_bytes() == PAYLOAD
    assert content.category_usage(paths)["radio"] >= len(PAYLOAD)


def test_catalog_fits_its_ceilings():
    paths = Paths(REPO, REPO / "content-manifests")
    totals = {}
    for item in content.load_catalog(paths).values():
        key = item["budget_category"]
        totals[key] = totals.get(key, 0) + item["size_bytes"]["value"]
    budgets = content.load_budgets(paths)
    assert sum(item["cap_gb"] for item in budgets.values()) == 800
    assert {key: value for key, value in totals.items()
            if value > budgets[key]["cap_gb"] * content.GB} == {}
