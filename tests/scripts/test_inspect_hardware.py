"""Tests for scripts/pi/inspect_hardware.py using a fake sysfs/proc tree."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "inspect_hardware", REPO / "scripts/pi/inspect_hardware.py"
)
ih = importlib.util.module_from_spec(spec)
sys.modules["inspect_hardware"] = ih
spec.loader.exec_module(ih)


def bitmap(*bits: int) -> str:
    """Format bits the way the kernel prints them on a 64-bit system."""
    value = 0
    for b in bits:
        value |= 1 << b
    words = []
    while value:
        words.append(f"{value & (2**64 - 1):x}")
        value >>= 64
    return " ".join(reversed(words)) or "0"


TOUCH = f"""I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="generic ft5x06 (00)"
H: Handlers=event5
B: PROP=2
B: EV=b
B: KEY={bitmap(0x14a)}
B: ABS={bitmap(0, 1, 0x2f, 0x35, 0x36, 0x39)}
"""

KEYBOARD = f"""I: Bus=0003 Vendor=046d Product=c31c Version=0110
N: Name="Logitech USB Keyboard"
H: Handlers=sysrq kbd leds event0
B: PROP=0
B: EV=120013
B: KEY={bitmap(*range(1, 128))}
"""

TOUCHPAD = f"""I: Bus=0003 Vendor=1234 Product=5678 Version=0111
N: Name="Generic Touchpad"
H: Handlers=mouse0 event3
B: PROP=5
B: EV=1b
B: KEY={bitmap(0x110, 0x145, 0x14a)}
B: ABS={bitmap(0, 1, 0x2f, 0x35, 0x36, 0x39)}
"""

MOUSE = """I: Bus=0003 Vendor=0001 Product=0002 Version=0111
N: Name="USB Optical Mouse"
H: Handlers=mouse1 event4
B: PROP=0
B: EV=17
B: KEY=70000 0 0 0 0
"""


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def fake_pi(tmp_path: Path) -> Path:
    write(tmp_path, "/proc/device-tree/model", "Raspberry Pi 5 Model B Rev 1.0\x00")
    write(tmp_path, "/proc/cpuinfo", "processor\t: 0\nRevision\t: d04170\n")
    write(tmp_path, "/proc/meminfo", "MemTotal:        8245632 kB\nMemFree: 1 kB\n")
    write(
        tmp_path,
        "/etc/os-release",
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_CODENAME=trixie\n',
    )
    write(tmp_path, "/proc/bus/input/devices", "\n".join([TOUCH, KEYBOARD, TOUCHPAD, MOUSE]))
    write(tmp_path, "/proc/mounts", "/dev/sda2 / ext4 rw,noatime 0 0\n")
    drm = "/sys/class/drm/card1-DSI-1"
    write(tmp_path, f"{drm}/status", "connected\n")
    write(tmp_path, f"{drm}/enabled", "enabled\n")
    write(tmp_path, f"{drm}/modes", "1280x800\n")
    write(tmp_path, "/sys/class/drm/card1-HDMI-A-1/status", "disconnected\n")
    write(tmp_path, "/sys/class/drm/version", "drm 1.1.0\n")
    nv = "/sys/class/nvme/nvme0"
    write(tmp_path, f"{nv}/model", "Example 1TB NVMe\n")
    write(tmp_path, f"{nv}/firmware_rev", "1.0\n")
    write(tmp_path, f"{nv}/device/current_link_speed", "8.0 GT/s PCIe\n")
    write(tmp_path, f"{nv}/device/current_link_width", "1\n")
    write(tmp_path, "/sys/class/net/eth0/operstate", "up\n")
    write(tmp_path, "/sys/class/net/wlan0/operstate", "down\n")
    (tmp_path / "sys/class/net/wlan0/wireless").mkdir()
    write(tmp_path, "/sys/class/power_supply/usb/type", "USB\n")
    # Samsung 990 Pro in a USB 3 enclosure: sda -> SCSI device under a UAS interface
    usbdev = tmp_path / "sys/devices/platform/axi/1000120000.pcie/xhci-hcd.1/usb4/4-1"
    scsi = usbdev / "4-1:1.0/host0/target0:0:0/0:0:0:0"
    scsi.mkdir(parents=True)
    write(tmp_path, str(usbdev.relative_to(tmp_path) / "speed"), "5000\n")
    write(tmp_path, str(usbdev.relative_to(tmp_path) / "idVendor"), "0bda\n")
    write(tmp_path, str(usbdev.relative_to(tmp_path) / "idProduct"), "9210\n")
    write(tmp_path, str(usbdev.relative_to(tmp_path) / "product"), "USB 10Gbps Device\n")
    drivers = tmp_path / "sys/bus/usb/drivers/uas"
    drivers.mkdir(parents=True)
    (usbdev / "4-1:1.0/driver").symlink_to(drivers)
    (tmp_path / "sys/block/sda").mkdir(parents=True)
    (tmp_path / "sys/block/sda/device").symlink_to(scsi)
    # 5 A PD supply negotiated (device-tree big-endian u32, mA)
    dt_power = tmp_path / "proc/device-tree/chosen/power"
    dt_power.mkdir(parents=True)
    (dt_power / "max_current").write_bytes((5000).to_bytes(4, "big"))
    write(tmp_path, "/boot/firmware/config.txt", "dtparam=pciex1\ndtoverlay=vc4-kms-v3d\narm_64bit=1\n")
    return tmp_path


def fake_runner(overrides: dict[str, ih.CmdResult] | None = None):
    canned = {
        "uname -m": ih.CmdResult(True, 0, "aarch64\n"),
        "uname -r": ih.CmdResult(True, 0, "6.12.47+rpt-rpi-2712\n"),
        "vcgencmd get_throttled": ih.CmdResult(True, 0, "throttled=0x50000\n"),
        "vcgencmd pmic_read_adc EXT5V_V": ih.CmdResult(True, 0, "EXT5V_V volt(24)=5.13024000V\n"),
        "vcgencmd measure_temp": ih.CmdResult(True, 0, "temp=48.3'C\n"),
        "vcgencmd bootloader_version": ih.CmdResult(True, 0, "2025/05/08 15:13:17\nversion abc\n"),
        "rpi-eeprom-update": ih.CmdResult(True, 0, "BOOTLOADER: up to date\n"),
        "rpi-eeprom-config": ih.CmdResult(
            True, 0, "[all]\nBOOT_UART=1\nBOOT_ORDER=0xf416\nPCIE_PROBE=1\n"
        ),
        "systemctl is-enabled ssh": ih.CmdResult(True, 0, "enabled\n"),
        "vcgencmd get_config usb_max_current_enable": ih.CmdResult(
            True, 0, "usb_max_current_enable=0\n"
        ),
        "lsblk -J -b -o NAME,SIZE,TYPE,MODEL,TRAN,FSTYPE,FSVER,LABEL,PARTLABEL,MOUNTPOINTS": ih.CmdResult(
            True, 0, json.dumps({"blockdevices": [
                {"name": "sda", "size": 1000204886016, "type": "disk",
                 "model": "Samsung SSD 990 PRO 1TB", "tran": "usb", "children": [
                     {"name": "sda1", "type": "part", "fstype": "vfat"},
                     {"name": "sda2", "type": "part", "fstype": "ext4"}]},
                {"name": "mmcblk0", "size": 31914983424, "type": "disk", "tran": None},
            ]}),
        ),
        # smartctl exits non-zero (bitmask) even when it returns data
        "smartctl -j -a /dev/sda": ih.CmdResult(True, 4, json.dumps({
            "model_name": "Samsung SSD 990 PRO 1TB",
            "device": {"type": "sntrealtek"},
            "smart_status": {"passed": True},
            "temperature": {"current": 38},
            "power_on_time": {"hours": 120},
            "nvme_smart_health_information_log": {"percentage_used": 1, "media_errors": 0},
        })),
    }
    canned.update(overrides or {})

    def run(argv):
        return canned.get(" ".join(argv), ih.CmdResult(available=False))

    return run


def test_full_report_on_fake_pi(fake_pi):
    report = ih.Inspector(root=fake_pi, runner=fake_runner()).collect()
    json.dumps(report)  # must be serializable
    p = report["platform"]
    assert p["is_pi5"] and p["arch"] == "aarch64" and p["mem_total_mib"] == 8052
    assert p["os_version_codename"] == "trixie"
    kinds = {d["name"]: d["kind"] for d in report["input_devices"]}
    assert kinds == {
        "generic ft5x06 (00)": "touchscreen",
        "Logitech USB Keyboard": "keyboard",
        "Generic Touchpad": "touchpad",
        "USB Optical Mouse": "pointer",
    }
    assert report["display"]["connectors"][0]["name"] == "card1-DSI-1"
    assert report["storage"]["nvme"][0]["pcie_link_width"] == "1"
    usb = report["storage"]["usb_disks"]
    assert len(usb) == 1 and usb[0]["name"] == "sda"
    assert usb[0]["model"] == "Samsung SSD 990 PRO 1TB"
    assert usb[0]["usb_speed_mbps"] == 5000 and usb[0]["driver"] == "uas"
    assert usb[0]["smart"]["passed"] is True and usb[0]["smart"]["percentage_used"] == 1
    assert usb[0]["usb_id"] == "0bda:9210" and usb[0]["bridge_chip"] == "Realtek RTL9210"
    assert usb[0]["smart"]["smartctl_args"] == ["-j", "-a"]
    assert report["power"]["psu_max_current_ma"] == 5000
    assert not any("USB" in w or "Power supply" in w for w in report["warnings"])
    assert report["firmware"]["boot_order_decoded"] == [
        "NVMe", "SD card", "USB mass storage", "Restart loop",
    ]
    assert report["power"]["pmic_ext5v_volts"] == pytest.approx(5.13024)
    assert report["power"]["battery_telemetry_available"] is False
    # 0x50000 = under-voltage occurred + throttling occurred -> one warning
    assert any("Under-voltage has occurred" in w for w in report["warnings"])
    assert not any("keyboard" in w or "trackpad" in w for w in report["warnings"])
    assert "dtparam=pciex1" in report["display"]["config_txt_display_lines"]


def test_portrait_display_and_missing_usb_boot_warn(fake_pi):
    write(fake_pi, "/sys/class/drm/card1-DSI-1/modes", "720x1280\n")
    runner = fake_runner(
        {"rpi-eeprom-config": ih.CmdResult(True, 0, "BOOT_ORDER=0xf61\n")}
    )
    w = ih.Inspector(root=fake_pi, runner=runner).collect()["warnings"]
    assert any("portrait 720x1280" in x for x in w)
    assert any("does not include USB mass storage" in x and "approval" in x for x in w)


def test_default_boot_order_is_fine_for_usb_boot(fake_pi):
    runner = fake_runner({"rpi-eeprom-config": ih.CmdResult(True, 0, "BOOT_ORDER=0xf41\n")})
    w = ih.Inspector(root=fake_pi, runner=runner).collect()["warnings"]
    assert not any("BOOT_ORDER" in x for x in w)


def test_usb2_link_weak_psu_and_no_touch_is_ok(fake_pi):
    usbdev = next(fake_pi.glob("sys/devices/**/usb4/4-1"))
    (usbdev / "speed").write_text("480\n")
    (fake_pi / "proc/device-tree/chosen/power/max_current").write_bytes((3000).to_bytes(4, "big"))
    devices = (fake_pi / "proc/bus/input/devices").read_text()
    (fake_pi / "proc/bus/input/devices").write_text(devices.replace("PROP=2", "PROP=0"))
    report = ih.Inspector(root=fake_pi, runner=fake_runner()).collect()
    w = report["warnings"]
    assert any("480 Mb/s (USB 2)" in x for x in w)
    assert any("600 mA" in x for x in w)
    assert "touchscreen" not in {d["kind"] for d in report["input_devices"]}
    assert not any("touch" in x.lower() for x in w)


def test_tolerates_missing_everything(tmp_path):
    report = ih.Inspector(root=tmp_path, runner=lambda argv: ih.CmdResult(False)).collect()
    json.dumps(report)
    assert report["platform"]["is_pi5"] is False
    assert report["storage"]["nvme"] == []
    assert report["firmware"]["boot_order_decoded"] is None
    assert any("Not detected as a Raspberry Pi 5" in w for w in report["warnings"])


def test_runs_on_real_host_without_crashing(capsys):
    assert ih.main([]) == 0
    assert "SURVIVAL OS hardware inspection" in capsys.readouterr().out
    assert ih.main(["--json"]) == 0
    json.loads(capsys.readouterr().out)


def test_capacity_math_excludes_reserved_blocks():
    # 4 KiB blocks, 1000 blocks total, 600 free, 550 available to non-root
    c = ih.capacity_from_statvfs(4096, 1000, 600, 550)
    assert c["fs_size_bytes"] == 4096 * 1000
    assert c["reserved_bytes"] == 4096 * 50
    assert c["usable_bytes"] == 4096 * 950
    assert c["used_bytes"] == 4096 * 400
    assert c["free_floor_bytes"] == int(4096 * 950 * 0.15)
    assert c["headroom_above_floor_bytes"] == 4096 * 550 - int(4096 * 950 * 0.15)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0xf416", ["NVMe", "SD card", "USB mass storage", "Restart loop"]),
        ("0xf41", ["SD card", "USB mass storage", "Restart loop"]),
        ("f461", ["SD card", "NVMe", "USB mass storage", "Restart loop"]),
    ],
)
def test_decode_boot_order(value, expected):
    assert ih.decode_boot_order(value) == expected


def test_parse_dumpe2fs():
    text = "Block count:              244071424\nReserved block count:     12203571\n" \
           "Block size:               4096\nInode size:\t          256\nJournal size:             1024M\n"
    assert ih.parse_dumpe2fs(text) == {
        "block_count": 244071424, "reserved_block_count": 12203571,
        "block_size": 4096, "inode_size": 256, "journal_size": 2**30,
    }


def test_decode_throttled():
    assert ih.decode_throttled(0)["flags"] == []
    assert ih.decode_throttled(0x1)["flags"] == ["Under-voltage detected"]


def test_script_is_read_only_by_construction():
    """Guard against regressions: no writes, no privileged mutating tools."""
    src = (REPO / "scripts/pi/inspect_hardware.py").read_text()
    for forbidden in ("i2cdetect", "i2cset", "dd ", "mkfs", "parted", "sfdisk",
                      "rpi-eeprom-config --apply", "rpi-eeprom-config -a",
                      "rpi-eeprom-update -a", "tune2fs", "wipefs"):
        assert forbidden not in src
    # The only write is the user-requested --output report file.
    assert src.count("write_text(") == 1


def test_smart_falls_back_to_bridge_device_type(fake_pi):
    """Auto-detect gives no NVMe health; the RTL9210 device type does."""
    nvme_json = fake_runner()(["smartctl", "-j", "-a", "/dev/sda"]).stdout
    runner = fake_runner({
        "smartctl -j -a /dev/sda": ih.CmdResult(True, 1, json.dumps(
            {"smart_status": {}, "device": {"type": "scsi"}})),
        "smartctl -j -a -d sntrealtek /dev/sda": ih.CmdResult(True, 0, nvme_json),
    })
    usb = ih.Inspector(root=fake_pi, runner=runner).collect()["storage"]["usb_disks"][0]
    assert usb["smart"]["percentage_used"] == 1
    assert usb["smart"]["smartctl_args"] == ["-j", "-a", "-d", "sntrealtek"]
