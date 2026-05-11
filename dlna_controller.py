"""DLNA/UPnP renderer control via SOAP."""

import html
import logging
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

import aiohttp

from device import Device, DeviceType

logger = logging.getLogger(__name__)

AVTRANSPORT_NS = "urn:schemas-upnp-org:service:AVTransport:1"
RENDERINGCONTROL_NS = "urn:schemas-upnp-org:service:RenderingControl:1"

DLNA_PORTS = [49152, 80, 7000, 8008, 8009, 9090, 60929]


async def discover_dlna(ip: str) -> Device | None:
    """Probe common ports for a DLNA MediaRenderer on the given IP."""
    async with aiohttp.ClientSession() as session:
        for port in DLNA_PORTS:
            for path in ["/description.xml", "/rootdesc.xml", "/"]:
                url = f"http://{ip}:{port}{path}"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                        if resp.status != 200:
                            continue
                        text = await resp.text()
                        if "MediaRenderer" not in text:
                            continue
                        root = ET.fromstring(text)
                        ns = {"upnp": "urn:schemas-upnp-org:device-1-0"}
                        name_el = root.find(".//upnp:friendlyName", ns) or root.find(".//friendlyName")
                        name = name_el.text.strip() if name_el is not None and name_el.text else ip
                        ctrl = _find_control_url_xml(root, ns, "AVTransport")
                        rendering_ctrl = _find_control_url_xml(root, ns, "RenderingControl")
                        if not ctrl:
                            continue
                        return Device(
                            name=name,
                            device_type=DeviceType.DLNA,
                            ip=ip,
                            port=port,
                            control_url=ctrl,
                            rendering_control_url=rendering_ctrl,
                        )
                except Exception:
                    continue
    return None


def _find_control_url_xml(root, ns, service_name: str = "AVTransport") -> str | None:
    """Find a service control URL from parsed XML root."""
    for svc in root.iter():
        tag = svc.tag.split("}")[-1] if "}" in svc.tag else svc.tag
        if tag == "service":
            svc_type = ""
            ctrl_url = ""
            for child in svc:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "serviceType":
                    svc_type = child.text or ""
                elif ctag == "controlURL":
                    ctrl_url = child.text or ""
            if service_name in svc_type and ctrl_url:
                return ctrl_url
    return None


async def play(device: Device, media_url: str, content_type: str = "video/mp4"):
    """Set media URI and start playback on a DLNA renderer."""
    control_url = _get_control_url(device)

    await _soap_action(
        device, control_url, AVTRANSPORT_NS, "Stop",
        {"InstanceID": "0"},
    )

    await _soap_action(
        device, control_url, AVTRANSPORT_NS, "SetAVTransportURI",
        {
            "InstanceID": "0",
            "CurrentURI": media_url,
            "CurrentURIMetaData": _build_didl_lite(media_url, content_type),
        },
    )

    await _soap_action(
        device, control_url, AVTRANSPORT_NS, "Play",
        {"InstanceID": "0", "Speed": "1"},
    )
    logger.info(f"Playing on {device.name}: {media_url}")


async def stop(device: Device):
    """Stop playback."""
    control_url = _get_control_url(device)
    await _soap_action(
        device, control_url, AVTRANSPORT_NS, "Stop",
        {"InstanceID": "0"},
    )
    logger.info(f"Stopped on {device.name}")


async def pause(device: Device):
    """Pause playback."""
    control_url = _get_control_url(device)
    await _soap_action(
        device, control_url, AVTRANSPORT_NS, "Pause",
        {"InstanceID": "0"},
    )
    logger.info(f"Paused on {device.name}")


async def set_volume(device: Device, volume: int):
    """Set volume (0-100)."""
    if not device.rendering_control_url:
        discovered = await discover_dlna(device.ip)
        if discovered and discovered.rendering_control_url:
            device.rendering_control_url = discovered.rendering_control_url
            device.port = discovered.port
    control_url = _get_rendering_control_url(device)
    result = await _soap_action(
        device, control_url, RENDERINGCONTROL_NS, "SetVolume",
        {
            "InstanceID": "0",
            "Channel": "Master",
            "DesiredVolume": str(max(0, min(100, volume))),
        },
    )
    if result is None:
        raise RuntimeError(f"Failed to set volume on {device.name}")
    logger.info(f"Volume set to {volume} on {device.name}")


async def get_transport_info(device: Device) -> dict:
    """Get current transport state."""
    control_url = _get_control_url(device)
    result = await _soap_action(
        device, control_url, AVTRANSPORT_NS, "GetTransportInfo",
        {"InstanceID": "0"},
    )
    return result or {}


def _get_control_url(device: Device) -> str:
    if device.control_url:
        if device.control_url.startswith("http"):
            return device.control_url
        path = device.control_url if device.control_url.startswith("/") else f"/{device.control_url}"
        return f"http://{device.ip}:{device.port}{path}"
    return f"http://{device.ip}:{device.port}/AVTransport/control"


def _get_rendering_control_url(device: Device) -> str:
    base = f"http://{device.ip}:{device.port}"
    control_url = device.rendering_control_url or _guess_rendering_control_url(device.control_url)
    if control_url:
        if control_url.startswith("http"):
            return control_url
        path = control_url if control_url.startswith("/") else f"/{control_url}"
        return f"{base}{path}"
    return f"{base}/RenderingControl/control"


def _guess_rendering_control_url(control_url: str | None) -> str | None:
    if not control_url:
        return None
    return control_url.replace("AVTransport", "RenderingControl")


def _build_didl_lite(media_url: str, content_type: str) -> str:
    """Build DIDL-Lite metadata for SetAVTransportURI."""
    escaped_url = html.escape(media_url, quote=True)
    escaped_type = html.escape(content_type, quote=True)
    title = html.escape(_media_title(media_url), quote=False)
    upnp_class = _upnp_class(content_type)
    protocol_info = f"http-get:*:{escaped_type}:*"

    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="0" restricted="1">'
        f'<dc:title>{title}</dc:title>'
        f'<upnp:class>{upnp_class}</upnp:class>'
        f'<res protocolInfo="{protocol_info}">{escaped_url}</res>'
        '</item>'
        '</DIDL-Lite>'
    )


def _media_title(media_url: str) -> str:
    path = urlparse(media_url).path
    name = unquote(path.rsplit("/", 1)[-1])
    return name or "Auto-Cast Stream"


def _upnp_class(content_type: str) -> str:
    if content_type.startswith("audio/"):
        return "object.item.audioItem.musicTrack"
    if content_type.startswith("image/"):
        return "object.item.imageItem.photo"
    return "object.item.videoItem"


async def _soap_action(
    device: Device,
    control_url: str,
    service_type: str,
    action: str,
    params: dict,
) -> dict | None:
    """Send a SOAP action request to the renderer."""
    body_parts = "".join(
        f"<{k}>{html.escape(str(v), quote=False)}</{k}>" for k, v in params.items()
    )
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body>'
        f'<u:{action} xmlns:u="{service_type}">'
        f'{body_parts}'
        f'</u:{action}>'
        '</s:Body>'
        '</s:Envelope>'
    )

    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{service_type}#{action}"',
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                control_url,
                data=envelope,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return _parse_soap_response(text)
                else:
                    logger.warning(f"SOAP {action} failed ({resp.status}): {text[:200]}")
                    return None
    except Exception as e:
        logger.error(f"SOAP {action} error for {device.name}: {e}")
        return None


def _parse_soap_response(xml_text: str) -> dict:
    """Parse SOAP response XML into a dict."""
    try:
        root = ET.fromstring(xml_text)
        body = root.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")
        if body is None:
            return {}
        result = {}
        for child in body:
            for elem in child:
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                result[tag] = elem.text or ""
        return result
    except Exception:
        return {}
