"""Network scanner for DLNA/UPnP, AirPlay, and Chromecast devices."""

import asyncio
import logging
import socket
import struct
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import psutil
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
    f'MAN: "ssdp:discover"\r\n'
    f"MX: {SSDP_MX}\r\n"
    f"ST: {SSDP_ST}\r\n"
    f"\r\n"
)


def _get_lan_ips() -> list[str]:
    """Return non-loopback, non-VPN IPv4 addresses suitable for SSDP multicast."""
    skip_prefixes = ("127.", "169.254.", "198.18.")
    skip_names_lower = ("loopback", "radmin", "tailscale", "mihomo", "vethernet")
    ips = []
    try:
        for name, addrs in psutil.net_if_addrs().items():
            name_lower = name.lower()
            if any(k in name_lower for k in skip_names_lower):
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith(skip_prefixes):
                    ips.append(addr.address)
    except Exception as e:
        logger.warning(f"psutil failed, falling back to socket: {e}")
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if not ip.startswith(skip_prefixes):
                ips.append(ip)
        except Exception:
            pass

    logger.info(f"LAN IPs for SSDP: {ips}")
    return ips


async def scan_dlna(timeout: float = 5.0) -> list[Device]:
    """Scan for DLNA/UPnP MediaRenderer devices via SSDP."""
    lan_ips = _get_lan_ips()
    if not lan_ips:
        logger.warning("No LAN interfaces found for SSDP scan")
        return []

    all_locations: set[str] = set()

    for ip in lan_ips:
        try:
            locations = await _ssdp_search(ip, timeout)
            all_locations.update(locations)
        except Exception as e:
            logger.debug(f"SSDP scan on {ip} failed: {e}")

    devices = []
    for location in all_locations:
        device = await _fetch_dlna_description(location)
        if device:
            devices.append(device)

    return devices


async def _ssdp_search(local_ip: str, timeout: float) -> list[str]:
    """Send SSDP M-SEARCH from a specific interface and collect response locations."""
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _SSDPProtocol(),
        local_addr=(local_ip, 0),
    )

    try:
        sock = transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            mreq = struct.pack(
                "4s4s",
                socket.inet_aton(SSDP_ADDR),
                socket.inet_aton(local_ip),
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        transport.sendto(SSDP_REQUEST.encode(), (SSDP_ADDR, SSDP_PORT))
        await asyncio.sleep(timeout)
        return protocol.locations
    finally:
        transport.close()


class _SSDPProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.locations: list[str] = []
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

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

        control_url = _absolute_url(location, _find_control_url(device_elem, ns, "AVTransport"))
        rendering_control_url = _absolute_url(location, _find_control_url(device_elem, ns, "RenderingControl"))

        parsed = urlparse(location)
        ip = parsed.hostname
        port = parsed.port or 80

        return Device(
            name=name,
            device_type=DeviceType.DLNA,
            ip=ip,
            port=port,
            control_url=control_url,
            rendering_control_url=rendering_control_url,
            manufacturer=manufacturer,
            model=model,
            uid=udn,
        )
    except Exception as e:
        logger.debug(f"Failed to parse description XML from {location}: {e}")
        return None


def _absolute_url(base_url: str, maybe_relative_url: Optional[str]) -> Optional[str]:
    if not maybe_relative_url:
        return None
    return urljoin(base_url, maybe_relative_url.strip())


def _find_control_url(device_elem, ns, service_name: str = "AVTransport") -> Optional[str]:
    """Find a service control URL from device description."""
    for service_list in device_elem.findall(".//upnp:serviceList", ns):
        for service in service_list.findall("upnp:service", ns):
            st = service.find("upnp:serviceType", ns)
            if st is not None and service_name in (st.text or ""):
                scp = service.find("upnp:controlURL", ns)
                if scp is not None and scp.text:
                    return scp.text

    for service_list in device_elem.findall(".//serviceList"):
        for service in service_list.findall("service"):
            st = service.find("serviceType")
            if st is not None and service_name in (st.text or ""):
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
