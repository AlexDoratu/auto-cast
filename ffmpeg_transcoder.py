"""FFmpeg-backed live stream transcoding for DLNA playback."""

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass, field

from aiohttp import web

logger = logging.getLogger(__name__)

TS_CONTENT_TYPE = "video/mp2t"
DEFAULT_VIDEO_BITRATE = "3500k"
DEFAULT_BUFFER_SIZE = "7000k"
DEFAULT_GOP_SIZE = "60"


@dataclass
class FFmpegTranscoder:
    input_url: str
    input_format: str = "url"
    video_bitrate: str = DEFAULT_VIDEO_BITRATE
    process: subprocess.Popen | None = field(default=None, init=False)

    def start(self):
        if self.process and self.process.poll() is None:
            return
        executable = shutil.which("ffmpeg")
        if not executable:
            raise RuntimeError("FFmpeg not found. Install FFmpeg and make sure ffmpeg is in PATH.")

        self.process = subprocess.Popen(
            build_ffmpeg_command(executable, self.input_url, self.input_format, self.video_bitrate),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    async def write_to_response(self, response: web.StreamResponse):
        self.start()
        if not self.process or not self.process.stdout:
            raise RuntimeError("FFmpeg did not start")

        while self.process.poll() is None:
            chunk = await asyncio.to_thread(self.process.stdout.read, 64 * 1024)
            if not chunk:
                break
            await response.write(chunk)

    def stop(self):
        process = self.process
        self.process = None
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def build_ffmpeg_command(
    executable: str,
    input_url: str,
    input_format: str = "url",
    video_bitrate: str = DEFAULT_VIDEO_BITRATE,
) -> list[str]:
    input_options = _input_options(input_format)
    return [
        executable,
        "-hide_banner",
        "-loglevel", "warning",
        *input_options,
        "-i", input_url,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-b:v", video_bitrate,
        "-maxrate", video_bitrate,
        "-bufsize", _buffer_size(video_bitrate),
        "-g", DEFAULT_GOP_SIZE,
        "-keyint_min", DEFAULT_GOP_SIZE,
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-f", "mpegts",
        "pipe:1",
    ]


def _buffer_size(video_bitrate: str) -> str:
    if video_bitrate.endswith("k") and video_bitrate[:-1].isdigit():
        return f"{int(video_bitrate[:-1]) * 2}k"
    return DEFAULT_BUFFER_SIZE


def _input_options(input_format: str) -> list[str]:
    if input_format == "mjpeg":
        return ["-f", "mpjpeg"]
    return [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
    ]
