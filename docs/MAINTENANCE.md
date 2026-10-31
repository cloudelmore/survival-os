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
