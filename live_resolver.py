"""Resolve live page URLs into playable media stream URLs."""

import shutil
import subprocess
from urllib.parse import urlparse


HLS_CONTENT_TYPE = "application/vnd.apple.mpegurl"
DEFAULT_CONTENT_TYPE = "video/mp4"


def resolve_live_url(url: str) -> tuple[str, str]:
    normalized_url = url.strip()
    if not normalized_url:
        raise ValueError("Live URL is empty")
    if not _is_http_url(normalized_url):
        raise ValueError("Live URL must start with http:// or https://")

    resolved_url = _resolve_with_streamlink(normalized_url) or _resolve_with_ytdlp(normalized_url)
    if not resolved_url:
        raise RuntimeError("Could not resolve live stream URL. Install streamlink or yt-dlp, or use a direct media stream URL.")
    return resolved_url, guess_content_type(resolved_url)


def guess_content_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".m3u8"):
        return HLS_CONTENT_TYPE
    if path.endswith(".flv"):
        return "video/x-flv"
    if path.endswith(".ts"):
        return "video/mp2t"
    if path.endswith(".mp4"):
        return "video/mp4"
    return DEFAULT_CONTENT_TYPE


def _resolve_with_streamlink(url: str) -> str | None:
    executable = shutil.which("streamlink")
    if not executable:
        return None
    return _run_resolver([executable, url, "best", "--stream-url"])


def _resolve_with_ytdlp(url: str) -> str | None:
    executable = shutil.which("yt-dlp")
    if not executable:
        return None
    return _run_resolver([executable, "-g", url])


def _run_resolver(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        stream_url = line.strip()
        if _is_http_url(stream_url):
            return stream_url
    return None


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
