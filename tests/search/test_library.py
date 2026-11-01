import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from survival_os.main import create_app
from survival_search import cli, extract, indexer, query, render
from survival_search.indexer import Indexer, Paths

from .corpus import build, write_pdf


@pytest.fixture
def paths(tmp_path) -> Paths:
    paths = Paths(tmp_path / "state")
    build(paths.library)
    Indexer(paths, pause_ratio=0).run_once()
    return paths


def top(paths, text, **filters):
    results = query.search(paths, text, **filters)["results"]
    assert results, text
    return results[0]


def row_counts(path: Path) -> tuple[int, int]:
    db = sqlite3.connect(path)
    db.execute("INSERT INTO passages_fts(passages_fts) VALUES ('integrity-check')")
    locations = db.execute("SELECT count(DISTINCT document_id || '-' || page) FROM passages")
    return locations.fetchone()[0], db.execute("SELECT count(*) FROM passages").fetchone()[0]


@pytest.mark.parametrize("text, title, page, label", [
    ("bleeding", "first-aid", 2, "Page 2"),
    ("purification boiling", "first-aid", 3, "Page 3"),
    ("tinder", "Field Manual", 2, "Fire"),
    ("repeaters", "Band Plan", 1, "MD"),
    ("generator oil", "notes", 1, "TXT"),
    ("bowline", "Knots", 1, "HTML"),
])
def test_finds_text_at_its_location(paths, text, title, page, label):
    result = top(paths, text)
    assert (result["title"], result["page"], result["label"]) == (title, page, label)


def test_snippet_marks_the_hit_and_stems(paths):
    result = top(paths, "bleed")
    assert result["hits"] == ["bleeding"]
    joined = "".join(part["text"] for part in result["snippet"])
    assert joined == "Apply direct pressure to control bleeding from a wound"


def test_scripts_and_styles_are_not_indexed(paths):
    for text in ("evil", "alert", "rope", "color"):
        assert query.search(paths, text)["results"] == []


def test_markdown_syntax_is_not_in_snippets(paths):
    assert "**" not in "".join(p["text"] for p in top(paths, "metre")["snippet"])


def test_filters(paths):
    assert top(paths, "bleeding", fmt="pdf")["format"] == "pdf"
    assert query.search(paths, "bleeding", fmt="epub")["total"] == 0
    assert top(paths, "bleeding", category="medical_survival")
    assert query.search(paths, "bleeding", category="radio")["total"] == 0


@pytest.mark.parametrize("text", ['"', "AND", "a OR", "NEAR(", "col:x", "*", "-x", "(((", "'"])
def test_hostile_queries_do_not_error(paths, text):
    assert isinstance(query.search(paths, text)["results"], list)


def test_phrase_needs_adjacent_words(paths):
    assert query.search(paths, '"direct pressure"')["total"] == 1
    assert query.search(paths, '"pressure direct"')["total"] == 0


def test_long_text_gives_one_result_per_location(tmp_path):
    paths = Paths(tmp_path / "state")
    paths.library.mkdir(parents=True)
    (paths.library / "long.txt").write_text("rainwater collection works well here.\n" * 900)
    Indexer(paths, pause_ratio=0).run_once()
    assert row_counts(paths.database)[1] > 1
    found = query.search(paths, "rainwater")
    assert found["total"] == 1 and len(found["results"]) == 1


def test_phrase_on_a_chunk_boundary_is_found():
    text = "x" * (extract.MAX_CHUNK - 5) + " needle thread " + "y" * 3000
    assert any("needle thread" in part for part in extract.chunks(text))


def test_rescan_is_incremental(paths):
    before = sqlite3.connect(paths.database).execute(
        "SELECT id, sha256 FROM documents ORDER BY id").fetchall()
    assert indexer.scan(indexer.store.connect(paths.database), paths.library) == 0
    after = sqlite3.connect(paths.database).execute(
        "SELECT id, sha256 FROM documents ORDER BY id").fetchall()
    assert before == after


def test_changed_file_is_reindexed(paths):
    (paths.library / "notes.txt").write_text("The pump needs a new seal.\n")
    Indexer(paths, pause_ratio=0).run_once()
    assert top(paths, "pump")["title"] == "notes"
    assert query.search(paths, "generator")["total"] == 0


def test_deleted_file_leaves_the_index(paths):
    (paths.library / "notes.txt").unlink()
    Indexer(paths, pause_ratio=0).run_once()
    assert query.search(paths, "generator")["total"] == 0
    row_counts(paths.database)


def test_deleting_a_document_leaves_no_large_log(tmp_path):
    paths = Paths(tmp_path / "state")
    paths.library.mkdir(parents=True)
    big = paths.library / "big.txt"
    big.write_text("rainwater collection works well here.\n" * 200000)
    Indexer(paths, pause_ratio=0).run_once()
    big.unlink()
    Indexer(paths, pause_ratio=0).run_once()
    assert paths.database.with_name("library.db-wal").stat().st_size < 1024 * 1024


def test_catalog_title_replaces_the_embedded_one(tmp_path):
    paths = Paths(tmp_path / "state")
    (paths.library / "radio").mkdir(parents=True)
    write_pdf(paths.library / "radio" / "guide.pdf", ["Repeater offsets for the two metre band"])
    (paths.state / "content").mkdir()
    db = sqlite3.connect(paths.state / "content" / "content.db")
    db.execute("CREATE TABLE installed (path TEXT, title TEXT)")
    db.execute("INSERT INTO installed VALUES ('library/radio/guide.pdf', 'Field Guide')")
    db.commit()
    db.close()
    Indexer(paths, pause_ratio=0).run_once()
    assert top(paths, "repeater")["title"] == "Field Guide"


def test_moved_file_keeps_its_index_and_takes_the_new_category(paths):
    before = top(paths, "generator")["document_id"]
    target = paths.library / "mechanical"
    target.mkdir()
    (paths.library / "notes.txt").rename(target / "notes.txt")
    Indexer(paths, pause_ratio=0).run_once()
    result = top(paths, "generator")
    assert (result["document_id"], result["category"]) == (before, "mechanical")


def test_bad_files_fail_alone(paths):
    (paths.library / "broken.pdf").write_bytes(b"%PDF-1.4 nonsense")
    (paths.library / "broken.epub").write_bytes(b"not a zip")
    Indexer(paths, pause_ratio=0).run_once()
    failed = {item["path"]: item["error"] for item in query.status(paths)["failed"]}
    assert failed == {"broken.epub": "EPUB could not be opened",
                      "broken.pdf": "PDF could not be opened"}
    assert top(paths, "bleeding")


def test_file_that_keeps_killing_the_indexer_is_skipped(paths):
    db = indexer.store.connect(paths.database)
    (paths.library / "extra.txt").write_text("searchable marker\n")
    indexer.scan(db, paths.library)
    db.execute("UPDATE documents SET attempts=3 WHERE path='extra.txt'")
    db.commit()
    db.close()
    Indexer(paths, pause_ratio=0).run_pending()
    assert [item["path"] for item in query.status(paths)["failed"]] == ["extra.txt"]


def test_page_without_text_is_counted(tmp_path):
    paths = Paths(tmp_path / "state")
    paths.library.mkdir(parents=True)
    write_pdf(paths.library / "scan.pdf", ["", "A page with plenty of real text on it"])
    Indexer(paths, pause_ratio=0).run_once()
    assert query.status(paths)["no_text"] == [{"path": "scan.pdf", "pages_no_text": 1}]


def test_indexing_stops_at_the_floor(paths, monkeypatch):
    (paths.library / "extra.txt").write_text("floor marker\n")
    monkeypatch.setattr(indexer, "bytes_above_floor", lambda path: 0)
    Indexer(paths, pause_ratio=0).run_once()
    assert query.status(paths)["indexer"]["state"] == "paused"
    assert query.search(paths, "marker")["total"] == 0


def test_import_copies_and_refuses_past_the_floor(paths, tmp_path, monkeypatch):
    source = tmp_path / "usb"
    source.mkdir()
    (source / "manual.txt").write_text("hello\n")
    (source / "ignored.exe").write_text("no\n")
    assert cli.import_files(paths, source, "mechanical") == 1
    assert (paths.library / "mechanical" / "manual.txt").is_file()
    assert not (paths.library / "mechanical" / "ignored.exe").exists()
    monkeypatch.setattr(cli, "bytes_above_floor", lambda path: 1)
    with pytest.raises(SystemExit, match="floor"):
        cli.import_files(paths, source, "radio")
    assert not (paths.library / "radio" / "manual.txt").exists()


def test_first_scan_runs_straight_after_boot(tmp_path, monkeypatch):
    paths = Paths(tmp_path / "state")
    paths.library.mkdir(parents=True)
    (paths.library / "notes.txt").write_text("Found right after boot.\n")
    monkeypatch.setattr(indexer.time, "monotonic", lambda: 1.0)
    worker = Indexer(paths, pause_ratio=0)
    monkeypatch.setattr(indexer.time, "sleep", worker.stop)
    worker.run_forever()
    assert top(paths, "boot")["title"] == "notes"


def test_forced_kill_resumes_without_duplicates(tmp_path):
    paths = Paths(tmp_path / "state")
    paths.library.mkdir(parents=True)
    pages = [f"Unique marker word{index} on this page of the manual" for index in range(400)]
    write_pdf(paths.library / "big.pdf", pages)
    command = [sys.executable, "-m", "survival_search.indexer_main", "--once",
               "--pause-ratio", "2"]
    environment = {**os.environ, "SURVIVAL_STATE_DIR": str(paths.state)}
    process = subprocess.Popen(command, env=environment)
    deadline = time.monotonic() + 30
    done = 0
    while time.monotonic() < deadline and done < 40:
        time.sleep(0.02)
        if paths.database.exists():
            try:
                done = query.status(paths)["pages_done"]
            except sqlite3.OperationalError:
                pass
    process.send_signal(signal.SIGKILL)
    process.wait()
    partial = query.status(paths)["pages_done"]
    assert 40 <= partial < 400

    subprocess.run([*command[:-2], "--pause-ratio", "0"], env=environment, check=True)
    assert query.status(paths)["pages_done"] == 400
    assert row_counts(paths.database) == (400, 400)
    for index in (0, partial - 1, partial, 399):
        assert top(paths, f"word{index}")["page"] == index + 1


def test_sanitize_removes_active_content():
    html = render.sanitize(
        '<p onclick="x()" style="color:red">Hi<script>bad()</script></p>'
        '<a href="http://x.example">link</a><iframe src="//x.example"></iframe>'
        '<img src="http://x.example/a.png"><style>p{}</style><form><input></form>')
    assert html == "<p>Hi</p>link<img>"
    assert render.sanitize("<html><head><title>Name</title></head><p>Body</p>") == "<p>Body</p>"


@pytest.fixture
def client(paths) -> TestClient:
    return TestClient(create_app(static_dir=paths.state / "none", state_dir=paths.state))


def test_api_search_and_views(client):
    found = client.get("/api/library/search", params={"q": "tinder"}).json()
    result = found["results"][0]
    view = client.get(f"/api/library/documents/{result['document_id']}/view",
                      params={"page": result["page"]}).json()
    assert view["kind"] == "html" and "Tinder must be kept" in view["html"]
    assert "script" not in view["html"] and "remote.example" not in view["html"]
    assert "/asset?path=OEBPS%2Fpic.png" in view["html"]


def test_api_epub_asset_rules(client):
    document_id = client.get("/api/library/search", params={"q": "tinder"}).json()[
        "results"][0]["document_id"]
    url = f"/api/library/documents/{document_id}/asset"
    response = client.get(url, params={"path": "OEBPS/pic.png"})
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    for name in ("OEBPS/c0.xhtml", "../../etc/passwd", "OEBPS/missing.png"):
        assert client.get(url, params={"path": name}).status_code == 404


def test_api_pdf_file_supports_ranges_and_is_sandboxed(client):
    document_id = client.get("/api/library/search", params={"q": "bleeding"}).json()[
        "results"][0]["document_id"]
    url = f"/api/library/documents/{document_id}/file"
    full = client.get(url)
    assert full.headers["content-security-policy"] == "sandbox"
    part = client.get(url, headers={"Range": "bytes=0-7"})
    assert part.status_code == 206 and part.content == b"%PDF-1.4"


def test_api_only_pdfs_are_served_raw(client):
    document_id = client.get("/api/library/search", params={"q": "bowline"}).json()[
        "results"][0]["document_id"]
    assert client.get(f"/api/library/documents/{document_id}/file").status_code == 404
    assert client.get("/api/library/documents/9999/view").status_code == 404


def test_api_status_with_no_library(tmp_path):
    client = TestClient(create_app(static_dir=tmp_path / "none", state_dir=tmp_path))
    assert client.get("/api/library/status").json()["documents"] == 0
    assert client.get("/api/library/search", params={"q": "x"}).json()["results"] == []


def test_api_rescan_refuses_cross_site(client, paths):
    assert client.post("/api/library/rescan", headers={"Sec-Fetch-Site": "cross-site"}
                       ).status_code == 403
    assert client.post("/api/library/rescan").status_code == 202
    assert paths.rescan_flag.exists()
