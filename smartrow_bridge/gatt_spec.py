"""Plain description of the physical pulley, captured by the central and cloned by the peripheral."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CharSpec:
    uuid: str
    handle: int
    properties: frozenset[str]  # BlueZ/bleak names: "read", "write", "notify", ...
    value: bytes = b""  # cached value for readable characteristics


@dataclass
class ServiceSpec:
    uuid: str
    characteristics: list[CharSpec] = field(default_factory=list)


@dataclass
class PulleySnapshot:
    address: str
    name: str
    manufacturer_data: dict[int, bytes]
    services: list[ServiceSpec]


_BASE_UUID_SUFFIX = "-0000-1000-8000-00805f9b34fb"


def short_uuid(uuid: str) -> int | None:
    """The 16-bit form of a Bluetooth-base UUID ("00001234-0000-1000-...": 0x1234), else None.

    BlueZ always reports the long form. The pulley declares its service and
    characteristics with 16-bit UUIDs, and the clone must do the same.
    """
    uuid = uuid.lower()
    if len(uuid) == 36 and uuid.startswith("0000") and uuid.endswith(_BASE_UUID_SUFFIX):
        return int(uuid[4:8], 16)
    return None
