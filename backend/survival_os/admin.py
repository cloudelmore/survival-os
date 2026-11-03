"""Admin PIN and privileged system actions."""

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
SCRYPT = {"n": 2**14, "r": 8, "p": 1}

# These exact commands are the only ones the service user may run as root. See
# systemd/survival-os.sudoers, which must stay in step with this table.
ACTIONS = {
    "shutdown": ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "poweroff"],
    "reboot": ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "reboot"],
    "content": ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start", "--no-block",
                "survival-content.service"],
    "maintenance": [
        "/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start", "survival-maintenance.target",
    ],
    "ai-start": ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start", "--no-block",
                 "survival-llm.service"],
    "ai-stop": ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "stop", "--no-block",
                "survival-llm.service"],
}


class PinLocked(Exception):
    def __init__(self, seconds: int):
        self.seconds = seconds


class PinStore:
    def __init__(self, path: Path, clock: Callable[[], float] = time.monotonic):
        self.path = path
        self.clock = clock
        self.failures = 0
        self.locked_until = 0.0

    def is_set(self) -> bool:
        return self.path.exists()

    def _hash(self, pin: str, salt: bytes) -> bytes:
        return hashlib.scrypt(pin.encode(), salt=salt, **SCRYPT)

    def set_pin(self, pin: str) -> None:
        salt = secrets.token_bytes(16)
        data = {"salt": salt.hex(), "hash": self._hash(pin, salt).hex()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, self.path)

    def verify(self, pin: str) -> bool:
        remaining = self.locked_until - self.clock()
        if remaining > 0:
            raise PinLocked(int(remaining) + 1)
        data = json.loads(self.path.read_text())
        expected = bytes.fromhex(data["hash"])
        if hmac.compare_digest(self._hash(pin, bytes.fromhex(data["salt"])), expected):
            self.failures = 0
            return True
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            self.failures = 0
            self.locked_until = self.clock() + LOCKOUT_SECONDS
        return False


def run_action(action: str) -> bool:
    result = subprocess.run(ACTIONS[action], capture_output=True, timeout=30)
    return result.returncode == 0
