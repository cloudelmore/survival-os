from pathlib import Path

from survival_os import telemetry


def fake_root(tmp_path: Path) -> Path:
    (tmp_path / "proc/device-tree/chosen/power").mkdir(parents=True)
    (tmp_path / "sys/class/thermal/thermal_zone0").mkdir(parents=True)
    (tmp_path / "proc/meminfo").write_text("MemTotal: 8000 kB\nMemFree: 1 kB\nMemAvailable: 6000 kB\n")
    (tmp_path / "proc/uptime").write_text("123.45 99.0\n")
    (tmp_path / "proc/stat").write_text("cpu  10 0 10 80 0 0 0 0 0 0\n")
    (tmp_path / "sys/class/thermal/thermal_zone0/temp").write_text("51250\n")
    (tmp_path / "proc/device-tree/chosen/power/max_current").write_bytes(b"\x00\x00\x13\x88")
    return tmp_path


def vcgencmd(outputs):
    def run(command):
        return outputs.get(" ".join(command[1:]))
    return run


def test_reads_real_files(tmp_path):
    root = fake_root(tmp_path)
    assert telemetry.memory(root) == {"total_bytes": 8192000, "available_bytes": 6144000}
    assert telemetry.temperature_c(root) == 51.2
    assert telemetry.uptime_seconds(root) == 123
    assert telemetry.supply_current_ma(root) == 5000


def test_missing_values_are_none_not_guesses(tmp_path):
    result = telemetry.collect(tmp_path, tmp_path / "absent", lambda command: None)
    assert result["memory"] is None
    assert result["temperature_c"] is None
    assert result["storage"] is None
    assert result["power"] == {"input_volts": None, "supply_current_ma": None, "throttling": None}
    assert result["services"]["survival-api"] == "unknown"


def test_no_battery_field_exists(tmp_path):
    result = telemetry.collect(fake_root(tmp_path), tmp_path, lambda command: None)
    assert "battery" not in str(result).lower()


def test_throttling_decodes_now_and_history():
    run = vcgencmd({"get_throttled": "throttled=0x50005"})
    assert telemetry.throttling(run) == {
        "now": ["under_voltage", "throttled"],
        "since_boot": ["under_voltage", "throttled"],
    }


def test_throttling_clear():
    run = vcgencmd({"get_throttled": "throttled=0x0"})
    assert telemetry.throttling(run) == {"now": [], "since_boot": []}


def test_input_voltage():
    run = vcgencmd({"pmic_read_adc EXT5V_V": "EXT5V_V volt(24)=5.13756000V"})
    assert telemetry.input_voltage(run) == 5.14


def test_storage_excludes_reserved_blocks(tmp_path, monkeypatch):
    class Stat:
        f_frsize = 4096
        f_blocks = 1000
        f_bfree = 500
        f_bavail = 400
    monkeypatch.setattr(telemetry.os, "statvfs", lambda path: Stat)
    result = telemetry.storage(tmp_path)
    assert result["usable_bytes"] == 4096 * 900
    assert result["available_bytes"] == 4096 * 400
    assert result["floor_bytes"] == int(4096 * 900 * 0.15)
