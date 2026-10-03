"""Bind each role to the right physical radio, whatever hciN numbers the kernel handed out.

hciN numbering is not stable across cold boots (the USB dongle can enumerate
before the Pi's UART radio). Resolution order for each role:
  1. an explicit adapter name (SRB_*_ADAPTER=hciN) - only if you really want it;
  2. a MAC pin (SRB_*_MAC) - the controller's burned-in BD address, read straight
     from the kernel with HCIGETDEVINFO, independent of bluetoothd;
  3. the bus - USB dongle = peripheral, built-in UART radio = central.
The result is cross-checked so the two roles can never land on the same chip.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SYSFS = Path("/sys/class/bluetooth")
_HCI_RE = re.compile(r"^hci(\d+)$")

_BTPROTO_HCI = 1
_HCIDEVDOWN = 0x400448CA  # _IOW('H', 202, int)
_HCIGETDEVINFO = 0x800448D3  # _IOR('H', 211, int)
_HCI_DEV_INFO_SIZE = 92  # sizeof(struct hci_dev_info)
_BDADDR_OFFSET = 10  # after dev_id (u16) and name[8]
_FLAGS_OFFSET = 16  # u32 flags after bdaddr[6]
_HCI_UP = 1 << 0  # flags bit: the kernel has the controller open and initialised

READY_TIMEOUT_S = 8.0
_READY_POLL_S = 0.1


@dataclass(frozen=True)
class Adapter:
    name: str
    index: int
    mac: str | None
    usb: bool


def _dev_info(index: int) -> bytearray:
    """struct hci_dev_info for hci<index> via the kernel HCI socket (needs root / CAP_NET_RAW)."""
    buf = bytearray(_HCI_DEV_INFO_SIZE)
    buf[0:2] = index.to_bytes(2, "little")
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI) as sock:
        fcntl.ioctl(sock.fileno(), _HCIGETDEVINFO, buf)
    return buf


def is_up(index: int) -> bool:
    try:
        flags = int.from_bytes(_dev_info(index)[_FLAGS_OFFSET:_FLAGS_OFFSET + 4], "little")
    except OSError:
        return False
    return bool(flags & _HCI_UP)


def read_mac(index: int) -> str | None:
    """Controller BD address, read from the kernel - independent of bluetoothd."""
    try:
        buf = _dev_info(index)
    except OSError as exc:
        log.warning("Could not read MAC of hci%d: %s", index, exc)
        return None
    raw = buf[_BDADDR_OFFSET:_BDADDR_OFFSET + 6]
    if not any(raw):
        return None
    return ":".join(f"{b:02X}" for b in reversed(raw))


def list_adapters() -> list[Adapter]:
    adapters = []
    if not SYSFS.exists():
        return adapters
    for entry in sorted(SYSFS.iterdir()):
        match = _HCI_RE.match(entry.name)
        if match:
            index = int(match.group(1))
            usb = "/usb" in str((entry / "device").resolve())
            adapters.append(Adapter(entry.name, index, read_mac(index), usb))
    return adapters


def _pick(role: str, adapters: list[Adapter], name: str | None, mac: str | None, want_usb: bool) -> Adapter:
    if name:
        for a in adapters:
            if a.name == name:
                return a
        raise RuntimeError(f"{role}: adapter {name} not present")
    if mac:
        for a in adapters:
            if a.mac and a.mac.upper() == mac.upper():
                return a
        raise RuntimeError(f"{role}: no adapter with MAC {mac} (found {[a.mac for a in adapters]})")
    candidates = [a for a in adapters if a.usb == want_usb]
    if not candidates:
        kind = "USB dongle" if want_usb else "built-in radio"
        raise RuntimeError(f"{role}: no {kind} found")
    return candidates[0]


def resolve(
    central: str | None = None,
    peripheral: str | None = None,
    central_mac: str | None = None,
    peripheral_mac: str | None = None,
) -> tuple[str, str]:
    adapters = list_adapters()
    log.info("Bluetooth adapters: %s",
             ", ".join(f"{a.name}={a.mac or '?'} ({'usb' if a.usb else 'built-in'})" for a in adapters) or "none")

    c = _pick("central", adapters, central, central_mac, want_usb=False)
    p = _pick("peripheral", adapters, peripheral, peripheral_mac, want_usb=True)
    if c.name == p.name:
        raise RuntimeError(f"Central and peripheral both resolved to {c.name}")
    if c.usb:
        log.warning("Central %s is a USB adapter - expected the built-in radio", c.name)
    if not p.usb:
        log.warning("Peripheral %s is not a USB adapter - expected the TP-Link UB500", p.name)
    log.info("Central -> %s (%s)   Peripheral -> %s (%s)", c.name, c.mac, p.name, p.mac)
    return c.name, p.name


def index_of(adapter: str) -> int:
    match = _HCI_RE.match(adapter)
    if not match:
        raise ValueError(f"Not an adapter name: {adapter}")
    return int(match.group(1))


def _unblock_rfkill() -> None:
    if shutil.which("rfkill") is None:
        return
    try:
        subprocess.run(["rfkill", "unblock", "bluetooth"], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("rfkill unblock failed: %s", exc)


async def wait_until_ready(names: list[str], timeout: float = READY_TIMEOUT_S) -> None:
    """Wait until bluetoothd has powered every adapter once, then return at once.

    That first power-up is when the kernel loads the UB500's Realtek firmware, so
    the dongle must not be taken from BlueZ before it. Replaces a fixed sleep in the
    service file; after the timeout it carries on and lets the later steps report.
    """
    _unblock_rfkill()
    loop = asyncio.get_running_loop()
    start = loop.time()
    pending = list(names)
    while pending:
        pending = [name for name in pending if not is_up(index_of(name))]
        if not pending:
            break
        if loop.time() - start >= timeout:
            log.warning("%s not powered by BlueZ after %.0f s; continuing anyway", ", ".join(pending), timeout)
            return
        await asyncio.sleep(_READY_POLL_S)
    log.info("Adapters ready after %.1f s", loop.time() - start)


async def prepare_central(adapter: str) -> None:
    """Undo an rfkill soft block and make sure BlueZ has the central powered for bleak.

    Talks to bluetoothd over D-Bus directly; btmgmt hangs when run without a TTY.
    """
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus

    _unblock_rfkill()
    path = f"/org/bluez/{adapter}"
    bus = None
    try:
        bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SYSTEM).connect(), 5)
        intro = await bus.introspect("org.bluez", path)
        props = bus.get_proxy_object("org.bluez", path, intro).get_interface("org.freedesktop.DBus.Properties")
        powered = await props.call_get("org.bluez.Adapter1", "Powered")
        if not powered.value:
            await asyncio.wait_for(props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True)), 10)
            log.info("Powered on %s", adapter)
    except Exception as exc:  # noqa: BLE001 - bleak will report a clearer error if it really is off
        log.warning("Could not power on %s via BlueZ: %s", adapter, exc)
    finally:
        if bus is not None:
            bus.disconnect()


def release_from_bluez(adapter: str) -> None:
    """Bring the adapter down so Bumble can open an HCI user channel on it.

    Uses the kernel HCIDEVDOWN ioctl directly. The kernel loaded the Realtek
    firmware when bluetoothd powered the dongle up at boot; bringing it down
    keeps the firmware loaded.
    """
    _unblock_rfkill()
    try:
        with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI) as sock:
            fcntl.ioctl(sock.fileno(), _HCIDEVDOWN, index_of(adapter))
        log.info("Released %s from BlueZ", adapter)
    except OSError as exc:
        log.warning("Could not bring %s down: %s", adapter, exc)
