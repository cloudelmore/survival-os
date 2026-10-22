# Phase 1: hardware inspection, SD trial, NVMe flash

Run these in order. Steps marked **APPROVAL GATE** must not be done until you
have explicitly decided to do them. No script in this repository performs
them automatically.

## Step 1: boot Pi OS Lite from a test SD card (or USB stick)

1. On Windows, use Raspberry Pi Imager → *Raspberry Pi 5* → *Raspberry Pi OS
   Lite (64-bit)*. Confirm it says Debian 13 / trixie. Set the hostname, user,
   locale and timezone (America/New_York for NC), and SSH with your public
   key (see [windows-wsl2-setup.md](../dev/windows-wsl2-setup.md)).
2. Insert the card and power on. Whether the Pi boots the SD card or the
   existing Ubuntu NVMe depends on the current `BOOT_ORDER`. The factory Pi 5
   default (`0xf41`) has no NVMe entry, so since the deck boots Ubuntu from
   NVMe today, its order was probably changed to try NVMe first. If Ubuntu
   comes up instead of Pi OS:
   - Easiest: temporarily disconnect the NVMe (or its ribbon) and boot from SD.
   - Otherwise, read the current order from Ubuntu without changing anything:
     `rpi-eeprom-config` (or `vcgencmd bootloader_config`), and copy
     `scripts/pi/inspect_hardware.py` over and run it there. Changing the order
     is an **APPROVAL GATE** (Step 5).
3. Confirm SSH from WSL: `ssh <user>@<pi-host>`.

## Step 2: hardware inspection (read-only)

From WSL:

```bash
scripts/dev/pi-remote-inspect.sh <user>@<pi-host>          # normal user
scripts/dev/pi-remote-inspect.sh --sudo <user>@<pi-host>   # + NVMe SMART, ext4 superblock
```

The report lands in `reports/hardware-<timestamp>.json` (git-ignored), and the
script prints a summary. It covers: model and RAM, OS version, display
connectors and modes, touchscreen, keyboard, and trackpad detection, NVMe model
and PCIe link, filesystem capacity and the 15% floor, bootloader version,
`BOOT_ORDER`, EXT5V input voltage, under-voltage and throttling history, power
supply classes (battery telemetry), network interfaces, and SSH state.

It never writes to disks, EEPROM, I2C, or config. Paste the **summary and
warnings** into the Phase 1 review. Check the JSON for anything you consider
private before sharing it; it contains no serial numbers.

Also record by hand (the script cannot know these):
- Exact touchscreen model and how it connects (DSI ribbon or HDMI + USB touch).
- NVMe adapter/HAT model.
- Solar charge controller and battery model, and whether it has any data port
  (USB, serial, I2C, VE.Direct...).

## Step 3: kiosk trial on the SD system

On the **Pi's local keyboard**, logged in on tty1:

```bash
git clone <this repo> ~/survival-os   # or: rsync -a ./ <user>@<pi-host>:survival-os/ from WSL
cd ~/survival-os
scripts/pi/kiosk-trial.sh --install   # asks before apt install of cage, labwc, wlr-randr, chromium
scripts/pi/kiosk-trial.sh cage
scripts/pi/kiosk-trial.sh labwc
# portrait-native panel? e.g.:
scripts/pi/kiosk-trial.sh cage --rotate DSI-1:90
```

For each run, check and note:
- [ ] Page fills the screen with no browser UI; the viewport is roughly 1280x800 landscape
- [ ] All four corner boxes highlight when tapped; the yellow dot sits under the finger
- [ ] Keyboard keys and trackpad movement show up on the page
- [ ] **Ctrl+Alt+F2** reaches a text console; **Ctrl+Alt+F1** returns
- [ ] **Ctrl+W** closes the kiosk and returns to the shell
- [ ] Peak kiosk PSS and minimum MemAvailable (printed at exit; full log in `~/survival-kiosk-trial/`)

Nothing is enabled at boot. The installed packages are the only persistent
change. This is the data the Phase 2 compositor decision is based on.

## Step 4: flash Pi OS Lite to the NVMe (APPROVAL GATE)

This **erases the NVMe** (the current Ubuntu install, which you said has
nothing to keep). Do it only after Steps 1–3 pass.

**Option A (simplest, if the NVMe can be removed):** put it in a USB NVMe
adapter on the Windows PC and write Pi OS Lite with Raspberry Pi Imager, using
the same OS customisation as the SD card.

**Option B (NVMe stays in the deck):** boot from the SD card, then on the Pi:

```bash
lsblk -o NAME,SIZE,MODEL,MOUNTPOINTS          # confirm the NVMe is nvme0n1 and NOT mounted
# Download the same Pi OS Lite image and verify its SHA-256 against the
# value published on raspberrypi.com (verify live; do not trust a copied value):
sha256sum <image>.img.xz
xzcat <image>.img.xz | sudo dd of=/dev/nvme0n1 bs=4M conv=fsync status=progress
sync
```

With Option B, Imager's OS customisation is not applied, so set up the user
and SSH on the NVMe's boot partition before first boot. The exact mechanism
(cloud-init `user-data` vs `firstrun.sh`) **must be checked against the
current trixie image** in this step. Look at the files on the freshly written
boot partition and record the result in STATUS.md.

## Step 5: boot order (APPROVAL GATE)

Only if inspection showed that `BOOT_ORDER` does not already try NVMe first:

```bash
sudo rpi-eeprom-config --edit      # set e.g. BOOT_ORDER=0xf416  (NVMe, then SD, then USB, then retry)
sudo reboot
```

`0xf416` is read right to left: 6 = NVMe, 1 = SD, 4 = USB, f = restart. Leaving
SD in the order keeps an SD recovery card usable. Re-run Step 2 afterwards and
confirm that the root filesystem is on `nvme0n1p2`.

## Recovery

- Keep the Step 1 SD card. With SD in `BOOT_ORDER`, removing the NVMe or
  holding it empty falls back to SD.
- If the EEPROM is misconfigured, Raspberry Pi Imager → *Misc utility images* →
  *Bootloader (Pi 5)* writes an SD card that restores a default bootloader.
