"""Temporary HTTP media server for DLNA streaming."""

import asyncio
import logging
import mimetypes
import os
import socket
from pathlib import Path
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)


class MediaServer:
    """Serves local media files over HTTP so DLNA renderers can pull them."""

    def __init__(self, host: str = "0.0.0.0", port: int = 0):
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/media/{filename}", self._handle_media)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._actual_port: int = 0
        self._local_ip: str = ""
        self._registered_files: list[str] = []

    async def start(self) -> tuple[str, int]:
        """Start the server and return (local_ip, port)."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

        self._actual_port = self._site._server.sockets[0].getsockname()[1]
        self._local_ip = self._get_local_ip()

        logger.info(f"Media server started at http://{self._local_ip}:{self._actual_port}")
        return self._local_ip, self._actual_port

    async def stop(self):
        """Stop the media server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
        logger.info("Media server stopped")

    def get_url(self, filepath: str) -> str:
        """Get the HTTP URL for a local media file."""
        filename = os.path.basename(filepath)
        return f"http://{self._local_ip}:{self._actual_port}/media/{filename}"

    async def _handle_media(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        filepath = self._resolve_path(filename)

        if not filepath or not filepath.exists():
            raise web.HTTPNotFound(text=f"File not found: {filename}")

        content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        file_size = filepath.stat().st_size

        return web.FileResponse(
            path=filepath,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    def _resolve_path(self, filename: str) -> Optional[Path]:
        """Resolve filename to actual path from registered files."""
        for registered in self._registered_files:
            if os.path.basename(registered) == filename:
                return Path(registered)
        return None

    def register_file(self, filepath: str):
        """Register a file to be served."""
        abs_path = os.path.abspath(filepath)
        if abs_path not in self._registered_files:
            self._registered_files.append(abs_path)

    def register_files(self, filepaths: list[str]):
        """Register multiple files."""
        for f in filepaths:
            self.register_file(f)

    @staticmethod
    def _get_local_ip() -> str:
        """Get the local IP address that can reach the network."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
