#!/usr/bin/env python3
"""SURVIVAL OS Phase 1 hardware inspection for Raspberry Pi 5.

STRICTLY READ-ONLY. This script never writes to disks, EEPROM, boot
partitions, I2C buses, or system configuration. It only reads /proc,
/sys, /etc, /boot/firmware, and runs informational commands.

Runs with the Python 3 standard library only (Pi OS Lite ships python3).
Running it with sudo adds SMART data and the ext4 superblock; everything
else works as a normal user.

Hardware baseline (docs/HARDWARE.md): the 1 TB Samsung 990 Pro sits in an
external USB enclosure, so it appears as a USB disk (sdX), not as
/sys/class/nvme. Touch input is not required.

Usage:
    python3 inspect_hardware.py                  # human-readable summary
    python3 inspect_hardware.py --json           # JSON report to stdout
    python3 inspect_hardware.py --output r.json  # JSON to file + summary
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 1
FREE_SPACE_FLOOR = 0.15  # Section 5: keep >= 15% of usable capacity free

# Bootloader BOOT_ORDER nibbles (Raspberry Pi 5 bootloader documentation).
BOOT_MODES = {
    "0": "SD card detect",
    "1": "SD card",
    "2": "Network",
    "3": "RPIBOOT",
    "4": "USB mass storage",
    "5": "BCM-USB mass storage",
    "6": "NVMe",
    "7": "HTTP",
    "e": "Stop (error pattern)",
    "f": "Restart loop",
}

# vcgencmd get_throttled bit meanings.
THROTTLE_BITS = {
    0: "Under-voltage detected",
    1: "ARM frequency capped",
    2: "Currently throttled",
    3: "Soft temperature limit active",
    16: "Under-voltage has occurred",
    17: "ARM frequency capping has occurred",
    18: "Throttling has occurred",
    19: "Soft temperature limit has occurred",
}

# Linux input event codes used to classify devices.
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_X = 0x00
INPUT_PROP_POINTER = 0
INPUT_PROP_DIRECT = 1
KEY_A = 30
KEY_Z = 44


@dataclass
class CmdResult:
    available: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[list[str]], CmdResult]


def default_runner(argv: list[str], timeout: float = 15.0) -> CmdResult:
    if shutil.which(argv[0]) is None:
        return CmdResult(available=False)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CmdResult(available=True, returncode=None, stderr=str(exc))
    return CmdResult(True, proc.returncode, proc.stdout, proc.stderr)


class Inspector:
    """Collects facts. `root` and `runner` are injectable for tests."""

    def __init__(self, root: Path = Path("/"), runner: Runner = default_runner):
        self.root = root
        self.run = runner
        self.warnings: list[str] = []

    # -- helpers ---------------------------------------------------------
    def path(self, p: str) -> Path:
        return self.root / p.lstrip("/")

    def read(self, p: str) -> str | None:
        try:
            return self.path(p).read_text(errors="replace").strip("\x00\n ")
        except OSError:
            return None

    def cmd(self, *argv: str) -> CmdResult:
        return self.run(list(argv))

    def cmd_text(self, *argv: str) -> str | None:
        r = self.cmd(*argv)
        if not r.available or r.returncode != 0:
            return None
        return r.stdout.strip()

    # -- sections --------------------------------------------------------
    def platform(self) -> dict:
        model = self.read("/proc/device-tree/model")
        os_release = parse_os_release(self.read("/etc/os-release") or "")
        mem_kib = parse_meminfo(self.read("/proc/meminfo") or "").get("MemTotal")
        revision = None
        for line in (self.read("/proc/cpuinfo") or "").splitlines():
            if line.startswith("Revision"):
                revision = line.split(":", 1)[1].strip()
        info = {
            "model": model,
            "is_pi5": bool(model and "Raspberry Pi 5" in model),
            "board_revision": revision,
            "arch": self.cmd_text("uname", "-m"),
            "kernel": self.cmd_text("uname", "-r"),
            "os_id": os_release.get("ID"),
            "os_pretty_name": os_release.get("PRETTY_NAME"),
            "os_version_codename": os_release.get("VERSION_CODENAME"),
            "mem_total_mib": round(mem_kib / 1024) if mem_kib else None,
        }
        if not info["is_pi5"]:
            self.warnings.append(f"Not detected as a Raspberry Pi 5 (model={model!r}).")
        if info["arch"] and info["arch"] != "aarch64":
            self.warnings.append(f"Architecture is {info['arch']}, expected aarch64.")
        if info["os_version_codename"] and info["os_version_codename"] != "trixie":
            self.warnings.append(
                f"OS codename is {info['os_version_codename']!r}; target is Debian 13 'trixie'."
            )
        return info

    def display(self) -> dict:
        connectors = []
        drm = self.path("/sys/class/drm")
        if drm.is_dir():
            for entry in sorted(drm.iterdir()):
                if not re.match(r"card\d+-", entry.name):
                    continue
                rel = f"/sys/class/drm/{entry.name}"
                modes = (self.read(f"{rel}/modes") or "").split()
                connectors.append(
                    {
                        "name": entry.name,
                        "status": self.read(f"{rel}/status"),
                        "enabled": self.read(f"{rel}/enabled"),
                        "preferred_mode": modes[0] if modes else None,
                        "modes": modes[:10],
                    }
                )
        connected = [c for c in connectors if c["status"] == "connected"]
        for c in connected:
            mode = c["preferred_mode"]
            if mode in ("720x1280", "800x1280"):
                self.warnings.append(
                    f"{c['name']} is natively portrait {mode}; "
                    "the kiosk must rotate the output to landscape."
                )
            elif mode and mode != "1280x800":
                self.warnings.append(
                    f"{c['name']} preferred mode is {mode}, not the expected 1280x800."
                )
        if not connected:
            self.warnings.append("No connected DRM display connector found.")
        config_txt = self.read("/boot/firmware/config.txt") or ""
        overlays = [
            ln.strip()
            for ln in config_txt.splitlines()
            if re.match(r"\s*(dtoverlay|dtparam|display_|hdmi_)", ln)
        ]
        return {"connectors": connectors, "config_txt_display_lines": overlays}

    def input_devices(self) -> list[dict]:
        devices = parse_input_devices(self.read("/proc/bus/input/devices") or "")
        # Touch is optional; keyboard + trackpad are the primary inputs.
        if not any(d["kind"] == "keyboard" for d in devices):
            self.warnings.append("No keyboard input device detected.")
        if not any(d["kind"] in ("touchpad", "pointer") for d in devices):
            self.warnings.append("No trackpad or mouse detected.")
        return devices

    def storage(self) -> dict:
        lsblk = None
        r = self.cmd(
            "lsblk", "-J", "-b", "-o",
            "NAME,SIZE,TYPE,MODEL,TRAN,FSTYPE,FSVER,LABEL,PARTLABEL,MOUNTPOINTS",
        )
        if r.available and r.returncode == 0:
            try:
                lsblk = json.loads(r.stdout)
            except json.JSONDecodeError:
                lsblk = None
        nvme = []
        nvme_cls = self.path("/sys/class/nvme")
        if nvme_cls.is_dir():
            for ctrl in sorted(nvme_cls.iterdir()):
                rel = f"/sys/class/nvme/{ctrl.name}"
                entry = {
                    "controller": ctrl.name,
                    "model": self.read(f"{rel}/model"),
                    "firmware_rev": self.read(f"{rel}/firmware_rev"),
                    "pcie_link_speed": self.read(f"{rel}/device/current_link_speed"),
                    "pcie_link_width": self.read(f"{rel}/device/current_link_width"),
                    "smart": None,
                }
                smart = self.cmd("nvme", "smart-log", "-o", "json", f"/dev/{ctrl.name}")
                if smart.available and smart.returncode == 0:
                    try:
                        entry["smart"] = json.loads(smart.stdout)
                    except json.JSONDecodeError:
                        pass
                nvme.append(entry)
        usb_disks = self.usb_disks(lsblk)
        if not nvme and not usb_disks:
            self.warnings.append("No NVMe controller or USB disk detected.")
        root_dev = None
        for line in (self.read("/proc/mounts") or "").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "/":
                root_dev = {"device": parts[0], "fstype": parts[2]}
        ext4 = None
        if root_dev and root_dev["fstype"] == "ext4":
            # dumpe2fs -h only reads the superblock; needs root for block devices.
            ext4 = parse_dumpe2fs(self.cmd_text("dumpe2fs", "-h", root_dev["device"]) or "")
        return {
            "lsblk": lsblk,
            "nvme": nvme,
            "usb_disks": usb_disks,
            "root_mount": root_dev,
            "root_ext4_superblock": ext4 or None,
            "root_capacity": self.capacity("/"),
        }

    def usb_disks(self, lsblk: dict | None) -> list[dict]:
        disks = []
        for dev in (lsblk or {}).get("blockdevices", []):
            if dev.get("type") != "disk" or dev.get("tran") != "usb":
                continue
            name = dev["name"]
            link = usb_link_info(self.path(f"/sys/block/{name}/device"))
            entry = {
                "name": name,
                "model": (dev.get("model") or "").strip() or None,
                "size_bytes": dev.get("size"),
                "usb_speed_mbps": link["speed_mbps"],
                "driver": link["driver"],
                "smart": None,
            }
            smart = self.cmd("smartctl", "-j", "-a", f"/dev/{name}")
            # smartctl's exit status is a bitmask; parse whatever JSON it gave.
            if smart.available and smart.stdout.strip().startswith("{"):
                try:
                    entry["smart"] = smart_summary(json.loads(smart.stdout))
                except json.JSONDecodeError:
                    pass
            speed = entry["usb_speed_mbps"]
            if speed is not None and speed < 5000:
                self.warnings.append(
                    f"USB disk {name} is linked at {speed} Mb/s (USB 2). "
                    "Use one of the Pi's blue USB 3 ports and a USB 3 cable."
                )
            if entry["driver"] == "usb-storage":
                self.warnings.append(
                    f"USB disk {name} uses usb-storage, not UAS; expect lower throughput."
                )
            disks.append(entry)
        return disks

    def capacity(self, mount: str) -> dict | None:
        try:
            st = os.statvfs(self.path(mount))
        except OSError:
            return None
        return capacity_from_statvfs(
            st.f_frsize, st.f_blocks, st.f_bfree, st.f_bavail
        )

    def power(self) -> dict:
        throttled_raw = self.cmd_text("vcgencmd", "get_throttled")
        throttled = None
        if throttled_raw and "=" in throttled_raw:
            throttled = decode_throttled(int(throttled_raw.split("=", 1)[1], 16))
            if throttled["flags"]:
                self.warnings.append(
                    "Power/thermal flags set: " + "; ".join(throttled["flags"])
                )
        ext5v = None
        adc = self.cmd_text("vcgencmd", "pmic_read_adc", "EXT5V_V")
        if adc:
            m = re.search(r"=([\d.]+)V", adc)
            ext5v = float(m.group(1)) if m else None
        temp = self.cmd_text("vcgencmd", "measure_temp")
        supplies = []
        ps = self.path("/sys/class/power_supply")
        if ps.is_dir():
            for s in sorted(ps.iterdir()):
                rel = f"/sys/class/power_supply/{s.name}"
                supplies.append(
                    {
                        "name": s.name,
                        "type": self.read(f"{rel}/type"),
                        "has_capacity": self.path(f"{rel}/capacity").exists(),
                    }
                )
        batteries = [s for s in supplies if s["type"] == "Battery"]
        dev = self.path("/dev")
        i2c = sorted(p.name for p in dev.glob("i2c-*")) if dev.is_dir() else []
        psu_ma = read_be_u32(self.path("/proc/device-tree/chosen/power/max_current"))
        usb_max = self.cmd_text("vcgencmd", "get_config", "usb_max_current_enable")
        usb_max_enabled = bool(usb_max and usb_max.strip().endswith("=1"))
        if psu_ma is not None and psu_ma < 5000 and not usb_max_enabled:
            self.warnings.append(
                f"Power supply negotiated {psu_ma} mA (< 5 A): the Pi limits all USB "
                "ports to 600 mA combined, which may not be enough for the USB NVMe "
                "enclosure. Use a 5 V / 5 A USB-C PD supply (official 27 W)."
            )
        return {
            "psu_max_current_ma": psu_ma,
            "usb_max_current_enable": usb_max_enabled,
            "throttled": throttled,
            "pmic_ext5v_volts": ext5v,
            "soc_temp": temp,
            "power_supply_class": supplies,
            "battery_telemetry_available": any(b["has_capacity"] for b in batteries),
            "i2c_buses_present": i2c,
            "note": "I2C buses are listed only; they are never probed (probing can write).",
        }

    def firmware(self) -> dict:
        eeprom_status = self.cmd("rpi-eeprom-update")
        cfg = self.cmd_text("rpi-eeprom-config") or self.cmd_text(
            "vcgencmd", "bootloader_config"
        )
        settings = parse_kv(cfg or "")
        boot_order = settings.get("BOOT_ORDER")
        decoded = decode_boot_order(boot_order) if boot_order else None
        if decoded is not None and "USB mass storage" not in decoded:
            self.warnings.append(
                f"BOOT_ORDER {boot_order} does not include USB mass storage, so the "
                "external NVMe cannot boot. Changing it needs your explicit approval "
                "(approval gate)."
            )
        return {
            "bootloader_version": self.cmd_text("vcgencmd", "bootloader_version"),
            "rpi_eeprom_update": (
                eeprom_status.stdout.strip() if eeprom_status.available else None
            ),
            "bootloader_config": settings or None,
            "boot_order_raw": boot_order,
            "boot_order_decoded": decoded,
        }

    def network(self) -> dict:
        ifaces = []
        net = self.path("/sys/class/net")
        if net.is_dir():
            for i in sorted(net.iterdir()):
                rel = f"/sys/class/net/{i.name}"
                ifaces.append(
                    {
                        "name": i.name,
                        "operstate": self.read(f"{rel}/operstate"),
                        "wireless": self.path(f"{rel}/wireless").exists(),
                    }
                )
        return {"interfaces": ifaces}

    def services(self) -> dict:
        running = self.cmd_text(
            "systemctl", "list-units", "--type=service", "--state=running",
            "--no-pager", "--plain", "--no-legend",
        )
        names = [ln.split()[0] for ln in (running or "").splitlines() if ln.strip()]
        ssh = self.cmd("systemctl", "is-enabled", "ssh")
        return {
            "running_services": names,
            "ssh_enabled": ssh.stdout.strip() if ssh.available else None,
            "kiwix_serve_present": shutil.which("kiwix-serve") is not None,
        }

    def collect(self) -> dict:
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "running_as_root": os.geteuid() == 0,
            "platform": self.platform(),
            "display": self.display(),
            "input_devices": self.input_devices(),
            "storage": self.storage(),
            "power": self.power(),
            "firmware": self.firmware(),
            "network": self.network(),
            "services": self.services(),
        }
        report["warnings"] = self.warnings
        return report


# -- pure parsers (unit tested) -------------------------------------------


def parse_os_release(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def parse_meminfo(text: str) -> dict[str, int]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def parse_kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def read_be_u32(path: Path) -> int | None:
    """Device-tree integer properties are big-endian u32."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return int.from_bytes(raw[:4], "big") if len(raw) >= 4 else None


def usb_link_info(device: Path) -> dict:
    """Walk up from /sys/block/sdX/device to the USB interface and device."""
    info = {"speed_mbps": None, "driver": None}
    try:
        node = device.resolve(strict=True)
    except OSError:
        return info
    for d in [node, *node.parents]:
        drv = d / "driver"
        if info["driver"] is None and drv.is_symlink():
            name = Path(os.readlink(drv)).name
            if name in ("uas", "usb-storage"):
                info["driver"] = name
        speed = d / "speed"
        if info["speed_mbps"] is None and speed.is_file():
            try:
                info["speed_mbps"] = int(float(speed.read_text().strip()))
            except ValueError:
                pass
        if info["speed_mbps"] is not None and info["driver"] is not None:
            break
    return info


def smart_summary(data: dict) -> dict:
    health = data.get("nvme_smart_health_information_log") or {}
    return {
        "model": data.get("model_name"),
        "device_type": (data.get("device") or {}).get("type"),
        "passed": (data.get("smart_status") or {}).get("passed"),
        "temperature_c": (data.get("temperature") or {}).get("current"),
        "percentage_used": health.get("percentage_used"),
        "power_on_hours": (data.get("power_on_time") or {}).get("hours"),
        "media_errors": health.get("media_errors"),
    }


def parse_dumpe2fs(text: str) -> dict[str, int]:
    wanted = {
        "Block count": "block_count",
        "Reserved block count": "reserved_block_count",
        "Block size": "block_size",
        "Inode count": "inode_count",
        "Inode size": "inode_size",
        "Journal size": "journal_size",
    }
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if k.strip() in wanted:
            v = v.strip()
            m = re.match(r"(\d+)([KMG]?)", v)
            if m:
                mult = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30}[m.group(2)]
                out[wanted[k.strip()]] = int(m.group(1)) * mult
    return out


def decode_boot_order(value: str) -> list[str]:
    """BOOT_ORDER is read from the least-significant nibble upward."""
    digits = value.lower().removeprefix("0x")
    return [BOOT_MODES.get(d, f"Unknown ({d})") for d in reversed(digits)]


def decode_throttled(value: int) -> dict:
    flags = [msg for bit, msg in THROTTLE_BITS.items() if value & (1 << bit)]
    return {"raw": hex(value), "flags": flags}


def capacity_from_statvfs(frsize: int, blocks: int, bfree: int, bavail: int) -> dict:
    """Usable capacity = what non-root services can ever use.

    ext4 reserved blocks (bfree - bavail) are excluded because SURVIVAL OS
    services do not run as root. The 15% floor is computed on usable size.
    """
    size = frsize * blocks
    reserved = frsize * (bfree - bavail)
    usable = size - reserved
    used = frsize * (blocks - bfree)
    available = frsize * bavail
    floor = int(usable * FREE_SPACE_FLOOR)
    return {
        "fs_size_bytes": size,
        "reserved_bytes": reserved,
        "usable_bytes": usable,
        "used_bytes": used,
        "available_bytes": available,
        "free_floor_bytes": floor,
        "headroom_above_floor_bytes": available - floor,
    }


def _bitmap(hexwords: str) -> int:
    """Kernel prints capability bitmaps as space-separated hex words, MSW first."""
    value = 0
    for word in hexwords.split():
        value = (value << 64) | int(word, 16)
    return value


def parse_input_devices(text: str) -> list[dict]:
    devices = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        name, handlers, caps = None, [], {}
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: "):
                k, v = line[3:].split("=", 1)
                caps[k] = _bitmap(v)
        abs_bits = caps.get("ABS", 0)
        key_bits = caps.get("KEY", 0)
        prop = caps.get("PROP", 0)
        has_mt = bool(abs_bits >> ABS_MT_POSITION_X & 1 and abs_bits >> ABS_MT_POSITION_Y & 1)
        if prop >> INPUT_PROP_DIRECT & 1 and (has_mt or abs_bits >> ABS_X & 1):
            kind = "touchscreen"
        elif prop >> INPUT_PROP_POINTER & 1 and has_mt:
            kind = "touchpad"
        elif all(key_bits >> k & 1 for k in range(KEY_A, KEY_Z + 1)) and any(
            h.startswith("kbd") for h in handlers
        ):
            kind = "keyboard"
        elif any(h.startswith("mouse") for h in handlers):
            kind = "pointer"
        else:
            kind = "other"
        devices.append({"name": name, "kind": kind, "handlers": handlers})
    return devices


# -- output ---------------------------------------------------------------


def gb(n: int | None) -> str:
    return "n/a" if n is None else f"{n / 1e9:,.1f} GB"


def summarize(r: dict) -> str:
    p, s, pw, fw = r["platform"], r["storage"], r["power"], r["firmware"]
    lines = [
        "SURVIVAL OS hardware inspection (read-only)",
        f"  Model:        {p['model']}  (rev {p['board_revision']})",
        f"  OS:           {p['os_pretty_name']}  kernel {p['kernel']}  arch {p['arch']}",
        f"  RAM:          {p['mem_total_mib']} MiB",
    ]
    for c in r["display"]["connectors"]:
        if c["status"] == "connected":
            lines.append(f"  Display:      {c['name']} preferred {c['preferred_mode']}")
    for d in r["input_devices"]:
        if d["kind"] != "other":
            lines.append(f"  Input:        {d['kind']:<11} {d['name']}")
    for n in s["nvme"]:
        lines.append(
            f"  NVMe:         {n['model']} fw {n['firmware_rev']} "
            f"link {n['pcie_link_speed']} x{n['pcie_link_width']}"
        )
    for u in s["usb_disks"]:
        smart = u["smart"] or {}
        lines.append(
            f"  USB disk:     {u['name']} {u['model']} {gb(u['size_bytes'])} "
            f"{u['usb_speed_mbps']} Mb/s {u['driver']} "
            f"SMART passed={smart.get('passed')} used={smart.get('percentage_used')}%"
        )
    cap = s["root_capacity"]
    if cap:
        lines.append(
            f"  Root fs:      size {gb(cap['fs_size_bytes'])}, usable {gb(cap['usable_bytes'])}, "
            f"reserved {gb(cap['reserved_bytes'])}, 15% floor {gb(cap['free_floor_bytes'])}"
        )
    lines.append(f"  Bootloader:   {(fw['bootloader_version'] or 'n/a').splitlines()[0]}")
    lines.append(f"  BOOT_ORDER:   {fw['boot_order_raw']} -> {fw['boot_order_decoded']}")
    lines.append(f"  EXT5V input:  {pw['pmic_ext5v_volts']} V   temp: {pw['soc_temp']}")
    lines.append(
        f"  PSU:          {pw['psu_max_current_ma']} mA negotiated, "
        f"usb_max_current_enable={pw['usb_max_current_enable']}"
    )
    lines.append(f"  Battery telemetry exposed to Linux: {pw['battery_telemetry_available']}")
    lines.append(f"  Throttled:    {pw['throttled']}")
    lines.append(f"  SSH enabled:  {r['services']['ssh_enabled']}")
    if r["warnings"]:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in r["warnings"])
    if not r["running_as_root"]:
        lines.append("(Run with sudo to include SMART health and ext4 superblock data.)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print JSON report to stdout")
    ap.add_argument("--output", type=Path, help="write JSON report to this file")
    args = ap.parse_args(argv)

    report = Inspector().collect()
    text = json.dumps(report, indent=2, sort_keys=False)
    if args.output:
        args.output.write_text(text + "\n")
    if args.json:
        print(text)
    else:
        print(summarize(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
