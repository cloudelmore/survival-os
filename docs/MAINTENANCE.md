# Maintenance and recovery

## Leave the dashboard

| Route | How | Good for |
|---|---|---|
| Maintenance mode | Press P, or open System Status, choose Maintenance mode, enter the PIN | Normal use |
| Text console | Press Ctrl+Alt+F2. Ctrl+Alt+F1 returns to the dashboard | Any time, no PIN |
| SSH | `ssh survival`, if enabled | From another computer |
| Boot flag | Add `survival.maintenance=1` to `cmdline.txt` on the boot partition, from another computer | The dashboard will not stay up |

After repeated browser crashes, about ten in two minutes, the kiosk stops and a console appears.

## Return to the dashboard

From a console:

```
sudo systemctl start survival-kiosk
```

Or reboot. Maintenance mode does not persist.

## Forgotten PIN

From a console, delete the PIN, then restart the API. The next power action asks for a new one:

```
sudo rm /var/lib/survival-os/admin-pin.json
sudo systemctl restart survival-api
```

## Services

```
systemctl status survival-api survival-web survival-kiosk
journalctl -u survival-kiosk -b
```

## Stop booting to the dashboard

From a source tree on the Pi:

```
sudo installers/install.sh --disable
```

`--uninstall` removes the services, users and `/opt/survival-os`. Settings stay in
`/var/lib/survival-os`.

## Flashing a Meshtastic device with no internet

This has not been tested on a real device.

1. In the Content Manager, install the firmware for your board and the Meshtastic Documentation.
2. Enter maintenance mode and log in. Plug the device into a USB port.
3. Copy the firmware somewhere readable and unpack it:

       sudo cp /var/lib/survival-os/content/firmware/firmware-esp32-*.zip ~/
       unzip ~/firmware-esp32-*.zip -d ~/firmware

4. Search Library Search for "Flashing with the CLI", and follow the page for your board. `esptool`
   and `meshtastic` are installed. Flashing the wrong board's firmware can leave a device unusable
   until it is reflashed.
5. Start the dashboard again with `sudo systemctl start survival-kiosk`.

## Maps and GPX

Install maps from the Content Manager. A map is cut from the newest Protomaps world build, so its size
can differ a little from the listed figure. Old builds disappear within days, so an interrupted install
finishes from the same build if it still exists and starts over if it does not. CHECK FOR UPDATES offers
a newer build. The old map stays in use until the new one is complete, so an update needs room for both.

CONTOURS and PHOTOS appear in Navigation once terrain or aerial photos are installed. Photos are built
on a development machine with `scripts/dev/build-imagery.py`, then copied to `/var/lib/survival-os/maps`.

Navigation shows one street map at a time. MARK CENTER saves the point under the cross, and a name is optional,
so no keyboard is needed. Waypoints and routes are in `/var/lib/survival-os/personal/navigation.db`.

To move GPX files, press USB DRIVE, enter the PIN, then IMPORT a file or SAVE TO USB. Saving writes
`survival-os-navigation.gpx` to the top of the drive, replacing an earlier copy, and returns the drive to
read-only. Press RELEASE DRIVE before pulling it out.

## Using the software shelf

Installed files are in `/var/lib/survival-os/content/software`. To copy one to a USB stick, enter
maintenance mode, log in, and mount the stick yourself. `survival-usb` is read-only, for imports only.
Check the device name with `lsblk` first, because the system disk is also a USB device:

    lsblk
    sudo mount /dev/sdXN /mnt
    sudo cp /var/lib/survival-os/content/software/FILE /mnt/
    sudo umount /mnt

This has not been tested.

## Offline AI

Install "Local AI runtime (llama.cpp)" and "Local AI model (Llama 3.2 3B)" from the Content Manager, then
press START AI on the Offline AI screen and enter the PIN. The model takes about 20 seconds to load, and each
answer about a minute. Press STOP AI when finished, because it holds about 3.5 GB of memory and heats the Pi.

The AI never answers medical, wild food or electrical questions. It shows the sourced passages instead.

Memory caps need `cgroup_enable=memory` in `/boot/firmware/cmdline.txt`. Raspberry Pi OS turns memory
control off by default. Check with `cat /sys/fs/cgroup/cgroup.controllers`, which must list `memory`.

Removing both AI items from the Content Manager stops the model and deletes `/var/lib/survival-os/ai`.
The disabled `survival-llm.service` unit stays, and it cannot start without those files.
