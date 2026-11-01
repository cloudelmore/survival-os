"""Read real system telemetry. A value that cannot be read is None, never a guess.

Battery figures are deliberately absent. The device runs on wall power, and the only battery the
OS reports is the wireless keyboard's, which says nothing about the system.
"""

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

FREE_SPACE_FLOOR = 0.15
SERVICES = ("survival-api", "survival-web", "survival-kiosk", "survival-indexer",
            "survival-kiwix")

THROTTLE_FLAGS = {
    0: "under_voltage",
    1: "frequency_capped",
    2: "throttled",
    3: "soft_temperature_limit",
}
THROTTLE_HISTORY_SHIFT = 16

Runner = Callable[[list[str]], str | None]


def run_command(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.stdout else None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def cpu_times(root: Path) -> tuple[int, int] | None:
    text = read_text(root / "proc/stat")
    if not text:
        return None
    fields = [int(v) for v in text.splitlines()[0].split()[1:]]
    idle = fields[3] + fields[4]
    return sum(fields), idle


def cpu_percent(root: Path, interval: float = 0.1) -> float | None:
    first = cpu_times(root)
    time.sleep(interval)
    second = cpu_times(root)
    if not first or not second or second[0] == first[0]:
        return None
    total = second[0] - first[0]
    return round(100 * (total - (second[1] - first[1])) / total, 1)


def memory(root: Path) -> dict[str, int] | None:
    text = read_text(root / "proc/meminfo")
    if not text:
        return None
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) * 1024
    if "MemTotal" not in values or "MemAvailable" not in values:
        return None
    return {"total_bytes": values["MemTotal"], "available_bytes": values["MemAvailable"]}


def temperature_c(root: Path) -> float | None:
    text = read_text(root / "sys/class/thermal/thermal_zone0/temp")
    return round(int(text) / 1000, 1) if text else None


def uptime_seconds(root: Path) -> int | None:
    text = read_text(root / "proc/uptime")
    return int(float(text.split()[0])) if text else None


def storage(path: Path) -> dict[str, int] | None:
    """Apply the STORAGE_PLAN.md formula, which excludes ext4 reserved blocks from usable space."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    usable = st.f_frsize * (st.f_blocks - (st.f_bfree - st.f_bavail))
    available = st.f_frsize * st.f_bavail
    return {
        "usable_bytes": usable,
        "available_bytes": available,
        "used_bytes": usable - available,
        "floor_bytes": int(usable * FREE_SPACE_FLOOR),
    }


def throttling(run: Runner) -> dict[str, list[str]] | None:
    output = run(["vcgencmd", "get_throttled"])
    if not output or "=" not in output:
        return None
    try:
        value = int(output.split("=")[1], 16)
    except ValueError:
        return None
    return {
        "now": [n for bit, n in THROTTLE_FLAGS.items() if value >> bit & 1],
        "since_boot": [
            n for bit, n in THROTTLE_FLAGS.items() if value >> (bit + THROTTLE_HISTORY_SHIFT) & 1
        ],
    }


def input_voltage(run: Runner) -> float | None:
    output = run(["vcgencmd", "pmic_read_adc", "EXT5V_V"])
    if not output or "=" not in output:
        return None
    try:
        return round(float(output.split("=")[1].rstrip("V")), 2)
    except ValueError:
        return None


def supply_current_ma(root: Path) -> int | None:
    try:
        return int.from_bytes((root / "proc/device-tree/chosen/power/max_current").read_bytes())
    except OSError:
        return None


def service_states(run: Runner) -> dict[str, str]:
    return {name: run(["systemctl", "is-active", name]) or "unknown" for name in SERVICES}


def collect(
    root: Path = Path("/"), storage_path: Path = Path("/"), run: Runner = run_command
) -> dict[str, Any]:
    return {
        "cpu_percent": cpu_percent(root),
        "memory": memory(root),
        "temperature_c": temperature_c(root),
        "uptime_seconds": uptime_seconds(root),
        "storage": storage(storage_path),
        "power": {
            "input_volts": input_voltage(run),
            "supply_current_ma": supply_current_ma(root),
            "throttling": throttling(run),
        },
        "services": service_states(run),
    }
