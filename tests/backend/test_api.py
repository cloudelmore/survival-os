from fastapi.testclient import TestClient

from survival_os import __version__
from survival_os.main import create_app


def test_health(tmp_path):
    client = TestClient(create_app(tmp_path / "absent"))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_serves_dashboard_when_built(tmp_path):
    (tmp_path / "index.html").write_text("<title>dashboard</title>")
    client = TestClient(create_app(tmp_path))
    assert "dashboard" in client.get("/").text
    assert client.get("/api/health").status_code == 200


def test_static_mount_blocks_traversal(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    client = TestClient(create_app(tmp_path / "www"))
    assert "secret" not in client.get("/../secret.txt").text
