#!/usr/bin/env python3
"""Regenerate the software shelf from each project's live release data. Run on the dev machine."""

import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[2] / "content-manifests" / "catalog"
DEBIAN = "https://cdimage.debian.org/debian-cd/current"
RPI = "https://downloads.raspberrypi.org"
UBUNTU = "https://releases.ubuntu.com/26.04"
AGENT = {"User-Agent": "Mozilla/5.0 SURVIVAL-OS-catalog-refresh"}
TODAY = date.today().isoformat()

# id, title, summary, Debian path, file pattern
DEBIAN_IMAGES = [
    ("software-debian-dvd", "Debian DVD 1 (PC, 64-bit)", "Full offline Debian installer for PCs.",
     "amd64/iso-dvd", r"debian-[\d.]+-amd64-DVD-1\.iso"),
    ("software-debian-netinst-arm64", "Debian Network Installer (ARM 64-bit)",
     "Small Debian installer for ARM computers. Needs a network to finish.",
     "arm64/iso-cd", r"debian-[\d.]+-arm64-netinst\.iso"),
]
# id, title, summary, Raspberry Pi image folder
PI_IMAGES = [
    ("software-pi-os-lite", "Raspberry Pi OS Lite (64-bit)", "Rebuild or replace a Pi system.",
     "raspios_lite_arm64"),
    ("software-pi-os-desktop", "Raspberry Pi OS with Desktop (64-bit)",
     "A full desktop for a spare Raspberry Pi.", "raspios_arm64"),
]
# id, title, summary, repository, file pattern
GITHUB_FILES = [
    ("software-ventoy-linux", "Ventoy for Linux", "Makes a USB stick that boots many ISO files.",
     "ventoy/Ventoy", r"ventoy-[\d.]+-linux\.tar\.gz"),
    ("software-ventoy-windows", "Ventoy for Windows", "Makes a USB stick that boots many ISO files.",
     "ventoy/Ventoy", r"ventoy-[\d.]+-windows\.zip"),
    ("software-rufus", "Rufus for Windows", "Writes ISO files to USB sticks.", "pbatard/rufus",
     r"rufus-[\d.]+\.exe"),
    ("software-7zip-windows", "7-Zip for Windows", "Opens archive files.", "ip7z/7zip",
     r"7z\d+-x64\.exe"),
    ("software-7zip-linux", "7-Zip for Linux (ARM 64-bit)", "Opens archive files.", "ip7z/7zip",
     r"7z\d+-linux-arm64\.tar\.xz"),
    ("software-meshtastic-android", "Meshtastic for Android", "Phone app for Meshtastic radios.",
     "meshtastic/Meshtastic-Android", r"androidApp-fdroid-universal-release\.apk"),
    ("software-kiwix-android", "Kiwix for Android", "Reads these ZIM libraries on a phone.",
     "kiwix/kiwix-android", r"v[\d.]+-arm64-v8a-standalone\.apk"),
    ("software-organic-maps", "Organic Maps for Android", "Offline maps on a phone.",
     "organicmaps/organicmaps", r"OrganicMaps-\d+-web-release\.apk"),
]


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def length(url: str) -> int:
    request = urllib.request.Request(url, headers=AGENT, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return int(response.headers["Content-Length"])


def verified(value) -> dict:
    return {"value": value, "status": "verified", "verified_at": TODAY}


def write(key: str, title: str, summary: str, publisher: str, url: str, size: int, sha: str,
          released: str | None) -> None:
    name = url.rsplit("/", 1)[1]
    entry = {
        "id": key, "title": title, "summary": summary, "publisher": publisher,
        "format": "software", "budget_category": "os_apps", "destination": f"software/{name}",
        "source_url": verified(url), "license": {"value": None, "status": "unverified"},
        "publication_date": verified(released) if released
        else {"value": None, "status": "unverified"},
        "size_bytes": verified(size), "sha256": verified(sha),
        "redistribution": {"base_image_allowed": False, "notes": "Downloaded separately."},
    }
    (CATALOG / f"{key}.json").write_text(json.dumps(entry, indent=2) + "\n")
    print(f"{size / 1e9:7.3f} GB  {key}", file=sys.stderr)


def main() -> None:
    for key, title, summary, folder, pattern in DEBIAN_IMAGES:
        base = f"{DEBIAN}/{folder}"
        sums = get(f"{base}/SHA256SUMS").decode()
        sha, name = re.search(rf"^(\w{{64}})\s+({pattern})$", sums, re.MULTILINE).groups()
        write(key, title, summary, "Debian", f"{base}/{name}", length(f"{base}/{name}"), sha, None)
    sums = get(f"{UBUNTU}/SHA256SUMS").decode()
    sha, name = re.search(r"^(\w{64}) \*(ubuntu-26\.04\.\d+-desktop-amd64\.iso)$", sums,
                          re.MULTILINE).groups()
    write("software-ubuntu-desktop", "Ubuntu 26.04 LTS Desktop (PC, 64-bit)",
          "Plain download for PCs. SURVIVAL OS itself does not run on Ubuntu.", "Canonical",
          f"{UBUNTU}/{name}", length(f"{UBUNTU}/{name}"), sha, None)
    for key, title, summary, folder in PI_IMAGES:
        request = urllib.request.Request(f"{RPI}/{folder}_latest", headers=AGENT, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            url, size = response.url, int(response.headers["Content-Length"])
        sha = get(f"{url}.sha256").decode().split()[0]
        write(key, title, summary, "Raspberry Pi", url, size, sha,
              re.search(r"\d{4}-\d{2}-\d{2}", url).group())
    for key, title, summary, repository, pattern in GITHUB_FILES:
        release = json.loads(get(f"https://api.github.com/repos/{repository}/releases/latest"))
        asset = next(item for item in release["assets"] if re.fullmatch(pattern, item["name"]))
        write(key, title, summary, repository.split("/")[0], asset["browser_download_url"],
              asset["size"], asset["digest"].split(":")[1], release["published_at"][:10])


if __name__ == "__main__":
    main()
