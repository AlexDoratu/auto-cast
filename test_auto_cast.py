"""Tests for auto-cast modules."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from device import Device, DeviceType
from scanner import _SSDPProtocol, _absolute_url, _find_control_url
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

    def test_find_rendering_control_url(self):
        import xml.etree.ElementTree as ET
        xml = """
        <device xmlns="urn:schemas-upnp-org:device-1-0">
          <serviceList>
            <service>
              <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
              <controlURL>/upnp/control/avtransport1</controlURL>
            </service>
            <service>
              <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
              <controlURL>/upnp/control/renderingcontrol1</controlURL>
            </service>
          </serviceList>
        </device>
        """
        root = ET.fromstring(xml)
        ns = {"upnp": "urn:schemas-upnp-org:device-1-0"}
        assert _find_control_url(root, ns, "RenderingControl") == "/upnp/control/renderingcontrol1"

    def test_absolute_url_resolves_relative_control_url(self):
        url = _absolute_url("http://192.168.1.100:5000/root/desc.xml", "../upnp/control/avtransport1")
        assert url == "http://192.168.1.100:5000/upnp/control/avtransport1"

    def test_absolute_url_preserves_full_control_url(self):
        url = _absolute_url("http://192.168.1.100:5000/desc.xml", "http://192.168.1.100:7000/ctrl")
        assert url == "http://192.168.1.100:7000/ctrl"


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


# --- Resume State Tests ---

class TestResumeState:
    def test_state_round_trip(self, tmp_path):
        from app_state import ResumeState, load_state, save_state
        path = tmp_path / "state.json"
        state = ResumeState(
            device_name="TV",
            device_type="dlna",
            device_ip="1.2.3.4",
            source_type="media",
            media_path="D:/video/a.mp4",
            queue=["D:/video/a.mp4", "D:/video/b.mp4"],
            queue_index=1,
            position="00:12:34",
        )
        save_state(state, path)
        assert load_state(path) == state

    def test_matches_device_by_name_ip_and_type(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="TV", device_type="dlna", device_ip="1.2.3.4")
        device = Device("TV", DeviceType.DLNA, "1.2.3.4", 5000)
        assert matches_device(state, device)

    def test_matches_device_rejects_ip_only_match(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_type="dlna", device_ip="1.2.3.4")
        device = Device("TV", DeviceType.DLNA, "1.2.3.4", 5000)
        assert not matches_device(state, device)

    def test_matches_device_falls_back_to_name_ip_when_uid_missing_on_device(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="TV", device_type="dlna", device_ip="1.2.3.4", device_uid="uuid:tv")
        device = Device("TV", DeviceType.DLNA, "1.2.3.4", 5000)
        assert matches_device(state, device)

    def test_redact_url_removes_query_tokens(self):
        from app_state import redact_url
        url = redact_url("https://live.bilibili.com/440006?session_id=secret&token=value")
        assert url == "https://live.bilibili.com/440006"

    def test_load_state_preserves_live_url_query_for_resume(self, tmp_path):
        from app_state import load_state
        path = tmp_path / "state.json"
        path.write_text('{"live_url":"https://live.bilibili.com/440006?session_id=needed"}', encoding="utf-8")
        assert load_state(path).live_url == "https://live.bilibili.com/440006?session_id=needed"

    def test_load_state_discards_invalid_queue(self, tmp_path):
        from app_state import load_state
        path = tmp_path / "state.json"
        path.write_text('{"queue":"not-a-list"}', encoding="utf-8")
        assert load_state(path).queue == []

    def test_load_state_sanitizes_invalid_resume_fields(self, tmp_path):
        from app_state import load_state
        path = tmp_path / "state.json"
        path.write_text('{"queue_index":"bad","position":123,"auto_resume_enabled":"yes","media_path":123,"live_url":null}', encoding="utf-8")
        state = load_state(path)
        assert state.queue_index == 0
        assert state.position == ""
        assert state.auto_resume_enabled is True
        assert state.media_path == ""
        assert state.live_url == ""

    def test_state_for_device_stores_queue_and_position(self):
        from app_state import state_for_device
        device = Device("TV", DeviceType.DLNA, "1.2.3.4", 5000)
        state = state_for_device(
            device,
            "media",
            media_path="D:/video/b.mp4",
            queue=["D:/video/a.mp4", "D:/video/b.mp4"],
            queue_index=1,
            position="00:01:02",
        )
        assert state.queue == ["D:/video/a.mp4", "D:/video/b.mp4"]
        assert state.queue_index == 1
        assert state.position == "00:01:02"

    def test_matches_device_rejects_uid_with_different_ip(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="TV", device_type="dlna", device_ip="1.2.3.4", device_uid="uuid:tv")
        device = Device("TV", DeviceType.DLNA, "5.6.7.8", 5000, uid="uuid:tv")
        assert not matches_device(state, device)

    def test_load_state_preserves_legacy_live_url_query(self, tmp_path):
        from app_state import load_state
        path = tmp_path / "state.json"
        path.write_text('{"live_url":"https://live.bilibili.com/440006?session_id=secret"}', encoding="utf-8")
        assert load_state(path).live_url == "https://live.bilibili.com/440006?session_id=secret"

    def test_matches_device_allows_same_renderer_with_different_discovery_type(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="TV", device_type="airplay", device_ip="1.2.3.4")
        device = Device("TV", DeviceType.DLNA, "1.2.3.4", 5000)
        assert matches_device(state, device)

    def test_matches_device_rejects_different_name_without_uid(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="TV", device_type="airplay", device_ip="1.2.3.4")
        device = Device("Other TV", DeviceType.DLNA, "1.2.3.4", 5000)
        assert not matches_device(state, device)

    def test_matches_device_allows_same_ip_aggregated_capability(self):
        from app_state import ResumeState, matches_device
        state = ResumeState(device_name="客厅的小米电视", device_type="airplay", device_ip="1.2.3.4")
        device = Device("1.2.3.4", DeviceType.DLNA, "1.2.3.4", 49152, services=["airplay", "dlna"])
        assert matches_device(state, device)


# --- Media Server Tests ---

class TestFFmpegTranscoder:
    def test_build_ffmpeg_command_outputs_mpegts(self):
        from ffmpeg_transcoder import build_ffmpeg_command
        command = build_ffmpeg_command("ffmpeg", "https://cdn.example.com/live.m3u8")
        assert command[0] == "ffmpeg"
        assert "https://cdn.example.com/live.m3u8" in command
        assert "mpegts" in command
        assert command[-1] == "pipe:1"

    def test_build_ffmpeg_command_supports_multipart_mjpeg_input(self):
        from ffmpeg_transcoder import build_ffmpeg_command
        command = build_ffmpeg_command("ffmpeg", "http://127.0.0.1/stream", "mjpeg")
        assert command[command.index("-f") + 1] == "mpjpeg"
        assert "-reconnect" not in command

    def test_build_ffmpeg_command_sets_manual_low_latency_video_options(self):
        from ffmpeg_transcoder import build_ffmpeg_command
        command = build_ffmpeg_command("ffmpeg", "https://cdn.example.com/live.m3u8")
        assert "-maxrate" in command
        assert "-bufsize" in command
        assert command[command.index("-g") + 1] == "60"
        assert command[command.index("-sc_threshold") + 1] == "0"

    def test_build_ffmpeg_command_reconnects_live_network_inputs(self):
        from ffmpeg_transcoder import build_ffmpeg_command
        command = build_ffmpeg_command("ffmpeg", "https://cdn.example.com/live.m3u8")
        assert command[command.index("-reconnect_at_eof") + 1] == "1"
        assert command[command.index("-reconnect_on_network_error") + 1] == "1"
        assert command[command.index("-reconnect_on_http_error") + 1] == "4xx,5xx"
        assert command[command.index("-rw_timeout") + 1] == "10000000"

    @patch("ffmpeg_transcoder.shutil.which", return_value=None)
    def test_ffmpeg_transcoder_errors_when_ffmpeg_missing(self, _which):
        from ffmpeg_transcoder import FFmpegTranscoder
        with pytest.raises(RuntimeError):
            FFmpegTranscoder("https://cdn.example.com/live.m3u8").start()

    @pytest.mark.asyncio
    async def test_ffmpeg_transcoder_converts_closing_transport_to_connection_error(self):
        from ffmpeg_transcoder import FFmpegTranscoder

        class FakeStdout:
            def __init__(self):
                self.reads = 0

            def read(self, _size):
                self.reads += 1
                return b"chunk" if self.reads == 1 else b""

        class FakeProcess:
            stdout = FakeStdout()

            def poll(self):
                return None

        class FakeResponse:
            async def write(self, _chunk):
                raise RuntimeError("Cannot write to closing transport")

        transcoder = FFmpegTranscoder("https://cdn.example.com/live.m3u8")
        transcoder.process = FakeProcess()
        with pytest.raises(ConnectionError):
            await transcoder.write_to_response(FakeResponse())


class TestMediaServer:
    def test_register_file(self):
        from media_server import MediaServer
        server = MediaServer()
        file_id = server.register_file("/path/to/video.mp4")
        assert file_id.endswith(".mp4")
        assert server._registered_files[file_id].endswith("video.mp4")

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
        assert url.startswith("http://192.168.1.1:12345/media/")
        assert url.endswith(".mp4")

    def test_register_live_stream_url_format(self):
        from media_server import MediaServer
        server = MediaServer()
        server._local_ip = "192.168.1.1"
        server._actual_port = 12345
        url = server.register_live_stream("https://cdn.example.com/live.m3u8")
        assert url.startswith("http://192.168.1.1:12345/live/")
        assert url.endswith(".ts")
        assert len(server._live_streams) == 1

    @pytest.mark.asyncio
    async def test_live_stream_handler_stops_transcoder_on_disconnect(self):
        from media_server import MediaServer
        from aiohttp.test_utils import make_mocked_request

        class FakeResponse:
            async def prepare(self, _request):
                return None

        class FakeTranscoder:
            stopped = False

            async def write_to_response(self, _response):
                raise ConnectionError("client closed")

            def stop(self):
                self.stopped = True

        server = MediaServer()
        server.register_live_stream("https://cdn.example.com/live.m3u8")
        stream_id = next(iter(server._live_streams))
        transcoder = FakeTranscoder()
        request = make_mocked_request("GET", f"/live/{stream_id}.ts", match_info={"stream_id": stream_id})
        with patch("media_server.web.StreamResponse", return_value=FakeResponse()):
            with patch("media_server.FFmpegTranscoder", return_value=transcoder):
                await server._handle_live_stream(request)
        assert transcoder.stopped is True

    @pytest.mark.asyncio
    async def test_live_stream_handler_creates_transcoder_per_request(self):
        from media_server import MediaServer
        from aiohttp.test_utils import make_mocked_request

        class FakeResponse:
            async def prepare(self, _request):
                return None

        class FakeTranscoder:
            def __init__(self):
                self.stopped = False

            async def write_to_response(self, _response):
                return None

            def stop(self):
                self.stopped = True

        transcoders = [FakeTranscoder(), FakeTranscoder()]
        server = MediaServer()
        server.register_live_stream("https://cdn.example.com/live.m3u8")
        stream_id = next(iter(server._live_streams))
        request = make_mocked_request("GET", f"/live/{stream_id}.ts", match_info={"stream_id": stream_id})
        with patch("media_server.web.StreamResponse", return_value=FakeResponse()):
            with patch("media_server.FFmpegTranscoder", side_effect=transcoders):
                await server._handle_live_stream(request)
                await server._handle_live_stream(request)
        assert all(transcoder.stopped for transcoder in transcoders)

    @pytest.mark.asyncio
    async def test_server_stop_stops_active_live_transcoders(self):
        from media_server import MediaServer

        class FakeTranscoder:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        server = MediaServer()
        transcoder = FakeTranscoder()
        server._active_transcoders.append(transcoder)
        await server.stop()
        assert transcoder.stopped is True
        assert server._active_transcoders == []

    @pytest.mark.asyncio
    async def test_media_response_does_not_override_file_response_content_length(self, tmp_path):
        from media_server import MediaServer
        from aiohttp.test_utils import make_mocked_request

        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"fake video content")
        server = MediaServer()
        file_id = server.register_file(str(test_file))
        request = make_mocked_request("GET", f"/media/{file_id}", match_info={"filename": file_id})
        response = await server._handle_media(request)
        assert "Content-Length" not in response.headers

    def test_get_local_ip_returns_string(self):
        from media_server import MediaServer
        ip = MediaServer._get_local_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_resolve_path_found(self):
        from media_server import MediaServer
        server = MediaServer()
        file_id = server.register_file("/full/path/to/video.mp4")
        result = server._resolve_path(file_id)
        assert result is not None
        assert str(result).endswith("video.mp4")

    def test_resolve_path_not_found(self):
        from media_server import MediaServer
        server = MediaServer()
        server.register_file("/full/path/to/video.mp4")
        result = server._resolve_path("other.mp4")
        assert result is None

    def test_register_file_avoids_basename_collisions(self):
        from media_server import MediaServer
        server = MediaServer()
        first = server.register_file("/a/video.mp4")
        second = server.register_file("/b/video.mp4")
        assert first != second
        assert len(server._registered_files) == 2

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

class TestLiveResolver:
    def test_guess_content_type_hls(self):
        from live_resolver import guess_content_type
        assert guess_content_type("https://example.com/live.m3u8") == "application/vnd.apple.mpegurl"

    def test_guess_content_type_flv(self):
        from live_resolver import guess_content_type
        assert guess_content_type("https://example.com/live.flv") == "video/x-flv"

    @patch("live_resolver.shutil.which", return_value=None)
    def test_resolve_live_url_errors_without_resolver(self, _which):
        from live_resolver import resolve_live_url
        with pytest.raises(RuntimeError):
            resolve_live_url("https://live.bilibili.com/123")

    @patch("live_resolver.yt_dlp", None)
    @patch("live_resolver.shutil.which", side_effect=lambda name: "yt-dlp" if name == "yt-dlp" else None)
    @patch("live_resolver.subprocess.run")
    def test_resolve_live_url_uses_ytdlp_command(self, run_mock, _which):
        from live_resolver import resolve_live_url
        run_mock.return_value = MagicMock(returncode=0, stdout="https://cdn.example.com/live.m3u8\n")
        url, content_type = resolve_live_url("https://live.bilibili.com/123")
        assert url == "https://cdn.example.com/live.m3u8"
        assert content_type == "application/vnd.apple.mpegurl"

    def test_extract_stream_url_ignores_non_string_facade_url(self):
        from live_resolver import _extract_stream_url

        class FacadeStream:
            pass

        url = _extract_stream_url({
            "url": FacadeStream(),
            "formats": [{"url": "https://cdn.example.com/live.m3u8", "protocol": "m3u8_native", "height": 1080}],
        })
        assert url == "https://cdn.example.com/live.m3u8"

    def test_resolve_live_url_rejects_non_http_url(self):
        from live_resolver import resolve_live_url
        with pytest.raises(ValueError):
            resolve_live_url("file:///tmp/video.mp4")


class TestVideoResolver:
    def test_start_time_from_url_reads_bilibili_t(self):
        from video_resolver import start_time_from_url
        url = "https://www.bilibili.com/video/BV1euUWB5Eg4/?t=3669"
        assert start_time_from_url(url) == 3669

    def test_format_seconds(self):
        from video_resolver import format_seconds
        assert format_seconds(3669) == "01:01:09"

    def test_progress_payload(self):
        from video_resolver import _progress_payload
        result = _progress_payload({
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 10,
            "eta": 5,
            "filename": "test.mp4",
        })
        assert result["percent"] == 0.5
        assert result["filename"] == "test.mp4"
        assert result["phase"] == "Downloading video"

    def test_progress_payload_treats_finished_bytes_as_total(self):
        from video_resolver import _progress_payload
        result = _progress_payload({
            "status": "finished",
            "downloaded_bytes": 100,
            "filename": "test.mp4",
        })
        assert result["percent"] == 1.0
        assert result["phase"] == "Merging"

    def test_progress_payload_uses_fragment_progress_when_bytes_unknown(self):
        from video_resolver import _progress_payload
        result = _progress_payload({
            "status": "downloading",
            "fragment_index": 3,
            "fragment_count": 10,
            "filename": "test.m4s",
        })
        assert result["percent"] == 0.3
        assert result["fragment_index"] == 3
        assert result["fragment_count"] == 10

    def test_estimated_progress_for_unknown_size_download(self):
        from video_resolver import _with_estimated_percent
        import video_resolver

        with patch.object(video_resolver.time, "monotonic", return_value=30):
            result = _with_estimated_percent({"status": "downloading", "percent": None}, 0)
        assert 0 < result["percent"] < 1
        assert result["estimated"] is True

    def test_cache_video_result_includes_source_url(self, tmp_path):
        import video_resolver

        cached_file = tmp_path / "Fake-p9.mp4"
        cached_file.write_bytes(b"fake")

        class FakeYdl:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def extract_info(self, _url, download=False):
                return {
                    "title": "p9",
                    "duration": 10,
                    "id": "p9",
                    "extractor_key": "Fake",
                }

            def prepare_filename(self, _info):
                return str(cached_file)

        with patch.object(video_resolver, "CACHE_DIR", tmp_path):
            with patch.object(video_resolver.yt_dlp, "YoutubeDL", FakeYdl):
                result = video_resolver.cache_video_url("https://example.com/p9")

        assert result["source_url"] == "https://example.com/p9"
        assert result["path"] == str(cached_file)

    def test_video_format_prefers_h264(self):
        from video_resolver import VIDEO_FORMAT
        assert "vcodec^=avc1" in VIDEO_FORMAT
        assert "acodec^=mp4a" in VIDEO_FORMAT

    def test_video_format_allows_unknown_direct_mp4_metadata(self):
        from video_resolver import VIDEO_FORMAT
        assert "height<=?720" in VIDEO_FORMAT


class TestDLNAController:
    @pytest.mark.asyncio
    async def test_play_raises_when_set_uri_fails(self):
        import dlna_controller
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")

        async def fake_action(_device, _url, _service, action, _params):
            return None if action == "SetAVTransportURI" else {}

        with patch.object(dlna_controller, "_soap_action", side_effect=fake_action):
            with pytest.raises(RuntimeError, match="Failed to set media URI"):
                await dlna_controller.play(d, "http://example.com/video.mp4", "video/mp4")

    @pytest.mark.asyncio
    async def test_play_raises_when_play_fails(self):
        import dlna_controller
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")

        async def fake_action(_device, _url, _service, action, _params):
            return None if action == "Play" else {}

        with patch.object(dlna_controller, "_soap_action", side_effect=fake_action):
            with pytest.raises(RuntimeError, match="Failed to start playback"):
                await dlna_controller.play(d, "http://example.com/video.mp4", "video/mp4")

    @pytest.mark.asyncio
    async def test_get_position_info_returns_position(self):
        import dlna_controller
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")

        async def fake_action(_device, _url, _service, action, _params):
            assert action == "GetPositionInfo"
            return {"RelTime": "00:01:02"}

        with patch.object(dlna_controller, "_soap_action", side_effect=fake_action):
            assert await dlna_controller.get_position_info(d) == {"RelTime": "00:01:02"}

    @pytest.mark.asyncio
    async def test_get_volume_returns_current_volume(self):
        import dlna_controller
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, rendering_control_url="/RenderingControl/control")

        async def fake_action(_device, _url, _service, action, params):
            assert action == "GetVolume"
            assert params == {"InstanceID": "0", "Channel": "Master"}
            return {"CurrentVolume": "6"}

        with patch.object(dlna_controller, "_soap_action", side_effect=fake_action):
            assert await dlna_controller.get_volume(d) == "6"

    @pytest.mark.asyncio
    async def test_seek_raises_on_failure(self):
        import dlna_controller
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")

        with patch.object(dlna_controller, "_soap_action", return_value=None):
            with pytest.raises(RuntimeError, match="Failed to seek"):
                await dlna_controller.seek(d, "00:01:02")

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

    def test_absolute_url_resolves_dlna_probe_relative_control_url(self):
        from dlna_controller import _absolute_url
        url = _absolute_url("http://1.1.1.1:5000/root/desc.xml", "../upnp/control/avtransport1")
        assert url == "http://1.1.1.1:5000/upnp/control/avtransport1"

    def test_find_text_xml_reads_url_base(self):
        import xml.etree.ElementTree as ET
        from dlna_controller import _find_text_xml
        root = ET.fromstring("<root><URLBase>http://1.1.1.1:5000/base/</URLBase></root>")
        assert _find_text_xml(root, "URLBase") == "http://1.1.1.1:5000/base/"

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

    def test_get_rendering_control_url_uses_discovered_service_url(self):
        from dlna_controller import _get_rendering_control_url
        d = Device(
            "TV",
            DeviceType.DLNA,
            "1.1.1.1",
            5000,
            control_url="/upnp/control/avtransport1",
            rendering_control_url="/upnp/control/renderingcontrol1",
        )
        assert _get_rendering_control_url(d) == "http://1.1.1.1:5000/upnp/control/renderingcontrol1"

    def test_get_rendering_control_url_no_control(self):
        from dlna_controller import _get_rendering_control_url
        d = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        url = _get_rendering_control_url(d)
        assert "RenderingControl" in url


class TestGUIBridge:
    def test_device_json_round_trip(self):
        from gui_bridge import device_from_json, device_to_json
        device = Device(
            "Living TV",
            DeviceType.DLNA,
            "192.168.1.20",
            5000,
            control_url="/AVTransport/control",
            rendering_control_url="/RenderingControl/control",
            manufacturer="ACME",
            model="TV-1",
            uid="uuid:tv",
        )
        data = device_to_json(device)
        assert data["device_type"] == "dlna"
        assert data["display_type"] == "DLNA"
        restored = device_from_json(data)
        assert restored == device

    @pytest.mark.asyncio
    async def test_bridge_rejects_unknown_command(self):
        from gui_bridge import BridgeSession
        session = BridgeSession()
        try:
            with pytest.raises(ValueError, match="Unknown command"):
                await session.handle({"command": "missing"})
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_state_command_returns_state(self, tmp_path):
        from gui_bridge import BridgeSession
        session = BridgeSession()
        try:
            result = await session.handle({"command": "state"})
            assert "state" in result
            assert result["playing"] is False
            assert result["cache_dir"]
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_playback_status_idle(self):
        from gui_bridge import BridgeSession
        session = BridgeSession()
        try:
            result = await session.handle({"command": "playback_status"})
            assert result["playing"] is False
            assert result["state"] == "IDLE"
            assert result["position_seconds"] == 0
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_playback_status_dlna(self):
        from gui_bridge import BridgeSession
        import dlna_controller

        session = BridgeSession()
        session.playback_device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)

        with patch.object(dlna_controller, "get_position_info", return_value={"RelTime": "00:01:02", "TrackDuration": "00:02:00"}):
            with patch.object(dlna_controller, "get_transport_info", return_value={"CurrentTransportState": "PLAYING", "CurrentTransportStatus": "OK"}):
                with patch.object(dlna_controller, "get_volume", return_value="55"):
                    result = await session.handle({"command": "playback_status"})
        try:
            assert result["playing"] is True
            assert result["state"] == "PLAYING"
            assert result["status"] == "OK"
            assert result["position_seconds"] == 62
            assert result["duration_seconds"] == 120
            assert result["volume"] == 55
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_playback_status_uses_fallbacks_on_timeout(self):
        from gui_bridge import BridgeSession
        import gui_bridge
        import dlna_controller

        session = BridgeSession()
        session.playback_device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)

        async def slow_position(_device):
            await asyncio.sleep(0.05)
            return {"RelTime": "00:00:05"}

        try:
            with patch.object(gui_bridge, "TV_STATUS_TIMEOUT_SECONDS", 0.001):
                with patch.object(dlna_controller, "get_position_info", side_effect=slow_position):
                    with patch.object(dlna_controller, "get_transport_info", return_value={"CurrentTransportState": "PLAYING"}):
                        with patch.object(dlna_controller, "get_volume", return_value="55"):
                            result = await session.handle({"command": "playback_status"})
            assert result["state"] == "PLAYING"
            assert result["position"] == "00:00:00"
            assert result["volume"] == 55
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_playback_status_estimates_media_position_without_rel_time(self):
        from gui_bridge import BridgeSession
        import gui_bridge
        import dlna_controller

        session = BridgeSession()
        session.playback_device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        session.current_session = {
            "kind": "media",
            "position": "00:10:00",
            "started_at": 100.0,
        }

        try:
            with patch.object(gui_bridge.time, "monotonic", return_value=130.0):
                with patch.object(dlna_controller, "get_position_info", return_value={}):
                    with patch.object(dlna_controller, "get_transport_info", return_value={"CurrentTransportState": "PLAYING"}):
                        with patch.object(dlna_controller, "get_volume", return_value="55"):
                            result = await session.handle({"command": "playback_status"})
            assert result["position"] == "00:10:30"
            assert result["position_seconds"] == 630
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_seek_uses_seconds(self):
        from gui_bridge import BridgeSession
        import dlna_controller

        session = BridgeSession()
        session.playback_device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        with patch.object(dlna_controller, "seek", new_callable=AsyncMock) as seek_mock:
            result = await session.handle({"command": "seek", "seconds": 3669})
        try:
            assert result["position"] == "01:01:09"
            seek_mock.assert_awaited_once()
        finally:
            session.close()

    def test_bridge_cache_video_emits_progress(self):
        from gui_bridge import BridgeSession
        import gui_bridge

        events = []
        session = BridgeSession(event_sink=events.append)

        def fake_cache(_url, callback):
            callback({"status": "downloading", "percent": 0.5})
            return {"path": "D:/cache/video.mp4"}

        try:
            with patch.object(gui_bridge, "cache_video_url", side_effect=fake_cache):
                result = session._cache_video_with_progress("https://example.com/video")
            assert result["path"] == "D:/cache/video.mp4"
            assert events[0]["event"] == "download_progress"
            assert events[1]["event"] == "download_complete"
            assert session.last_download_progress["percent"] == 1.0
        finally:
            session.close()

    def test_bridge_cache_video_starts_background_task(self):
        from gui_bridge import BridgeSession

        session = BridgeSession()
        try:
            with patch.object(session, "_run_cache_task", return_value=None):
                result = session.start_cache_video("https://example.com/video")
                assert result["status"] == "started"
                assert result["task_id"] in session.download_tasks
                cancel = session.cancel_cache(result["task_id"])
                assert cancel["status"] == "cancel_requested"
        finally:
            session.close()

    def test_bridge_cancelled_cache_does_not_emit_complete(self):
        from gui_bridge import BridgeSession
        import gui_bridge

        events = []
        session = BridgeSession(event_sink=events.append)
        session.download_tasks["task-1"] = {
            "id": "task-1",
            "url": "https://example.com/video",
            "status": "running",
            "cancel": __import__("threading").Event(),
            "result": None,
            "error": "",
        }

        def fake_cache(_url, callback):
            session.cancel_cache("task-1")
            callback({"status": "downloading", "phase": "Downloading video"})
            return {"path": "D:/cache/video.mp4"}

        try:
            with patch.object(gui_bridge, "cache_video_url", side_effect=fake_cache):
                session._run_cache_task("task-1")
            event_names = [event["event"] for event in events]
            assert "download_complete" not in event_names
            assert events[-1]["event"] == "download_failed"
            assert events[-1]["payload"]["status"] == "cancelled"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_pick_file_command(self):
        from gui_bridge import BridgeSession
        import gui_bridge

        session = BridgeSession()
        try:
            with patch.object(gui_bridge, "pick_media_file", return_value={"path": "D:/video/test.mp4"}):
                result = await session.handle({"command": "pick_file"})
            assert result["path"] == "D:/video/test.mp4"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_pick_files_command(self):
        from gui_bridge import BridgeSession
        import gui_bridge

        session = BridgeSession()
        try:
            with patch.object(gui_bridge, "pick_media_files", return_value={"paths": ["D:/video/a.mp4", "D:/video/b.mp4"]}):
                result = await session.handle({"command": "pick_files"})
            assert result["paths"] == ["D:/video/a.mp4", "D:/video/b.mp4"]
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_airplay_falls_back_to_dlna(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import airplay_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        airplay = Device("TV", DeviceType.AIRPLAY, "1.1.1.1", 7000)
        dlna = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        session = BridgeSession()
        try:
            with patch.object(airplay_controller, "play", side_effect=RuntimeError("stream_file is not supported")):
                with patch.object(session, "_dlna_target", new_callable=AsyncMock, return_value=dlna):
                    with patch.object(session, "_play_dlna_file", new_callable=AsyncMock, return_value={"status": "playing", "url": "http://local/video.mp4"}):
                        result = await session.handle({"command": "play_media", "device": gui_bridge.device_to_json(airplay), "path": str(media)})
            assert result["transport"] == "dlna-fallback"
            assert result["status"] == "playing"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_with_position_prefers_dlna_on_dual_device(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import airplay_controller
        import dlna_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        device = Device("TV", DeviceType.AIRPLAY, "1.1.1.1", 7000, services=["airplay", "dlna"])
        dlna = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        session = BridgeSession()
        try:
            with patch.object(gui_bridge, "save_state"):
                with patch.object(airplay_controller, "play", new_callable=AsyncMock) as airplay_mock:
                    with patch.object(session, "_dlna_target", new_callable=AsyncMock, return_value=dlna):
                        with patch.object(session, "_play_dlna_file", new_callable=AsyncMock, return_value={"status": "playing", "url": "http://local/video.mp4"}):
                            with patch.object(dlna_controller, "seek", new_callable=AsyncMock) as seek_mock:
                                result = await session.handle({
                                    "command": "play_media",
                                    "device": gui_bridge.device_to_json(device),
                                    "path": str(media),
                                    "position": "00:01:23",
                                })
            assert result["transport"] == "dlna"
            airplay_mock.assert_not_awaited()
            seek_mock.assert_awaited_once_with(dlna, "00:01:23")
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_zero_position_allows_airplay(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import airplay_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        device = Device("TV", DeviceType.AIRPLAY, "1.1.1.1", 7000)
        session = BridgeSession()
        try:
            with patch.object(gui_bridge, "save_state"):
                with patch.object(airplay_controller, "play", new_callable=AsyncMock) as airplay_mock:
                    result = await session.handle({
                        "command": "play_media",
                        "device": gui_bridge.device_to_json(device),
                        "path": str(media),
                        "position": "00:00:00",
                    })
            assert result["transport"] == "airplay"
            airplay_mock.assert_awaited_once()
        finally:
            session.close()

    def test_bridge_device_json_includes_capabilities(self):
        import gui_bridge

        device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, services=["airplay", "dlna"])
        data = gui_bridge.device_to_json(device)
        restored = gui_bridge.device_from_json(data)

        assert data["display_type"] == "AirPlay + DLNA"
        assert data["capabilities"] == ["airplay", "dlna"]
        assert restored.services == ["airplay", "dlna"]

    @pytest.mark.asyncio
    async def test_bridge_scan_aggregates_airplay_with_dlna_probe(self):
        import gui_bridge
        import dlna_controller

        airplay = Device("Living Room", DeviceType.AIRPLAY, "1.1.1.1", 7000, model="AppleTV3,1")
        dlna = Device("1.1.1.1", DeviceType.DLNA, "1.1.1.1", 49152, control_url="/AVTransport/control")

        with patch.object(gui_bridge, "scan_all", new_callable=AsyncMock, return_value=[airplay]):
            with patch.object(dlna_controller, "discover_dlna", new_callable=AsyncMock, return_value=dlna):
                devices = await gui_bridge.scan_devices_with_capabilities(0.1)

        assert len(devices) == 1
        assert devices[0].name == "Living Room"
        assert devices[0].device_type == DeviceType.DLNA
        assert devices[0].port == 49152
        assert devices[0].control_url == "/AVTransport/control"
        assert devices[0].services == ["airplay", "dlna"]

    @pytest.mark.asyncio
    async def test_bridge_resume_last_media_uses_aggregated_scan(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        from app_state import ResumeState

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        device = Device("TV", DeviceType.DLNA, "1.1.1.1", 49152, services=["airplay", "dlna"])
        session = BridgeSession()
        session.state = ResumeState(device_name="TV", device_type="airplay", device_ip="1.1.1.1", source_type="media", media_path=str(media))
        try:
            with patch.object(gui_bridge, "load_state", return_value=session.state):
                with patch.object(gui_bridge, "scan_devices_with_capabilities", new_callable=AsyncMock, return_value=[device]):
                    with patch.object(session, "play_media", new_callable=AsyncMock, return_value={"status": "playing"}) as play_mock:
                        result = await session.resume_last(0.1)
            assert result["status"] == "playing"
            assert play_mock.await_args.args[0]["device"]["display_type"] == "AirPlay + DLNA"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_dlna_seeks_start_position(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import dlna_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        dlna = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        session = BridgeSession()
        try:
            with patch.object(gui_bridge.MediaServer, "start_background", return_value=("127.0.0.1", 8080)):
                with patch.object(gui_bridge.MediaServer, "get_url", return_value="http://127.0.0.1:8080/video.mp4"):
                    with patch.object(dlna_controller, "play", new_callable=AsyncMock):
                        with patch.object(dlna_controller, "seek", new_callable=AsyncMock) as seek_mock:
                            result = await session.handle({
                                "command": "play_media",
                                "device": gui_bridge.device_to_json(dlna),
                                "path": str(media),
                                "position": "01:01:09",
                            })
            assert result["position"] == "01:01:09"
            seek_mock.assert_awaited_once()
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_retries_start_position_seek(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import dlna_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        dlna = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        session = BridgeSession()
        try:
            with patch.object(gui_bridge.MediaServer, "start_background", return_value=("127.0.0.1", 8080)):
                with patch.object(gui_bridge.MediaServer, "get_url", return_value="http://127.0.0.1:8080/video.mp4"):
                    with patch.object(dlna_controller, "play", new_callable=AsyncMock):
                        with patch.object(dlna_controller, "seek", new_callable=AsyncMock, side_effect=[RuntimeError("not ready"), None]) as seek_mock:
                            result = await session.handle({
                                "command": "play_media",
                                "device": gui_bridge.device_to_json(dlna),
                                "path": str(media),
                                "position": "00:02:03",
                            })
            assert result["position"] == "00:02:03"
            assert seek_mock.await_count == 2
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_play_media_cleans_server_on_dlna_failure(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        import dlna_controller

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        dlna = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000, control_url="/AVTransport/control")
        session = BridgeSession()
        server = MagicMock()
        server.get_url.return_value = "http://127.0.0.1:8080/video.mp4"
        try:
            with patch.object(gui_bridge, "MediaServer", return_value=server):
                with patch.object(dlna_controller, "play", new_callable=AsyncMock, side_effect=RuntimeError("TV rejected URI")):
                    with pytest.raises(RuntimeError, match="TV rejected URI"):
                        await session.handle({
                            "command": "play_media",
                            "device": gui_bridge.device_to_json(dlna),
                            "path": str(media),
                        })
            server.stop_background.assert_called_once()
            assert session.media_server is None
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_resume_last_media(self, tmp_path):
        from gui_bridge import BridgeSession
        import gui_bridge
        from app_state import ResumeState

        media = tmp_path / "video.mp4"
        media.write_bytes(b"fake")
        device = Device("TV", DeviceType.DLNA, "1.1.1.1", 5000)
        session = BridgeSession()
        session.state = ResumeState(device_name="TV", device_type="dlna", device_ip="1.1.1.1", source_type="media", media_path=str(media), position="00:00:05")
        try:
            with patch.object(gui_bridge, "load_state", return_value=session.state):
                with patch.object(gui_bridge, "scan_devices_with_capabilities", new_callable=AsyncMock, return_value=[device]):
                    with patch.object(session, "play_media", new_callable=AsyncMock, return_value={"status": "playing"}) as play_mock:
                        result = await session.resume_last(0.1)
            assert result["status"] == "playing"
            assert play_mock.await_args.args[0]["position"] == "00:00:05"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_restart_stream_live(self):
        from gui_bridge import BridgeSession

        session = BridgeSession()
        session.current_session = {"kind": "live", "device": {"name": "TV", "device_type": "dlna", "ip": "1.1.1.1", "port": 5000}, "url": "https://example.com/live"}
        try:
            with patch.object(session, "play_live", new_callable=AsyncMock, return_value={"status": "playing"}) as play_mock:
                result = await session.restart_stream({"video_bitrate": "4500k"})
            assert result["status"] == "playing"
            assert play_mock.await_args.args[0]["video_bitrate"] == "4500k"
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_bridge_restart_stream_capture_uses_updated_fps(self):
        from gui_bridge import BridgeSession

        session = BridgeSession()
        session.current_session = {
            "kind": "screen",
            "device": {"name": "TV", "device_type": "dlna", "ip": "1.1.1.1", "port": 5000},
            "source_id": 1,
            "label": "screen",
            "fps": 10,
            "video_bitrate": "3500k",
        }
        try:
            with patch.object(session, "cast_capture", new_callable=AsyncMock, return_value={"status": "casting"}) as cast_mock:
                result = await session.restart_stream({"video_bitrate": "4500k", "fps": 25})
            assert result["status"] == "casting"
            assert cast_mock.await_args.args[0]["fps"] == 25
            assert cast_mock.await_args.args[0]["video_bitrate"] == "4500k"
        finally:
            session.close()
