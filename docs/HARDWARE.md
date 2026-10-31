# Hardware baseline

## Measured on the real device (2026-10-30)

Where this table differs from the owner baseline below, the measurement wins.

| Item | Measured | Differs from baseline |
|---|---|---|
| Display | 7-inch HDMI panel, native **1024x600**, the only mode reported | Baseline said 1280x800 |
| Touch | USB `QDtech MPI5001`, works, no calibration needed | Baseline said not required. Keep it working, but keyboard remains the hard requirement |
| Drive | **Samsung 970 EVO Plus 1 TB** | Baseline said 990 Pro |
| Enclosure | Ugreen CM578, Realtek RTL9210 bridge, `0bda:9210` | Confirms the enclosure, identifies the bridge |
| Link | **USB 2, 480 Mb/s**, `usb-storage`, about 35 MB/s. Owner accepted this for now. USB 3 lines do not connect, cable or plug suspected | Baseline expected 5 Gb/s with UAS |
| Boot | Boots from the drive with no SD or stick. `BOOT_ORDER=0xf461` (SD, NVMe, USB) | Baseline assumed `0xf41`. No change was needed |
| Supply | `max_current` is 5000 mA, `usb_max_current_enable=1`. Not current-limited | Confirms the device-tree value is populated |
| Keyboard | Logitech K270. A trackpad exists but is swapped out, so support both | |
| Power source | Wall power over USB-C, confirmed by the owner 2026-10-30. No solar | Overrides the Rev. 2 brief |

UAS and SMART through this bridge are unverified. Touch is working hardware, so the design should
not break it, even though keyboard navigation is the requirement.

## Owner baseline (2026-10-22)

Confirmed by the project owner on 2026-10-22. Where it differs from the Rev. 2
implementation prompt, this file wins.

| Item | Baseline | Change from Rev. 2 prompt |
|---|---|---|
| Board | Raspberry Pi 5, 8 GB | none |
| Display | Integrated 7-inch, 1280x800 | **Touch input is not required.** Keyboard and trackpad are the primary inputs. |
| Input | Keyboard + trackpad | Full keyboard navigation is a hard requirement. Large targets stay for readability. |
| Storage | 1 TB **Samsung 990 Pro** NVMe in an external **Ugreen CM578** USB enclosure, the only persistent storage | Connects over USB, not PCIe. It appears as `/dev/sdX`. Boot uses USB mass storage. |
| Power | **Wall power via USB-C** | No solar or battery assumptions. Power status shows the input voltage, the negotiated supply current, and throttling history only. |

## Consequences for the design

- **Boot:** the Pi 5 factory `BOOT_ORDER=0xf41` tries SD, then USB mass
  storage, then retries. With no SD card inserted it boots the USB drive, so
  **no EEPROM change should be needed**. Phase 1 inspection confirms the
  actual value.
- **Flashing:** the drive is external, so it can be written directly from the
  Windows PC with Raspberry Pi Imager (with OS customisation). No `dd` from the
  Pi is needed.
- **Throughput:** the enclosure must be on a blue USB 3 port at 5 Gb/s or
  better, using the UAS driver. The inspection warns about USB 2 links and the
  `usb-storage` fallback.
- **USB power budget:** with a supply that negotiates less than 5 A, the Pi 5
  limits all USB ports to 600 mA combined, which may brown out a 990 Pro under
  load. Use a 5 V / 5 A USB-C PD supply (the official 27 W supply). The
  inspection reports the negotiated current
  (`/proc/device-tree/chosen/power/max_current`).
- **SMART:** health is read through the USB bridge with `smartctl` (the
  `smartmontools` package). The inspector reads the enclosure's USB
  vendor:product ID to identify the bridge chip. If plain `smartctl` returns no
  NVMe health, it retries with the matching device type (`sntrealtek`,
  `sntasmedia`, `sntjmicron`). The CM578's bridge chip and its UAS and SMART
  behavior are **unverified** until Phase 1 Step 2 reports the USB ID.
- **Link speed:** the Pi 5's USB 3 ports run at 5 Gb/s, so a 10 Gb/s
  enclosure is expected to report 5000 Mb/s. That is normal.
- **Disconnect risk:** a bumped cable is equivalent to a power loss for the
  root filesystem. The power-loss-safety rules in ARCHITECTURE.md apply.
- **Filesystem:** single ext4 root with reserved blocks lowered to 1%
  (decision 2026-10-22; see STORAGE_PLAN.md).
