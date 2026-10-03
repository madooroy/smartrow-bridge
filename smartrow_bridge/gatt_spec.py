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
