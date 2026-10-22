# Phase 1: hardware inspection, kiosk trial, flash to the USB NVMe

Baseline: [HARDWARE.md](../HARDWARE.md). The 990 Pro is in an external USB
enclosure, the deck runs on wall power over USB-C, and touch is not required.

Steps marked **APPROVAL GATE** must not be done until you have explicitly
decided to do them. No script in this repository performs them automatically.

## Step 1: boot Pi OS Lite from a test SD card

1. **Unplug the USB NVMe enclosure** so nothing can touch it.
2. On Windows, use Raspberry Pi Imager → *Raspberry Pi 5* → *Raspberry Pi OS
   Lite (64-bit)*. Confirm it says Debian 13 / trixie. In OS customisation, set
   the hostname, user, locale, keyboard, timezone, and SSH with public-key
   authentication only (see
   [windows-wsl2-setup.md](../dev/windows-wsl2-setup.md)).
3. Power the Pi from the 5 V / 5 A USB-C supply, boot from the card, and
   confirm SSH from WSL: `ssh <user>@<pi-host>`.

## Step 2: hardware inspection (read-only)

On the Pi, install the SMART tool once (needed to read health data through the
USB bridge): `sudo apt-get install -y smartmontools`.

Plug the USB NVMe enclosure into a **blue USB 3 port**. It is not mounted and
is not written to. Then, from WSL:

```bash
scripts/dev/pi-remote-inspect.sh --sudo <user>@<pi-host>
```

The report lands in `reports/hardware-<timestamp>.json` (git-ignored), with a
printed summary. It covers: model and RAM, OS, display connectors and modes,
keyboard and trackpad detection, the USB disk (model, size, USB link speed,
UAS vs `usb-storage` driver, SMART summary), root filesystem capacity and the
15% floor, bootloader version, decoded `BOOT_ORDER`, EXT5V input voltage,
negotiated supply current, throttling history, network interfaces, and SSH
state.

It never writes to disks, EEPROM, I2C, or config. Paste the **summary and
warnings** into the Phase 1 review. Also note the USB enclosure's make and
model by hand.

## Step 3: kiosk trial on the SD system

On the **Pi's own keyboard**, logged in on tty1:

```bash
git clone https://github.com/cloudelmore/survival-os ~/survival-os
cd ~/survival-os
scripts/pi/kiosk-trial.sh --install   # asks before apt install of cage, labwc, wlr-randr, chromium
scripts/pi/kiosk-trial.sh cage
scripts/pi/kiosk-trial.sh labwc
# panel comes up portrait? e.g.:
scripts/pi/kiosk-trial.sh cage --rotate DSI-1:90
```

For each run, note:
- [ ] Page fills the screen with no browser UI; the viewport is roughly 1280x800 landscape
- [ ] Trackpad: all four corner boxes highlight when clicked
- [ ] Keyboard keys show on the page
- [ ] **Ctrl+Alt+F2** reaches a text console; **Ctrl+Alt+F1** returns
- [ ] **Ctrl+W** closes the kiosk and returns to the shell
- [ ] Peak kiosk PSS and minimum MemAvailable (printed at exit; log in `~/survival-kiosk-trial/`)

Nothing is enabled at boot. The installed packages are the only persistent
change.

## Step 4: write Pi OS Lite to the 990 Pro (APPROVAL GATE)

This **erases the drive**, including the current Ubuntu install, which has
nothing to keep.

1. Shut down the Pi and connect the USB enclosure to the **Windows PC**.
2. In Raspberry Pi Imager, choose *Raspberry Pi 5* → *Raspberry Pi OS Lite
   (64-bit)* → **Storage: the Samsung 990 Pro, about 1 TB**. Check the size
   twice so you don't pick another disk. Apply the same OS customisation as in
   Step 1.
3. Let Imager finish its verify pass. Eject the drive.

## Step 5: first boot from USB

1. Remove the SD card and keep it as the recovery card. Connect the enclosure
   to a blue USB 3 port and power on.
2. The factory `BOOT_ORDER` (`0xf41`: SD, then USB, then retry) boots the USB
   drive when no card is inserted. Pi OS expands the root filesystem on first
   boot.
3. Only if it does not boot **and** Step 2 showed a `BOOT_ORDER` without
   `4` (USB): changing the boot order is an **APPROVAL GATE**:
   `sudo rpi-eeprom-config --edit` from the SD system, set
   `BOOT_ORDER=0xf41`, then reboot.
4. Apply the 1% reserved-block decision (this changes one superblock field and
   is safe on a mounted filesystem):

   ```bash
   findmnt -no SOURCE /          # expect /dev/sda2
   sudo tune2fs -m 1 /dev/sda2
   ```

5. Re-run Step 2. Phase 1 is complete when the root is on the USB disk, the
   link is 5000 Mb/s with UAS, there are no power warnings, and the reserved
   space is about 1%.

## Recovery

- Insert the Step 1 SD card. SD is first in the factory boot order, so it
  boots even with the USB drive attached.
- If the EEPROM is misconfigured, use Raspberry Pi Imager → *Misc utility
  images* → *Bootloader (Pi 5)* to write a card that restores the default
  bootloader.
