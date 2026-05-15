"""Temporary HTTP media server for DLNA streaming."""

import asyncio
import logging
import mimetypes
import os
import socket
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from uuid import uuid4

from aiohttp import web

from ffmpeg_transcoder import FFmpegTranscoder, TS_CONTENT_TYPE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveStreamSource:
    input_url: str
    input_format: str = "url"
    video_bitrate: str = "3500k"


class MediaServer:
    """Serves local media files over HTTP so DLNA renderers can pull them."""

    def __init__(self, host: str = "0.0.0.0", port: int = 0):
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/media/{filename}", self._handle_media)
        self._app.router.add_get("/live/{stream_id}.ts", self._handle_live_stream)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._actual_port: int = 0
        self._local_ip: str = ""
        self._registered_files: dict[str, str] = {}
        self._live_streams: dict[str, LiveStreamSource] = {}
        self._active_transcoders: list[FFmpegTranscoder] = []
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None

    async def start(self, target_ip: str = "8.8.8.8") -> tuple[str, int]:
        """Start the server and return (local_ip, port).

        Args:
            target_ip: IP of the target device, used to pick the correct local interface.
        """
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        self._actual_port = self._site._server.sockets[0].getsockname()[1]
        self._local_ip = self._get_local_ip(target_ip)

        logger.info(f"Media server started at http://{self._local_ip}:{self._actual_port}")
        return self._local_ip, self._actual_port

    async def stop(self):
        """Stop the media server."""
        for transcoder in list(self._active_transcoders):
            transcoder.stop()
        self._active_transcoders = []
        self._live_streams = {}
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
        logger.info("Media server stopped")

    def start_background(self, target_ip: str = "8.8.8.8") -> tuple[str, int]:
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run_background, args=(target_ip,), daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if self._start_error:
            raise self._start_error
        if not self._loop or not self._runner:
            raise RuntimeError("Media server did not start")
        return self._local_ip, self._actual_port

    def stop_background(self):
        loop = self._loop
        if not loop:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self.stop(), loop)
            future.result(timeout=10)
        except Exception as exc:
            logger.warning(f"Media server shutdown timed out or failed: {exc}")
        finally:
            loop.call_soon_threadsafe(loop.stop)
            if self._thread:
                self._thread.join(timeout=5)
                self._thread = None
            self._loop = None

    def get_url(self, filepath: str) -> str:
        """Get the HTTP URL for a local media file."""
        file_id = self.register_file(filepath)
        return f"http://{self._local_ip}:{self._actual_port}/media/{file_id}"

    def register_live_stream(self, input_url: str, input_format: str = "url", video_bitrate: str = "3500k") -> str:
        stream_id = uuid4().hex
        self._live_streams[stream_id] = LiveStreamSource(input_url, input_format=input_format, video_bitrate=video_bitrate)
        return f"http://{self._local_ip}:{self._actual_port}/live/{stream_id}.ts"

    async def _handle_live_stream(self, request: web.Request) -> web.StreamResponse:
        stream_id = request.match_info["stream_id"]
        source = self._live_streams.get(stream_id)
        if not source:
            raise web.HTTPNotFound(text="Live stream not found")
        transcoder = FFmpegTranscoder(source.input_url, input_format=source.input_format, video_bitrate=source.video_bitrate)
        self._active_transcoders.append(transcoder)

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": TS_CONTENT_TYPE,
                "Cache-Control": "no-cache",
                "Connection": "close",
            },
        )
        await response.prepare(request)
        try:
            await transcoder.write_to_response(response)
        except (asyncio.CancelledError, ConnectionError, BrokenPipeError):
            logger.debug(f"Live stream client disconnected: {stream_id}")
        except Exception as exc:
            logger.debug(f"Live stream response ended: {exc}")
        finally:
            transcoder.stop()
            if transcoder in self._active_transcoders:
                self._active_transcoders.remove(transcoder)
        return response

    def _run_background(self, target_ip: str):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.start(target_ip=target_ip))
        except Exception as exc:
            self._start_error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _handle_media(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        filepath = self._resolve_path(filename)

        if not filepath or not filepath.exists():
            raise web.HTTPNotFound(text=f"File not found: {filename}")

        content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"

        return web.FileResponse(
            path=filepath,
            headers={
                "Content-Type": content_type,
                "Accept-Ranges": "bytes",
            },
        )

    def _resolve_path(self, file_id: str) -> Optional[Path]:
        """Resolve file id to actual path from registered files."""
        filepath = self._registered_files.get(file_id)
        return Path(filepath) if filepath else None

    def register_file(self, filepath: str) -> str:
        """Register a file to be served."""
        abs_path = os.path.abspath(filepath)
        for file_id, registered_path in self._registered_files.items():
            if registered_path == abs_path:
                return file_id
        file_id = uuid4().hex + Path(abs_path).suffix.lower()
        self._registered_files[file_id] = abs_path
        return file_id

    def register_files(self, filepaths: list[str]):
        """Register multiple files."""
        for f in filepaths:
            self.register_file(f)

    @staticmethod
    def _get_local_ip(target_ip: str = "8.8.8.8") -> str:
        """Get the local IP address that can reach target_ip."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target_ip, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
