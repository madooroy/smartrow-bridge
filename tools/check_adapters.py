#!/usr/bin/env python3
"""Inventory and verify the Pi's two Bluetooth adapters (see CLAUDE.md).

Expected:
  * built-in Raspberry Pi radio (UART)       -> central, pulley side
  * TP-Link UB500 USB dongle (Realtek 8761BU) -> peripheral, tablet/iPad side

Bleak has no public "list adapters" call, so the inventory reads BlueZ over
D-Bus with dbus-fast (installed as a bleak dependency) and sysfs for the bus
type. Each adapter is then exercised with a short BleakScanner scan.

Stop the bridge first (sudo systemctl stop smartrow-bridge): while it runs,
Bumble owns the dongle and BlueZ can no longer see it.

Usage: sudo /opt/smartrow-bridge/venv/bin/python tools/check_adapters.py [--scan-seconds 5] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from bleak import BleakScanner
from dbus_fast import BusType
from dbus_fast.aio import MessageBus

SYSFS = Path("/sys/class/bluetooth")
# TP-Link UB500 ships as 2357:0604; some units report the bare Realtek ID.
UB500_USB_IDS = {("2357", "0604"), ("0bda", "8771")}
_HCI_RE = re.compile(r"^hci\d+$")


def sysfs_adapters() -> dict[str, dict]:
    """Adapter name -> bus info straight from the kernel."""
    found: dict[str, dict] = {}
    if not SYSFS.exists():
        return found
    for entry in sorted(SYSFS.iterdir()):
        if not _HCI_RE.match(entry.name):
            continue
        device = (entry / "device").resolve()
        info = {"bus": "usb" if "/usb" in str(device) else "uart", "sysfs_path": str(device), "usb_id": None}
        # Walk up to the USB device node that carries idVendor/idProduct.
        for node in (device, *device.parents):
            vid, pid = node / "idVendor", node / "idProduct"
            if vid.exists() and pid.exists():
                info["usb_id"] = f"{vid.read_text().strip()}:{pid.read_text().strip()}"
                break
        found[entry.name] = info
    return found


async def bluez_adapters() -> dict[str, dict]:
    """Adapter name -> org.bluez.Adapter1 properties."""
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        intro = await bus.introspect("org.bluez", "/")
        manager = bus.get_proxy_object("org.bluez", "/", intro).get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await manager.call_get_managed_objects()
    finally:
        bus.disconnect()

    wanted = ("Address", "AddressType", "Name", "Alias", "Powered", "Modalias")
    adapters: dict[str, dict] = {}
    for path, interfaces in objects.items():
        props = interfaces.get("org.bluez.Adapter1")
        if props:
            adapters[path.rsplit("/", 1)[-1]] = {k: props[k].value for k in wanted if k in props}
    return adapters


async def scan_test(adapter: str, seconds: float) -> tuple[bool, str]:
    try:
        devices = await BleakScanner.discover(timeout=seconds, adapter=adapter)
    except Exception as exc:  # noqa: BLE001 - report any failure as a failed check
        return False, f"scan failed: {exc}"
    smartrow = [d for d in devices if "smartrow" in (d.name or "").lower()]
    note = f"{len(devices)} devices seen"
    if smartrow:
        note += f", SmartRow at {', '.join(d.address for d in smartrow)}"
    return True, note


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan-seconds", type=float, default=5.0)
    ap.add_argument("--json", help="also write the inventory to this file")
    args = ap.parse_args()

    kernel = sysfs_adapters()
    try:
        bluez = await bluez_adapters()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  cannot query BlueZ over D-Bus ({exc}). Is bluetooth.service running?")
        return 1

    problems: list[str] = []
    inventory: dict[str, dict] = {}
    for name in sorted(set(kernel) | set(bluez)):
        entry = {**kernel.get(name, {}), **bluez.get(name, {})}
        usb_id = entry.get("usb_id")
        if "bus" not in entry:
            entry["role"] = "unknown (not in sysfs)"
        elif entry.get("bus") == "uart":
            entry["role"] = "built-in (central / pulley)"
        elif usb_id and tuple(usb_id.split(":")) in UB500_USB_IDS:
            entry["role"] = "TP-Link UB500 (peripheral / apps)"
        else:
            entry["role"] = f"unexpected USB adapter {usb_id}"
            problems.append(f"{name}: USB adapter {usb_id} is not a recognised UB500")
        if name not in bluez:
            problems.append(f"{name}: present in kernel but not in BlueZ (bridge running? firmware missing?)")
        elif not entry.get("Powered"):
            idx = name.removeprefix("hci")
            problems.append(f"{name}: not powered (try: sudo rfkill unblock bluetooth; sudo btmgmt --index {idx} power on)")
        inventory[name] = entry

    builtin = [n for n, e in inventory.items() if e.get("bus") == "uart"]
    dongle = [n for n, e in inventory.items() if e["role"].startswith("TP-Link")]
    if len(builtin) != 1:
        problems.append(f"expected 1 built-in radio, found {len(builtin)} (is dtoverlay=disable-bt set in config.txt?)")
    if len(dongle) != 1:
        problems.append(f"expected 1 UB500 dongle, found {len(dongle)} (check lsusb and dmesg | grep -i rtl)")

    for name, entry in inventory.items():
        if entry.get("Powered"):
            ok, note = await scan_test(name, args.scan_seconds)
            entry["scan"] = note
            if not ok:
                problems.append(f"{name}: {note}")

    print(f"{'Adapter':8} {'MAC':18} {'Bus':5} {'USB ID':10} {'Powered':8} Role / scan")
    for name, e in inventory.items():
        print(f"{name:8} {e.get('Address', '?'):18} {e.get('bus', '?'):5} {e.get('usb_id') or '-':10} "
              f"{str(e.get('Powered', '?')):8} {e['role']}; {e.get('scan', 'not scanned')}")

    if builtin and dongle:
        print("\nSuggested /etc/default/smartrow-bridge MAC pins (hciN can swap between boots):")
        print(f"  SRB_CENTRAL_MAC={inventory[builtin[0]].get('Address')}     # built-in, currently {builtin[0]}")
        print(f"  SRB_PERIPHERAL_MAC={inventory[dongle[0]].get('Address')}  # UB500, currently {dongle[0]}")

    if args.json:
        Path(args.json).write_text(json.dumps(inventory, indent=2, default=str))
        print(f"\nInventory written to {args.json}")

    if problems:
        print("\nFAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nPASS  both adapters present, identified, powered and scanning")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
