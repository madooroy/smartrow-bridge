# smartrow-bridge

Use a **SmartRow** pulley with the **SmartRow app and a fitness app such as Peloton at the same time**.

A Raspberry Pi holds the only Bluetooth connection the pulley allows and re-publishes it as two devices:

- **`SmartRow`** - a byte-for-byte copy of your pulley, for the SmartRow app (force curves and all);
- **`Rower`** - a standard Bluetooth fitness machine (FTMS rower), for Peloton and other apps that support FTMS rowers.

Both apps record the same strokes. Switch the Pi on, pull the handle, open your apps.

```
SmartRow pulley ──BLE──> Pi built-in radio (central, bleak/BlueZ)
                              │ raw notifications, byte for byte
                              ├──────────> "SmartRow" ──> tablet / phone running the SmartRow app
                              │ <── the app's commands forwarded to the pulley ──
                              └─ parse → watts / stroke rate / pace / distance / time
                                           "Rower"   ──> phone / tablet running Peloton (FTMS 0x2AD1)
USB Bluetooth dongle (peripheral, Bumble): two advertising sets, two connections, one GATT server
```

> **Unofficial.** This project is not affiliated with or endorsed by SmartRow, WaterRower, Peloton or
> anyone else. It was worked out from a pulley's Bluetooth traffic and may stop working after a firmware
> or app update. Use it at your own risk.

## Status

Working on the author's setup: SmartRow pulley firmware **V3.10**, Raspberry Pi 4,
TP-Link UB500, SmartRow app on an Android tablet, Peloton app on an iPhone. Cold boot to both apps recording
needs no interaction. Other firmware versions, dongles and apps are untested - reports welcome.

Peloton shows stroke rate, pace and heart rate live, and output (watts, kJ), distance and stroke count in the
workout summary.

## What you need

| Part | Notes |
|---|---|
| Raspberry Pi 4 | Other models with built-in Bluetooth probably work; untested |
| microSD card | Raspberry Pi OS **Lite (64-bit)**, flashed with Raspberry Pi Imager; set up Wi-Fi and SSH there |
| USB Bluetooth dongle | TP-Link **UB500** (Realtek RTL8761BU). It must support LE extended advertising; other Bluetooth 5 dongles may work |
| SmartRow pulley | Firmware V3.10 tested |
| Two devices for the apps | The SmartRow app on one, the fitness app on another (or the same one) |

Why two radios: the built-in radio is the *client* of the pulley, and the dongle is driven directly by
[Bumble](https://github.com/google/bumble) to host the two virtual devices.

## Install

On the Pi, over SSH, with the dongle plugged in:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/madooroy/smartrow-bridge.git ~/smartrow-bridge
cd ~/smartrow-bridge
sudo bash install.sh
```

The installer puts the code in `/opt/smartrow-bridge`, creates the `smartrow-bridge` service (starts on every
boot) and the settings file `/etc/default/smartrow-bridge`. No settings are required.

Then pull the handle to wake the pulley and check:

```bash
sudo bash ~/smartrow-bridge/tools/health_check.sh
```

### Pair the apps (once)

1. **SmartRow app**: forget your pulley, then pair the one that appears as **`SmartRow-<number>`** - the same
   number as before, because the bridge copies the pulley's ID. From then on it reconnects by itself.
2. **Peloton** (or another FTMS app): add the rower called **`Rower`**.

The real pulley no longer shows up in the apps while the bridge is running: the bridge is holding its
connection.

## Everyday use

1. Power on the Pi and pull the handle straight away. The virtual devices appear once the pulley has
   connected, about 20 s after power-on.
2. Open the SmartRow app and/or your fitness app. Row.
3. Shut the Pi down before cutting power (`sudo shutdown -h now`, wait for the green LED to go dark).
   `tools/setup_shutdown_shortcut.sh` sets up a one-tap iOS Shortcut for that.

Updating: `cd ~/smartrow-bridge && git pull && sudo bash install.sh`.

Pulley firmware updates still come from the SmartRow app talking to the real pulley: stop the bridge first
(`sudo systemctl stop smartrow-bridge`), update, start it again.

## Checking and troubleshooting

```bash
sudo bash ~/smartrow-bridge/tools/health_check.sh
```

It is read-only and checks the service, the installed code, the settings, both radios, the last rowing
session (pulley data received → forwarded to the SmartRow app → FTMS sent to the fitness app), warnings, and
the SD card and power supply. It works after a reboot too: the bridge keeps a small record of each session in
`/var/lib/smartrow-bridge/sessions.log`.

| Tool | Use |
|---|---|
| `tools/health_check.sh` | Everything above, in one screen |
| `tools/check_adapters.py` | Lists both radios (MAC, type, USB ID) and scans with each |
| `tools/pulley_rssi.py` | Live signal strength of the pulley link. Aim for −75 dBm or better; move the Pi closer if not |
| `tools/sniff_pulley.py` | Connects to the pulley directly and prints its services and raw packets (stop the bridge first) |
| `tools/setup_shutdown_shortcut.sh` | Lets an iOS Shortcut shut the Pi down, and nothing else |

Live log: `journalctl -u smartrow-bridge -f`. Raspberry Pi OS keeps the log in memory, so save it before
shutting down if you want to share it: `journalctl -u smartrow-bridge -b --no-pager > ~/bridge.log`.

Common problems:

- **Both radios "not powered" / nothing happens** - Bluetooth is soft-blocked on a fresh image:
  `sudo rfkill unblock bluetooth` (the installer does this).
- **The dongle is not found** - `lsusb` should list it; `dmesg | grep -i rtl` should show its firmware loading.
- **Apps cannot see `SmartRow` / `Rower`** - they only appear after the pulley has connected. Pull the handle.
- **The SmartRow app does not reconnect after you replaced the pulley** - it is a different pulley ID; pair
  the new `SmartRow-<number>` once.

## Settings

`/etc/default/smartrow-bridge` - all optional. Restart after a change: `sudo systemctl restart smartrow-bridge`.

| Setting | Default | Meaning |
|---|---|---|
| `SRB_PULLEY_ADDRESS` | empty | Empty = the first device advertising the SmartRow service; a MAC pins one pulley (use where several SmartRows are in range) |
| `SRB_FITNESS_NAME` | `Rower` | The name fitness apps see |
| `SRB_CLONE_NAME` | the pulley's name | The name the SmartRow app sees |
| `SRB_CLONE_ADDRESS`, `SRB_FITNESS_ADDRESS` | derived from the dongle's MAC | Addresses of the two virtual devices: the same on every boot, unique per Pi |
| `SRB_ADVERTISE_PULLEY_ID` | `1` | Test only: `0` advertises the clone without the pulley ID (manufacturer data), as an iPhone would; change `SRB_CLONE_ADDRESS` too so the app sees a new device |
| `SRB_CENTRAL_MAC`, `SRB_PERIPHERAL_MAC` | empty | Empty = built-in radio for the pulley, USB dongle for the apps; set the radios' MACs to pin them |
| `SRB_DRIVE_WITHOUT_TABLET` | `1` | The bridge runs the pulley's start-up handshake itself when the SmartRow app is not connected, so the fitness app works alone |
| `SRB_SESSION_LOG` | `/var/lib/smartrow-bridge/sessions.log` | Session record that survives shutdown; `off` disables |
| `SRB_SNIFF_LOG` | empty | Append every raw pulley packet to this file |
| `SRB_GATT_LOG` | empty | `1` logs every GATT request the apps make to the virtual devices (verbose) |
| `SRB_LOG_LEVEL` | `INFO` | `DEBUG` adds a line per second |

## How it works

| Module | Role |
|---|---|
| `smartrow_bridge/central.py` | Finds and holds the pulley, copies its GATT table, reconnects, keeps writes in order |
| `smartrow_bridge/peripheral.py` | Bumble GATT server: pulley clone + FTMS rower, two advertising sets |
| `smartrow_bridge/protocol.py` | SmartRow record decoding, checksum, V3 KEYLOCK handshake |
| `smartrow_bridge/ftms.py` | FTMS Rower Data (0x2AD1), Feature, Control Point |
| `smartrow_bridge/bridge.py` | Wiring; runs the pulley handshake when the SmartRow app is absent; 1 Hz FTMS; data-flow log |
| `smartrow_bridge/adapters.py` | Picks the two radios, clears rfkill, hands the dongle to Bumble |
| `smartrow_bridge/addresses.py`, `advertising.py`, `session_log.py`, `config.py` | Virtual device addresses, advertising payloads, session record, settings |

- **Pass-through.** Every pulley notification is forwarded to the clone first, unchanged and in order; parsing
  works on a copy. The SmartRow app's writes go back to the pulley unchanged.
- **Who talks to the pulley.** The pulley streams only after an init command, a `$` poll every ~2 s and, on V3
  firmware, a KEYLOCK challenge-response. The SmartRow app does that through the clone. While the app is not
  connected, the bridge does it, so a fitness app works on its own.
- **Stopping.** After you stop, the pulley keeps repeating the last stroke's values; the bridge zeroes the live
  values when the pulley's "stopped" marker arrives or no new stroke comes for 6 s.

Tests (no Bluetooth needed): `python -m unittest discover -s tests -t .` - they replay a real 2½-minute capture
(`captures/sniff2.log`).

### SmartRow protocol notes (firmware V3.10)

Service `0x1234`; `0x1235` write without response; `0x1236` read + notify. The pulley advertises its ID as
manufacturer data under company id `0x1235` (the SmartRow app shows it as `SmartRow-<id>`).

What the SmartRow app needs from a clone (tested with the Android and iOS apps): the iOS app lists a device
only if that manufacturer data is advertised, and after connecting it uses the service only if `0x1234`,
`0x1235` and `0x1236` are declared as 16-bit UUIDs. The Android app accepts a clone without the manufacturer
data (it lists it as plain `SmartRow`) and with either UUID form.

Handshake: write `$\rV@\r` → version reply (`SmartRow 'V3.10'`) → write `#` → `KEYLOCK=…` → answer → records
stream at about 10 per second.

Records are 17 ASCII bytes: type, distance in metres (bytes 1-5, high nibble scrambled on V3), fields, hex
checksum of bytes 0-13 (bytes 14-15), CR.

| Record | Fields |
|---|---|
| `a` | elapsed time `MMMSS` [6:11] |
| `c` | instantaneous W [6:9], average W×10 [9:14] |
| `d` | strokes/min ×10 [6:9], stroke count [9:13] |
| `e` | instantaneous split `mss` [6:9], average split [9:12] |
| `f` | `!` at [11] = rowing stopped |
| `b`, `x`/`y`/`z` | work and stroke length, force curve (passed through, not translated) |

## Optional: faster start-up

Measured on a Pi 4, from power-on to `Rower` visible in a Bluetooth scanner: about 26 s → 19 s. These change
the Pi, not this project; each can be undone by reverting the line (the files are on the SD card's boot
partition, readable from any computer).

| Where | Change | Effect |
|---|---|---|
| `/boot/firmware/config.txt` | `boot_delay=0` and `disable_splash=1` under `[all]`; `camera_auto_detect=0`, `display_auto_detect=0` | No firmware pause, splash or probing |
| `/boot/firmware/config.txt` | `auto_initramfs=0` | Skips loading the initramfs (not needed to boot from the SD card) |
| `/boot/firmware/cmdline.txt` | append ` cloud-init=disabled` to the single line | Removes cloud-init from every boot (~2.4 s). You can then no longer reconfigure the Pi by editing `user-data` on the card until you remove it |
| Bootloader | `NET_INSTALL_AT_POWER_ON=0` via `rpi-eeprom-config` | No USB keyboard wait at power-on |

## Acknowledgements

The SmartRow protocol knowledge here - service and characteristic IDs, the init command, the record layout and
the V3 KEYLOCK handshake - comes from **[qdomyos-zwift](https://github.com/cagnulein/qdomyos-zwift)** by Roberto
Viola, in particular `src/devices/smartrowrower/smartrowrower.cpp`; `keylock_response()` is a Python port of its
`calculateSmartRowV3ChallengeResponse()`. If you want a rower (or bike, treadmill…) bridge that runs on your
phone, with far wider device support, use QZ.

The findings from this project (record checksum, elapsed-time format, stop marker) and a draft "virtual
SmartRow" profile were offered back to QZ; the patches are in `contrib/qz-virtual-smartrow/`.

Built on [bleak](https://github.com/hbldh/bleak) and [Bumble](https://github.com/google/bumble).

## Licence

GPL-3.0 - see [LICENSE](LICENSE). You may use, change and redistribute it; distributed versions must stay
under the same licence.
