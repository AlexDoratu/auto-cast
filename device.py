"""Unified device abstraction for DLNA, AirPlay, and Chromecast devices."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DeviceType(Enum):
    DLNA = "dlna"
    AIRPLAY = "airplay"
    CHROMECAST = "chromecast"


@dataclass
class Device:
    name: str
    device_type: DeviceType
    ip: str
    port: int
    control_url: Optional[str] = None
    manufacturer: str = ""
    model: str = ""
    uid: str = ""
    services: list = None

    def __post_init__(self):
        if self.services is None:
            self.services = []

    @property
    def display_type(self) -> str:
        icons = {
            DeviceType.DLNA: "DLNA",
            DeviceType.AIRPLAY: "AirPlay",
            DeviceType.CHROMECAST: "Cast",
        }
        return icons.get(self.device_type, "Unknown")

    def __str__(self) -> str:
        return f"{self.name} [{self.display_type}] @ {self.ip}:{self.port}"
