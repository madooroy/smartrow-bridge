"""Command-line / environment configuration (env vars come from /etc/default/smartrow-bridge)."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from . import session_log


@dataclass
class Config:
    central_adapter: str | None
    peripheral_adapter: str | None
    central_mac: str | None
    peripheral_mac: str | None
    peripheral_transport: str | None
    pulley_address: str | None
    pulley_name: str
    clone_name: str | None
    clone_address: str | None
    fitness_name: str
    fitness_address: str | None
    drive_without_tablet: bool
    sniff_log: str | None
    session_log: str
    log_level: str


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


def parse(argv: list[str] | None = None) -> Config:
    p = argparse.ArgumentParser(prog="smartrow-bridge", description="SmartRow -> SmartRow app + Peloton (FTMS) BLE bridge")
    p.add_argument("--central-adapter", default=_env("SRB_CENTRAL_ADAPTER"),
                   help="adapter connecting to the pulley, e.g. hci0 (default: built-in radio)")
    p.add_argument("--peripheral-adapter", default=_env("SRB_PERIPHERAL_ADAPTER"),
                   help="adapter hosting the virtual devices, e.g. hci1 (default: USB dongle)")
    p.add_argument("--central-mac", default=_env("SRB_CENTRAL_MAC"),
                   help="bind the central to the radio with this BD address (built-in chip)")
    p.add_argument("--peripheral-mac", default=_env("SRB_PERIPHERAL_MAC"),
                   help="bind the peripheral to the radio with this BD address (TP-Link UB500)")
    p.add_argument("--peripheral-transport", default=_env("SRB_PERIPHERAL_TRANSPORT"),
                   help="Bumble transport override, e.g. 'usb:0' (default: hci-socket:<index>)")
    p.add_argument("--pulley-address", default=_env("SRB_PULLEY_ADDRESS"),
                   help="MAC of the physical pulley (default: first device matching service/name)")
    p.add_argument("--pulley-name", default=_env("SRB_PULLEY_NAME", "SmartRow"),
                   help="name substring used to find the pulley")
    p.add_argument("--clone-name", default=_env("SRB_CLONE_NAME"),
                   help="advertised name of the virtual device (default: the pulley's own name)")
    p.add_argument("--clone-address", default=_env("SRB_CLONE_ADDRESS"),
                   help="static random address of the pulley clone, top two bits set "
                        "(default: derived from the dongle's MAC)")
    p.add_argument("--fitness-name", default=_env("SRB_FITNESS_NAME", "Rower"),
                   help="name Peloton and other FTMS apps see (default: Rower)")
    p.add_argument("--fitness-address", default=_env("SRB_FITNESS_ADDRESS"),
                   help="static random address of the FTMS rower, different from the clone's "
                        "(default: derived from the dongle's MAC)")
    p.add_argument("--no-drive", dest="drive_without_tablet", action="store_false",
                   default=_env("SRB_DRIVE_WITHOUT_TABLET", "1") not in ("0", "false", "no"),
                   help="never send init/poll/KEYLOCK to the pulley; rely on the SmartRow app")
    p.add_argument("--sniff-log", default=_env("SRB_SNIFF_LOG"),
                   help="append every raw pulley packet (hex + ascii) to this file")
    p.add_argument("--session-log", default=_env("SRB_SESSION_LOG", session_log.DEFAULT_PATH),
                   help="milestone record that survives shutdown ('off' to disable)")
    p.add_argument("--log-level", default=_env("SRB_LOG_LEVEL", "INFO"))
    return Config(**vars(p.parse_args(argv)))
