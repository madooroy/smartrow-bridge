#!/usr/bin/env python3
"""Live BLE signal strength (RSSI) of the pulley connection, read from the radio.

"btmgmt conn-info" fails on the Pi's built-in radio with "Invalid Parameters":
besides RSSI it requests the transmit power level, which that controller rejects
for LE links. This tool sends only the standard HCI "Read RSSI" command for the
live connection. Read-only and safe while the bridge runs. Standard library only.

Usage (on the Pi, with the bridge connected to the pulley):
    sudo python3 ~/smartrow-bridge/tools/pulley_rssi.py [--address MAC] [--seconds 30]
"""

from __future__ import annotations

import argparse
import fcntl
import re
import select
import socket
import struct
import sys
import time
from pathlib import Path

HCIGETCONNLIST = 0x800448D4  # _IOR('H', 212, int)
SOL_HCI = 0
HCI_FILTER = 2
HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
OP_READ_RSSI = (0x05 << 10) | 0x0005  # Status Parameters group, Read RSSI
MAX_CONNECTIONS = 10
CONN_INFO_SIZE = 16  # struct hci_conn_info: handle, bdaddr, type, out, state, link_mode


def pinned_address() -> str | None:
    try:
        text = Path("/etc/default/smartrow-bridge").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^SRB_PULLEY_ADDRESS=([0-9A-Fa-f:]{17})\s*$", text, re.M)
    return match.group(1).upper() if match else None


def adapters() -> list[int]:
    root = Path("/sys/class/bluetooth")
    return sorted(int(p.name[3:]) for p in root.iterdir() if re.fullmatch(r"hci\d+", p.name))


def find_connection(address: str) -> tuple[int, int] | None:
    """(adapter index, connection handle) of the live link to address, if any."""
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI) as sock:
        for dev_id in adapters():
            buf = bytearray(4 + MAX_CONNECTIONS * CONN_INFO_SIZE)
            struct.pack_into("<HH", buf, 0, dev_id, MAX_CONNECTIONS)
            try:
                fcntl.ioctl(sock.fileno(), HCIGETCONNLIST, buf)
            except OSError:
                continue  # e.g. the dongle, owned by Bumble
            count = struct.unpack_from("<H", buf, 2)[0]
            for i in range(count):
                handle, raw_addr = struct.unpack_from("<H6s", buf, 4 + i * CONN_INFO_SIZE)
                if ":".join(f"{b:02X}" for b in reversed(raw_addr)) == address:
                    return dev_id, handle
    return None


def open_hci(dev_id: int) -> socket.socket:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
    sock.bind((dev_id,))
    event_mask = (1 << EVT_CMD_COMPLETE) | (1 << EVT_CMD_STATUS)
    sock.setsockopt(SOL_HCI, HCI_FILTER, struct.pack("<IIIH2x", 1 << HCI_EVENT_PKT, event_mask, 0, 0))
    return sock


def read_rssi(sock: socket.socket, handle: int, timeout: float = 1.0) -> int:
    sock.send(struct.pack("<BHBH", HCI_COMMAND_PKT, OP_READ_RSSI, 2, handle))
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        if not select.select([sock], [], [], remaining)[0]:
            break
        pkt = sock.recv(260)
        if len(pkt) < 7 or pkt[0] != HCI_EVENT_PKT:
            continue
        # Command Complete: 04 0E len ncmd opcode(2) status handle(2) rssi
        if pkt[1] == EVT_CMD_COMPLETE and len(pkt) >= 10 and struct.unpack_from("<H", pkt, 4)[0] == OP_READ_RSSI:
            if pkt[6]:
                raise OSError(f"radio returned status 0x{pkt[6]:02X}")
            return struct.unpack_from("<b", pkt, 9)[0]
        # Command Status: 04 0F len status ncmd opcode(2)
        if pkt[1] == EVT_CMD_STATUS and struct.unpack_from("<H", pkt, 5)[0] == OP_READ_RSSI and pkt[3]:
            raise OSError(f"radio rejected Read RSSI (status 0x{pkt[3]:02X})")
    raise TimeoutError("no reply from the radio")


def verdict(rssi: float) -> str:
    if rssi >= -65:
        return "strong"
    if rssi >= -80:
        return "fine"
    if rssi >= -90:
        return "weak - occasional drops possible"
    return "unreliable"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default=pinned_address(), help="pulley MAC (default: SRB_PULLEY_ADDRESS)")
    ap.add_argument("--seconds", type=int, default=30, help="how long to sample, one reading per second")
    args = ap.parse_args()
    if not args.address:
        print("No pulley address: pass --address or set SRB_PULLEY_ADDRESS.", file=sys.stderr)
        return 1
    address = args.address.upper()

    found = find_connection(address)
    if found is None:
        print(f"No live connection to {address}. Is the bridge running and the pulley awake?", file=sys.stderr)
        return 1
    dev_id, handle = found
    print(f"Pulley {address} on hci{dev_id}, connection handle 0x{handle:04X}. Sampling for {args.seconds} s...")

    readings: list[int] = []
    with open_hci(dev_id) as sock:
        try:
            for _ in range(args.seconds):
                started = time.monotonic()
                try:
                    rssi = read_rssi(sock, handle)
                except (OSError, TimeoutError) as exc:
                    print(f"  {time.strftime('%H:%M:%S')}  no reading ({exc})")
                else:
                    readings.append(rssi)
                    bar = "#" * max(0, min(40, (rssi + 100) // 2))
                    print(f"  {time.strftime('%H:%M:%S')}  {rssi:4d} dBm  {bar}")
                time.sleep(max(0.0, 1.0 - (time.monotonic() - started)))
        except KeyboardInterrupt:
            print("  (stopped early)")

    if not readings:
        print("No readings - the radio did not answer Read RSSI.")
        return 1
    avg = sum(readings) / len(readings)
    print(f"\n{len(readings)} readings: min {min(readings)}  avg {avg:.0f}  max {max(readings)} dBm"
          f"  -> {verdict(avg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
