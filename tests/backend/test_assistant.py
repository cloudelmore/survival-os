import http.server
import json
import threading
import tarfile

import pytest
from fastapi.testclient import TestClient
from survival_search import query
from survival_search.indexer import Indexer, Paths

from survival_os import acquire, admin, assistant, content
from survival_os.main import create_app

SOURCE = {"title": "Knots", "document_id": 1, "page": 2, "label": None, "format": "pdf",
          "category": "education", "text": "A bowline makes a fixed loop at the end of a rope."}


@pytest.fixture
def retrieve(monkeypatch):
    found = [SOURCE]
    monkeypatch.setattr(query, "passages", lambda paths, text: list(found))
    return found


def run(question="Which knot makes a loop?", ready=True, words=("A bowline makes a fixed loop.",)):
    calls = []

    def model(messages):
        calls.append(messages)
        yield from words
    return list(assistant.ask(None, question, ready, model)), calls


def kinds(events):
    return [event["type"] for event in events]


def test_answer_gets_its_sources_first_and_cites_them(retrieve):
    events, calls = run()
    assert kinds(events) == ["sources", "text", "done"]
    assert events[0]["mode"] == "answer"
    assert "[1] A bowline makes" in calls[0][1]["content"]
    assert events[1]["text"] == "A bowline makes a fixed loop. [1]"


@pytest.mark.parametrize("question", [
    "What dose of aspirin for a child?", "how do I stop bleeding", "Is this mushroom edible?",
    "can I eat these berries", "How do I wire a breaker?", "what voltage is dangerous",
    "treat a snake bite", "CPR steps",
])
def test_restricted_questions_never_reach_the_model(retrieve, question):
    events, calls = run(question)
    assert calls == []
    assert events[0]["mode"] == "restricted"
    assert events[0]["sources"][0]["text"] == SOURCE["text"]
    assert "text" not in kinds(events)


def test_restricted_passage_keeps_the_model_out_of_a_harmless_question(retrieve):
    retrieve[0] = {**SOURCE, "text": "Apply a tourniquet above the injury."}
    events, calls = run("what should I do next?")
    assert calls == [] and events[0]["mode"] == "restricted"


def test_everyday_electronics_words_in_passages_do_not_block_the_model(retrieve):
    retrieve[0] = {**SOURCE, "text": "The radio circuit runs at a voltage of 5 V over a wire."}
    events, calls = run("Which radio is this?", words=("It runs at a voltage of 5 V.",))
    assert calls and events[0]["mode"] == "answer"
    assert "withheld" not in kinds(events)


def test_answer_that_drifts_to_a_restricted_topic_stops_at_once(retrieve):
    words = iter(("Tie it. ", "Then take ", "two pills", " and more"))
    events, _ = run(words=words)
    assert kinds(events) == ["sources", "withheld", "done"]
    assert events[1]["reason"] == "restricted"
    assert next(words) == " and more"


@pytest.mark.parametrize("words", [
    ("The capital of France is Paris.",), ("A bowline makes 40 fixed loops.",), (".",),
])
def test_answers_no_passage_supports_are_withheld(retrieve, words):
    events, _ = run(words=words)
    assert kinds(events) == ["sources", "withheld", "done"]


def test_citation_names_the_passage_that_says_it_not_the_first_one(retrieve):
    retrieve.insert(0, {**SOURCE, "text": "Radios need an antenna."})
    events, _ = run(words=("A bowline makes a fixed loop.",))
    assert events[1]["text"].endswith("[2]")


def test_not_covered_needs_no_citation(retrieve):
    events, _ = run(words=(assistant.NOT_COVERED,))
    assert kinds(events) == ["sources", "text", "done"]
    assert "[" not in events[1]["text"]


def test_model_off_still_gives_the_passages(retrieve):
    events, calls = run(ready=False)
    assert calls == [] and events[0]["mode"] == "off" and events[0]["sources"]


def test_nothing_found_does_not_call_the_model(retrieve):
    retrieve.clear()
    events, calls = run()
    assert calls == [] and events[0]["mode"] == "empty"


def test_a_model_that_fails_ends_cleanly(retrieve):
    def broken(messages):
        raise ConnectionRefusedError
        yield
    events = list(assistant.ask(None, "a knot?", True, broken))
    assert kinds(events) == ["sources", "failed", "done"]


def test_gate_allows_one_answer_and_frees_itself():
    gate = assistant.Gate()
    first = gate.stream([{"type": "done"}])
    with pytest.raises(assistant.Busy):
        gate.stream([])
    assert list(first)
    assert list(gate.stream([{"type": "done"}]))


def test_streaming_client_reads_the_llama_format():
    class Fake(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["stream"] is True
            assert "root ::=" in body["grammar"]
            self.send_response(200)
            self.end_headers()
            for word in ("Hello", " there"):
                data = {"choices": [{"delta": {"content": word}}]}
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    assert "".join(assistant.generate([], url)) == "Hello there"
    server.shutdown()


def make_app(tmp_path, actions, catalog=None):
    def action(name):
        actions.append(name)
        return True
    state = tmp_path / "state"
    app = create_app(tmp_path / "absent", state, lambda: {}, action, actions_enabled=True,
                     catalog_dir=catalog or tmp_path / "catalog")
    return TestClient(app), content.Paths(state, catalog or tmp_path / "catalog")


def test_start_needs_both_packages_and_the_pin(tmp_path):
    actions = []
    client, stores = make_app(tmp_path, actions)
    assert client.post("/api/admin/pin", json={"pin": "1234"}).status_code == 204
    assert client.post("/api/ai/start", json={"pin": "1234"}).status_code == 409
    db = content.connect(stores)
    for item in assistant.PACKAGES:
        db.execute("INSERT INTO installed (id, title, format, category, path, bytes, sha256, version,"
                   " origin, checksum_source, installed_at) VALUES (?,'t','model','ai_indexes','p',"
                   "1,'s','v','o','c',1)", (item,))
    db.commit()
    assert client.post("/api/ai/start", json={"pin": "9999"}).status_code == 403
    assert actions == []
    assert client.post("/api/ai/start", json={"pin": "1234"}).status_code == 202
    assert actions == ["ai-start"]
    assert client.get("/api/ai/status").json()["model_installed"] is True


def test_ask_refuses_other_sites_and_works_with_an_empty_library(tmp_path):
    client, _ = make_app(tmp_path, [])
    assert client.post("/api/ai/ask", json={"question": "x"},
                       headers={"Origin": "http://evil.example"}).status_code == 403
    lines = client.post("/api/ai/ask", json={"question": "a knot?"}).text.splitlines()
    assert json.loads(lines[0])["mode"] == "empty"


def test_ai_actions_match_the_sudoers_file():
    rules = (acquire.Path(__file__).parents[2] / "systemd/survival-os.sudoers").read_text()
    for name in ("ai-start", "ai-stop"):
        assert " ".join(admin.ACTIONS[name][3:]) in rules


def test_unit_cannot_start_at_boot_and_has_no_outside_network():
    unit = (acquire.Path(__file__).parents[2] / "systemd/survival-llm.service").read_text()
    assert "[Install]" not in unit
    assert "127.0.0.1" in unit and "IPAddressDeny=any" in unit and "MemoryMax=" in unit


def test_tar_unpack_keeps_programs_links_and_refuses_escapes(tmp_path):
    source = tmp_path / "s/top"
    source.mkdir(parents=True)
    program = source / "llama-server"
    program.write_text("x")
    program.chmod(0o755)
    (source / "libfoo.so.1").write_text("y")
    (source / "libfoo.so").symlink_to("libfoo.so.1")
    (source / "other").write_text("z")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, "top")
    target = tmp_path / "out/llama"
    target.parent.mkdir()
    acquire.unpack_tar(archive, target, ["llama-server", "lib*.so*"])
    assert (target / "llama-server").stat().st_mode & 0o100
    assert (target / "libfoo.so").read_text() == "y"
    assert not (target / "other").exists()

    bad = tmp_path / "b.tar.gz"
    with tarfile.open(bad, "w:gz") as bundle:
        link = tarfile.TarInfo("top/lib-evil.so")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        bundle.addfile(link)
    with pytest.raises(tarfile.FilterError):
        acquire.unpack_tar(bad, tmp_path / "out/bad", ["lib*"])


def test_removing_the_ai_leaves_no_folder(tmp_path):
    stores = content.Paths(tmp_path / "state", tmp_path / "catalog")
    stores.ai.mkdir(parents=True)
    (tmp_path / "catalog").mkdir()
    model = stores.ai / "model.gguf"
    model.write_text("x")
    worker = acquire.Worker(stores)
    worker.record(assistant.MODEL_ID, "m", "model", "ai_indexes", model, "s", "v", "o", "c")
    worker.refresh_kiwix = lambda: None
    worker.remove(assistant.MODEL_ID)
    assert not stores.ai.exists()
    assert worker.db.execute("SELECT count(*) FROM installed").fetchone()[0] == 0


def test_question_terms_match_any_word_and_are_safe(tmp_path):
    assert query.question_expression('How do I tie a "bowline"?') == '"tie" OR "bowline"'
    assert query.question_expression("what is the") is None
    assert query.passages(Paths(tmp_path), "bowline") == []


def test_passages_must_share_most_of_the_question(tmp_path):
    library = Paths(tmp_path / "state")
    folder = library.library / "education"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("France has mountains and rivers.")
    (folder / "b.md").write_text("The capital city of France holds many old buildings.")
    Indexer(library, pause_ratio=0).run_once()
    found = query.passages(library, "What is the capital of France?")
    assert [row["text"][:10] for row in found] == ["The capita"]
    assert query.passages(library, "capital of Spain and Portugal") == []
