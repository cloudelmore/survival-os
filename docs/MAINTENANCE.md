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

## Using the software shelf

Installed files are in `/var/lib/survival-os/content/software`. To copy one to a USB stick, enter
maintenance mode, log in, and mount the stick yourself. `survival-usb` is read-only, for imports only.
Check the device name with `lsblk` first, because the system disk is also a USB device:

    lsblk
    sudo mount /dev/sdXN /mnt
    sudo cp /var/lib/survival-os/content/software/FILE /mnt/
    sudo umount /mnt

This has not been tested.
