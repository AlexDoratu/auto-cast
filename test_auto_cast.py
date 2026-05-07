"""Tests for auto-cast modules."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from device import Device, DeviceType
from scanner import _SSDPProtocol
from dlna_controller import _parse_soap_response, _build_didl_lite


# --- Device Tests ---

class TestDevice:
    def test_create_dlna_device(self):
        d = Device(
            name="Living Room TV",
            device_type=DeviceType.DLNA,
            ip="192.168.1.100",
            port=5000,
            control_url="/AVTransport/control",
        )
        assert d.name == "Living Room TV"
        assert d.device_type == DeviceType.DLNA
        assert d.ip == "192.168.1.100"
        assert d.port == 5000
        assert d.display_type == "DLNA"

    def test_create_airplay_device(self):
        d = Device(
            name="Apple TV",
            device_type=DeviceType.AIRPLAY,
            ip="192.168.1.200",
            port=7000,
        )
        assert d.display_type == "AirPlay"

    def test_create_chromecast_device(self):
        d = Device(
            name="Chromecast",
            device_type=DeviceType.CHROMECAST,
            ip="192.168.1.300",
            port=8009,
        )
        assert d.display_type == "Cast"

    def test_str_representation(self):
        d = Device(name="TV", device_type=DeviceType.DLNA, ip="1.2.3.4", port=5000)
        assert "TV" in str(d)
        assert "DLNA" in str(d)
        assert "1.2.3.4" in str(d)

    def test_default_services_is_empty_list(self):
        d = Device(name="X", device_type=DeviceType.DLNA, ip="1.1.1.1", port=80)
        assert d.services == []

    def test_device_with_all_fields(self):
        d = Device(
            name="Full Device",
            device_type=DeviceType.DLNA,
            ip="10.0.0.1",
            port=5000,
            control_url="/ctrl",
            manufacturer="Samsung",
            model="SmartTV",
            uid="uuid:1234",
            services=["AVTransport"],
        )
        assert d.manufacturer == "Samsung"
        assert d.model == "SmartTV"
        assert d.uid == "uuid:1234"
        assert "AVTransport" in d.services


# --- SSDP Protocol Tests ---

class TestSSDPProtocol:
    def test_parse_location_header(self):
        proto = _SSDPProtocol()
        proto.connection_made(MagicMock())
        data = (
            "HTTP/1.1 200 OK\r\n"
            "LOCATION: http://192.168.1.100:5000/desc.xml\r\n"
            "SERVER: Linux/1.0\r\n"
            "\r\n"
        ).encode()
        proto.datagram_received(data, ("192.168.1.100", 1900))
        assert "http://192.168.1.100:5000/desc.xml" in proto.locations

    def test_ignores_non_location_headers(self):
        proto = _SSDPProtocol()
        proto.connection_made(MagicMock())
        data = "HTTP/1.1 200 OK\r\nSERVER: Test\r\n\r\n".encode()
        proto.datagram_received(data, ("1.1.1.1", 1900))
        assert proto.locations == []

    def test_multiple_locations(self):
        proto = _SSDPProtocol()
        proto.connection_made(MagicMock())
        for i in range(3):
            data = f"LOCATION: http://192.168.1.{i}:5000/desc.xml\r\n".encode()
            proto.datagram_received(data, (f"192.168.1.{i}", 1900))
        assert len(proto.locations) == 3

    def test_case_insensitive_location(self):
        proto = _SSDPProtocol()
        proto.connection_made(MagicMock())
        data = "location: http://192.168.1.1:5000/desc.xml\r\n".encode()
        proto.datagram_received(data, ("192.168.1.1", 1900))
        assert "http://192.168.1.1:5000/desc.xml" in proto.locations

    def test_malformed_data_ignored(self):
        proto = _SSDPProtocol()
        proto.connection_made(MagicMock())
        proto.datagram_received(b"\x00\x01\x02", ("1.1.1.1", 1900))
        assert proto.locations == []


# --- SOAP Response Tests ---

class TestSOAPResponse:
    def test_parse_valid_response(self):
        xml = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body>'
            '<u:GetTransportInfoResponse xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
            '<CurrentTransportState>PLAYING</CurrentTransportState>'
            '<CurrentTransportStatus>OK</CurrentTransportStatus>'
            '</u:GetTransportInfoResponse>'
            '</s:Body>'
            '</s:Envelope>'
        )
        result = _parse_soap_response(xml)
        assert result.get("CurrentTransportState") == "PLAYING"
        assert result.get("CurrentTransportStatus") == "OK"

    def test_parse_empty_response(self):
        result = _parse_soap_response("")
        assert result == {}

    def test_parse_malformed_xml(self):
        result = _parse_soap_response("<not valid xml>>>")
        assert result == {}

    def test_parse_no_body(self):
        xml = '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"></s:Envelope>'
        result = _parse_soap_response(xml)
        assert result == {}


# --- DIDL-Lite Tests ---

class TestDIDLLite:
    def test_build_didl_lite_contains_url(self):
        didl = _build_didl_lite("http://192.168.1.1:8080/media/test.mp4", "video/mp4")
        assert "http://192.168.1.1:8080/media/test.mp4" in didl
        assert "video/mp4" in didl

    def test_build_didl_lite_is_valid_xml(self):
        didl = _build_didl_lite("http://example.com/video.mp4", "video/mp4")
        import xml.etree.ElementTree as ET
        root = ET.fromstring(didl)
        assert root.tag.endswith("DIDL-Lite")

    def test_build_didl_lite_with_audio(self):
        didl = _build_didl_lite("http://example.com/song.mp3", "audio/mpeg")
        assert "audio/mpeg" in didl
        assert "song.mp3" in didl


# --- Media Server Tests ---

class TestMediaServer:
    def test_register_file(self):
        from media_server import MediaServer
        server = MediaServer()
        server.register_file("/path/to/video.mp4")
        assert any("video.mp4" in f for f in server._registered_files)

    def test_register_files_dedup(self):
        from media_server import MediaServer
        server = MediaServer()
        server.register_file("/path/to/video.mp4")
        server.register_file("/path/to/video.mp4")
        assert len(server._registered_files) == 1

    def test_register_multiple_files(self):
        from media_server import MediaServer
        server = MediaServer()
        server.register_files(["/a.mp4", "/b.mp3", "/c.jpg"])
        assert len(server._registered_files) == 3

    def test_get_url_format(self):
        from media_server import MediaServer
        server = MediaServer()
        server._local_ip = "192.168.1.1"
        server._actual_port = 12345
        url = server.get_url("/some/path/video.mp4")
        assert "192.168.1.1" in url
        assert "12345" in url
        assert "video.mp4" in url

    def test_get_local_ip_returns_string(self):
        from media_server import MediaServer
        ip = MediaServer._get_local_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_resolve_path_found(self):
        from media_server import MediaServer
        server = MediaServer()
        server._registered_files = ["/full/path/to/video.mp4"]
        result = server._resolve_path("video.mp4")
        assert result is not None
        assert str(result).endswith("video.mp4")

    def test_resolve_path_not_found(self):
        from media_server import MediaServer
        server = MediaServer()
        server._registered_files = ["/full/path/to/video.mp4"]
        result = server._resolve_path("other.mp4")
        assert result is None

    def test_resolve_path_empty_registry(self):
        from media_server import MediaServer
        server = MediaServer()
        result = server._resolve_path("video.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_server_start_stop(self, tmp_path):
        from media_server import MediaServer
        server = MediaServer(port=0)
        local_ip, port = await server.start()
        assert port > 0
        assert len(local_ip) > 0
        await server.stop()

    @pytest.mark.asyncio
    async def test_server_serves_file(self, tmp_path):
        from media_server import MediaServer
        import aiohttp

        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"fake video content")

        server = MediaServer(port=0)
        server.register_file(str(test_file))
        local_ip, port = await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                url = server.get_url(str(test_file))
                async with session.get(url) as resp:
                    assert resp.status == 200
                    content = await resp.read()
                    assert content == b"fake video content"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_server_404_for_missing_file(self, tmp_path):
        from media_server import MediaServer
        import aiohttp

        server = MediaServer(port=0)
        local_ip, port = await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{local_ip}:{port}/media/nonexistent.mp4"
                async with session.get(url) as resp:
                    assert resp.status == 404
        finally:
            await server.stop()


# --- Async Integration Tests ---

class TestAsyncIntegration:
    def test_scan_dlna_returns_list(self):
        from scanner import scan_dlna
        result = asyncio.run(scan_dlna(timeout=0.5))
        assert isinstance(result, list)

    def test_scan_airplay_returns_list(self):
        from scanner import scan_airplay
        result = asyncio.run(scan_airplay(timeout=0.5))
        assert isinstance(result, list)

    def test_scan_chromecast_returns_list(self):
        from scanner import scan_chromecast
        result = asyncio.run(scan_chromecast(timeout=0.5))
        assert isinstance(result, list)

    def test_scan_all_returns_list(self):
        from scanner import scan_all
        result = asyncio.run(scan_all(timeout=0.5))
        assert isinstance(result, list)

    def test_scan_by_type_dlna(self):
        from scanner import scan_by_type
        result = asyncio.run(scan_by_type(DeviceType.DLNA, timeout=0.5))
        assert isinstance(result, list)

    def test_scan_by_type_invalid_returns_empty(self):
        from scanner import scan_by_type
        result = asyncio.run(scan_by_type("invalid", timeout=0.5))
        assert result == []


# --- CLI Validation Tests ---

class TestCLI:
    def test_validate_media_nonexistent(self):
        import click
        from main import _validate_media
        with pytest.raises(click.BadParameter):
            _validate_media("/nonexistent/file.mp4")

    def test_validate_media_unsupported_format(self, tmp_path):
        import click
        from main import _validate_media
        f = tmp_path / "test.xyz"
        f.write_text("data")
        with pytest.raises(click.BadParameter):
            _validate_media(str(f))

    def test_validate_media_valid(self, tmp_path):
        from main import _validate_media
        f = tmp_path / "test.mp4"
        f.write_bytes(b"fake video data")
        path, ctype = _validate_media(str(f))
        assert ctype == "video/mp4"

    def test_validate_media_audio(self, tmp_path):
        from main import _validate_media
        f = tmp_path / "song.mp3"
        f.write_bytes(b"fake audio")
        path, ctype = _validate_media(str(f))
        assert ctype == "audio/mpeg"

    def test_validate_media_image(self, tmp_path):
        from main import _validate_media
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake image")
        path, ctype = _validate_media(str(f))
        assert ctype == "image/jpeg"

    def test_select_device_first(self):
        from main import _select_device
        devices = [
            Device("TV1", DeviceType.DLNA, "1.1.1.1", 5000),
            Device("TV2", DeviceType.DLNA, "2.2.2.2", 5000),
        ]
        assert _select_device(devices, None).name == "TV1"

    def test_select_device_by_name(self):
        from main import _select_device
        devices = [
            Device("Living Room", DeviceType.DLNA, "1.1.1.1", 5000),
            Device("Bedroom", DeviceType.DLNA, "2.2.2.2", 5000),
        ]
        assert _select_device(devices, "bedroom").name == "Bedroom"

    def test_select_device_partial_match(self):
        from main import _select_device
        devices = [
            Device("Samsung Smart TV", DeviceType.DLNA, "1.1.1.1", 5000),
        ]
        assert _select_device(devices, "samsung").name == "Samsung Smart TV"

    def test_select_device_empty_list(self):
        from main import _select_device
        assert _select_device([], None) is None

    def test_select_device_case_insensitive(self):
        from main import _select_device
        devices = [
            Device("Apple TV", DeviceType.AIRPLAY, "1.1.1.1", 7000),
        ]
        assert _select_device(devices, "APPLE TV").name == "Apple TV"


# --- DLNA Controller Helper Tests ---

class TestDLNAController:
    def test_get_control_url_with_path(self):
        from dlna_controller import _get_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        url = _get_control_url(d)
        assert url == "http://1.1.1.1:5000/AVTransport/control"

    def test_get_control_url_with_full_url(self):
        from dlna_controller import _get_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="http://1.1.1.1:5000/ctrl")
        url = _get_control_url(d)
        assert url == "http://1.1.1.1:5000/ctrl"

    def test_get_control_url_no_url(self):
        from dlna_controller import _get_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        url = _get_control_url(d)
        assert "AVTransport/control" in url

    def test_build_didl_lite_structure(self):
        from dlna_controller import _build_didl_lite
        didl = _build_didl_lite("http://test.com/v.mp4", "video/mp4")
        assert "DIDL-Lite" in didl
        assert "http://test.com/v.mp4" in didl

    def test_get_rendering_control_url(self):
        from dlna_controller import _get_rendering_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        url = _get_rendering_control_url(d)
        assert "RenderingControl" in url

    def test_get_rendering_control_url_no_control(self):
        from dlna_controller import _get_rendering_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        url = _get_rendering_control_url(d)
        assert "RenderingControl" in url
