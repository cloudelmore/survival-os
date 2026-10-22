# Hardware baseline

Confirmed by the project owner on 2026-10-22. Where it differs from the Rev. 2
implementation prompt, this file wins.

| Item | Baseline | Change from Rev. 2 prompt |
|---|---|---|
| Board | Raspberry Pi 5, 8 GB | none |
| Display | Integrated 7-inch, 1280x800 | **Touch input is not required.** Keyboard and trackpad are the primary inputs. |
| Input | Keyboard + trackpad | Full keyboard navigation is a hard requirement. Large targets stay for readability. |
| Storage | 1 TB **Samsung 990 Pro** NVMe in an **external USB enclosure**, the only persistent storage | Connects over USB, not PCIe. It appears as `/dev/sdX`. Boot uses USB mass storage. |
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
  `smartmontools` package). Whether the enclosure's bridge chip passes NVMe
  SMART through is unverified until Phase 1 runs.
- **Disconnect risk:** a bumped cable is equivalent to a power loss for the
  root filesystem. The power-loss-safety rules in ARCHITECTURE.md apply.
- **Filesystem:** single ext4 root with reserved blocks lowered to 1%
  (decision 2026-10-22; see STORAGE_PLAN.md).
