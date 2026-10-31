import stat

import pytest
from fastapi.testclient import TestClient

from survival_os import admin
from survival_os.main import create_app


@pytest.fixture
def actions():
    return []


@pytest.fixture
def client(tmp_path, actions):
    def run(action):
        actions.append(action)
        return True
    app = create_app(
        tmp_path / "absent", tmp_path / "state", lambda: {}, run, actions_enabled=True
    )
    return TestClient(app)


def set_pin(client, pin="1234"):
    assert client.post("/api/admin/pin", json={"pin": pin}).status_code == 204


def test_action_needs_a_pin_to_exist(client, actions):
    response = client.post("/api/system/action", json={"action": "reboot", "pin": "1234"})
    assert response.status_code == 409
    assert actions == []


def test_pin_can_only_be_set_once(client):
    set_pin(client)
    assert client.post("/api/admin/pin", json={"pin": "9999"}).status_code == 409


@pytest.mark.parametrize("pin", ["123", "123456789", "abcd", ""])
def test_bad_pin_formats(client, pin):
    assert client.post("/api/admin/pin", json={"pin": pin}).status_code == 422


def test_pin_file_is_private_and_hashed(tmp_path, client):
    set_pin(client, "4321")
    path = tmp_path / "state" / "admin-pin.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "4321" not in path.read_text()


@pytest.mark.parametrize("action", ["shutdown", "reboot", "maintenance"])
def test_correct_pin_runs_action(client, actions, action):
    set_pin(client)
    response = client.post("/api/system/action", json={"action": action, "pin": "1234"})
    assert response.status_code == 202
    assert actions == [action]


def test_wrong_pin_runs_nothing(client, actions):
    set_pin(client)
    response = client.post("/api/system/action", json={"action": "shutdown", "pin": "0000"})
    assert response.status_code == 403
    assert actions == []


def test_unknown_action_refused(client, actions):
    set_pin(client)
    response = client.post("/api/system/action", json={"action": "rm", "pin": "1234"})
    assert response.status_code == 422
    assert actions == []


def test_lockout_after_failures(tmp_path):
    now = [0.0]
    pins = admin.PinStore(tmp_path / "pin.json", clock=lambda: now[0])
    pins.set_pin("1234")
    for _ in range(admin.MAX_FAILURES):
        assert pins.verify("0000") is False
    with pytest.raises(admin.PinLocked):
        pins.verify("1234")
    now[0] += admin.LOCKOUT_SECONDS + 1
    assert pins.verify("1234") is True


def test_lockout_returns_429(client):
    set_pin(client)
    for _ in range(admin.MAX_FAILURES):
        client.post("/api/system/action", json={"action": "reboot", "pin": "0000"})
    response = client.post("/api/system/action", json={"action": "reboot", "pin": "1234"})
    assert response.status_code == 429


@pytest.mark.parametrize("headers", [
    {"origin": "http://evil.example"},
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},
])
def test_cross_site_requests_refused(client, actions, headers):
    set_pin(client)
    response = client.post(
        "/api/system/action", json={"action": "reboot", "pin": "1234"}, headers=headers
    )
    assert response.status_code == 403
    assert actions == []


def test_same_origin_browser_request_allowed(client, actions):
    set_pin(client)
    response = client.post(
        "/api/system/action",
        json={"action": "reboot", "pin": "1234"},
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == 202


def test_disabled_actions_run_nothing(tmp_path):
    ran = []
    client = TestClient(create_app(
        tmp_path / "absent", tmp_path / "state", lambda: {},
        lambda action: ran.append(action) or True, actions_enabled=False,
    ))
    set_pin(client)
    response = client.post("/api/system/action", json={"action": "shutdown", "pin": "1234"})
    assert response.status_code == 503
    assert ran == []


def test_failed_action_is_reported(tmp_path):
    client = TestClient(create_app(
        tmp_path / "absent", tmp_path / "state", lambda: {}, lambda action: False,
        actions_enabled=True,
    ))
    set_pin(client)
    response = client.post("/api/system/action", json={"action": "reboot", "pin": "1234"})
    assert response.status_code == 500
