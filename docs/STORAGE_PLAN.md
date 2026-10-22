# Storage plan

All sizes are decimal GB (10^9 bytes) unless marked GiB. The figures below are
**estimates**. They get replaced with measured values from
`scripts/pi/inspect_hardware.py` (`storage.root_capacity`,
`storage.root_ext4_superblock`) once Phase 1 runs on the real NVMe.

## Raw capacity

| Item | Value |
|---|---|
| Typical 1 TB NVMe | 1,000,204,886,016 bytes = 1,000.2 GB = 931.5 GiB |
| Boot partition (FAT32, Pi OS) | 0.5 GiB |
| Drive | Samsung 990 Pro 1 TB in a USB enclosure (exact byte count from Phase 1 inspection) |

## Usable capacity estimates (single ext4 root, Pi OS default layout)

Assumptions: 4 KiB blocks, 256-byte inodes, 1 GiB journal, about 0.06% other
metadata. "Usable" means space a non-root service can ever use, which
excludes ext4 reserved blocks.

| Layout | fs size | Reserved | **Usable** | 15% floor | Room for everything else |
|---|---|---|---|---|---|
| A. Pi OS default (`-i 16384`, 5% reserved) | 982 GB | 50 GB | **932 GB** | 140 GB | 792 GB |
| A′. Same, reserved lowered to 1% (`tune2fs -m 1`) | 982 GB | 10 GB | **972 GB** | 146 GB | 826 GB |
| B. 64 GiB root + data partition (`-i 65536`, 1%) | 67 + 926 GB | 3 + 9 GB | **63 + 916 GB** | two floors | 54 + 779 GB |

Takeaways:

- The 800 GB category caps can never all fill at once under layout A
  (792 GB of room). That matches the spec: caps are ceilings, and the 15% floor
  wins.
- A′ recovers about 40 GB for free. Root keeps 1% (about 10 GB) so logs and
  package upgrades still work on a nearly full disk.
- B adds partitioning complexity and two floors for little gain.
  **Decision (2026-10-22): layout A′, a single ext4 root with 1% reserved
  blocks.** Expected usable is about 972 GB, the floor about 146 GB, leaving
  about 826 GB of room. Applied with `tune2fs -m 1` in Phase 1 Step 5; the
  installer and image builder do the same in Phases 8–9.

## Budget categories (caps from spec §5)

| Category | Cap (GB) | Manifest key |
|---|---:|---|
| OS, applications, system files | 45 | `os_apps` |
| Wikipedia / Kiwix (Wikimedia ZIMs) | 150 | `wikimedia_zim` |
| Maps (all map data) | 85 | `maps` |
| Medical and survival manuals | 110 | `medical_survival` |
| Educational videos (all video) | 120 | `video` |
| AI models and search indexes | 45 | `ai_indexes` |
| Personal files, config, backups | 45 | `personal` |
| Technical engineering | 35 | `engineering` |
| Natural sciences / field guides | 25 | `natural_sciences` |
| Radio communications | 20 | `radio` |
| Mechanical repair | 35 | `mechanical` |
| Navigation / weather / astronomy | 20 | `navigation_weather` |
| Offline education (non-video) | 65 | `education` |
| **Total of ceilings** | **800** | |

Assignment overrides, in order: video goes to `video`, map data goes to
`maps`, and Wikimedia ZIMs go to `wikimedia_zim`. Everything else follows
subject, and the manifest records a one-line reason for any tie-break. Each
entry has exactly one category.

## Enforcement rule (implemented in Phase 5)

```
usable        = f_frsize * (f_blocks - (f_bfree - f_bavail))
floor         = 0.15 * usable
allowed(op)   = f_bavail*f_frsize - peak_bytes(op) >= floor
                and category_used + final_bytes(op) <= category_cap
peak_bytes(op) = download temp + decompression + index growth + snapshot/upgrade
```

The check runs before every operation and again before each phase of a
multi-step operation (download → verify → extract → index). Crossing 80% of the
headroom shows a warning. Operations that would cross the floor are blocked.
