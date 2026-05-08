"""Network scanner for DLNA/UPnP, AirPlay, and Chromecast devices."""

import asyncio
import logging
import socket
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from zeroconf import ServiceBrowser, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

from device import Device, DeviceType

logger = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_MX = 3
SSDP_ST = "urn:schemas-upnp-org:device:MediaRenderer:1"

SSDP_REQUEST = (
    f"M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    f"MAN: \"ssdp:discover\"\r\n"
    f"MX: {SSDP_MX}\r\n"
    f"ST: {SSDP_ST}\r\n"
    f"\r\n"
)


async def scan_dlna(timeout: float = 5.0) -> list[Device]:
    """Scan for DLNA/UPnP MediaRenderer devices via SSDP."""
    devices = []
    seen = set()

    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _SSDPProtocol(),
        remote_addr=(SSDP_ADDR, SSDP_PORT),
    )

    try:
        sock = transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        transport.sendto(SSDP_REQUEST.encode(), (SSDP_ADDR, SSDP_PORT))
        await asyncio.sleep(timeout)

        for location in protocol.locations:
            if location in seen:
                continue
            seen.add(location)
            device = await _fetch_dlna_description(location)
            if device:
                devices.append(device)
    finally:
        transport.close()

    return devices


class _SSDPProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.locations: list[str] = []
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    def datagram_received(self, data: bytes, addr: tuple):
        try:
            text = data.decode("utf-8", errors="ignore")
            for line in text.split("\r\n"):
                if line.upper().startswith("LOCATION:"):
                    url = line.split(":", 1)[1].strip()
                    self.locations.append(url)
        except Exception as e:
            logger.debug(f"Failed to parse SSDP response from {addr}: {e}")


async def _fetch_dlna_description(location: str) -> Optional[Device]:
    """Fetch and parse UPnP device description XML."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(location, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
                xml_text = await resp.text()
    except Exception as e:
        logger.debug(f"Failed to fetch description from {location}: {e}")
        return None

    try:
        root = ET.fromstring(xml_text)
        ns = {"upnp": "urn:schemas-upnp-org:device-1-0"}

        device_elem = root.find(".//upnp:device", ns)
        if device_elem is None:
            device_elem = root.find(".//device")
        if device_elem is None:
            return None

        def find_text(tag: str) -> str:
            el = device_elem.find(f"upnp:{tag}", ns)
            if el is None:
                el = device_elem.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        name = find_text("friendlyName") or find_text("modelName") or "Unknown Device"
        manufacturer = find_text("manufacturer")
        model = find_text("modelName")
        udn = find_text("UDN")

        control_url = _find_control_url(device_elem, ns)

        parsed = urlparse(location)
        ip = parsed.hostname
        port = parsed.port or 80

        return Device(
            name=name,
            device_type=DeviceType.DLNA,
            ip=ip,
            port=port,
            control_url=control_url,
            manufacturer=manufacturer,
            model=model,
            uid=udn,
        )
    except Exception as e:
        logger.debug(f"Failed to parse description XML from {location}: {e}")
        return None


def _find_control_url(device_elem, ns) -> Optional[str]:
    """Find AVTransport control URL from device description."""
    for service_list in device_elem.findall(".//upnp:serviceList", ns):
        for service in service_list.findall("upnp:service", ns):
            st = service.find("upnp:serviceType", ns)
            if st is not None and "AVTransport" in (st.text or ""):
                scp = service.find("upnp:controlURL", ns)
                if scp is not None and scp.text:
                    return scp.text

    for service_list in device_elem.findall(".//serviceList"):
        for service in service_list.findall("service"):
            st = service.find("serviceType")
            if st is not None and "AVTransport" in (st.text or ""):
                scp = service.find("controlURL")
                if scp is not None and scp.text:
                    return scp.text

    return None


async def _scan_mdns(
    service_type: str,
    device_type: DeviceType,
    model_key: bytes,
    timeout: float,
) -> list[Device]:
    """Generic mDNS scanner for any service type."""
    zc = AsyncZeroconf()
    found = {}

    class Listener:
        def add_service(self, zc_instance, svc_type, name):
            info = zc_instance.get_service_info(svc_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                device = Device(
                    name=name.replace(f".{svc_type}", ""),
                    device_type=device_type,
                    ip=ip,
                    port=info.port,
                    model=info.properties.get(model_key, b"").decode(errors="ignore"),
                )
                found[name] = device

        def remove_service(self, zc_instance, svc_type, name):
            found.pop(name, None)

        def update_service(self, zc_instance, svc_type, name):
            pass

    try:
        browser = ServiceBrowser(zc.zeroconf, service_type, Listener())
        await asyncio.sleep(timeout)
        browser.cancel()
        return list(found.values())
    except Exception as e:
        logger.debug(f"mDNS scan error for {service_type}: {e}")
        return []
    finally:
        await zc.async_close()


async def scan_airplay(timeout: float = 5.0) -> list[Device]:
    """Scan for AirPlay devices via mDNS."""
    return await _scan_mdns("_airplay._tcp.local.", DeviceType.AIRPLAY, b"model", timeout)


async def scan_chromecast(timeout: float = 5.0) -> list[Device]:
    """Scan for Chromecast devices via mDNS."""
    return await _scan_mdns("_googlecast._tcp.local.", DeviceType.CHROMECAST, b"md", timeout)


async def scan_all(timeout: float = 5.0) -> list[Device]:
    """Scan for all supported device types in parallel."""
    results = await asyncio.gather(
        scan_dlna(timeout),
        scan_airplay(timeout),
        scan_chromecast(timeout),
        return_exceptions=True,
    )

    all_devices = []
    for result in results:
        if isinstance(result, list):
            all_devices.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"Scan task failed: {result}")

    return all_devices


async def scan_by_type(device_type: DeviceType, timeout: float = 5.0) -> list[Device]:
    """Scan for a specific device type."""
    scanners = {
        DeviceType.DLNA: scan_dlna,
        DeviceType.AIRPLAY: scan_airplay,
        DeviceType.CHROMECAST: scan_chromecast,
    }
    scanner = scanners.get(device_type)
    if not scanner:
        return []
    return await scanner(timeout)
