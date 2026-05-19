"""Resolve and cache regular video page URLs for seekable casting."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


CACHE_DIR = Path.home() / ".auto-cast" / "cache"
VIDEO_FORMAT = "bv*[vcodec^=avc1][height<=?720]+ba[acodec^=mp4a]/b[vcodec^=avc1][height<=?720]/b[height<=?720]"


def start_time_from_url(url: str) -> int:
    query = parse_qs(urlparse(url).query)
    value = query.get("t", ["0"])[0]
    if isinstance(value, str) and value.endswith("s"):
        value = value[:-1]
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def inspect_video_url(url: str) -> dict:
    if not yt_dlp:
        raise RuntimeError("yt-dlp is required to inspect video URLs")
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or info.get("fulltitle") or "Video",
        "duration": int(float(info.get("duration") or 0)),
        "duration_string": info.get("duration_string") or format_seconds(int(float(info.get("duration") or 0))),
        "id": info.get("id") or info.get("display_id") or "",
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
        "start_time": start_time_from_url(url),
    }


def cache_video_url(url: str, progress_callback: Callable[[dict], None] | None = None) -> dict:
    if not yt_dlp:
        raise RuntimeError("yt-dlp is required to cache video URLs")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()

    def emit_progress(payload: dict):
        if progress_callback:
            progress_callback(_with_estimated_percent(payload, started_at))

    if progress_callback:
        progress_callback({
            "status": "preparing",
            "phase": "Preparing download",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "percent": None,
            "speed": None,
            "eta": None,
            "filename": "",
        })
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": VIDEO_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(CACHE_DIR / "%(extractor_key)s-%(id)s.%(ext)s"),
        "restrictfilenames": True,
    }
    if progress_callback:
        options["progress_hooks"] = [lambda data: emit_progress(_progress_payload(data))]
    with yt_dlp.YoutubeDL(options) as ydl:
        if progress_callback:
            emit_progress({
                "status": "extracting",
                "phase": "Resolving video",
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "percent": None,
                "speed": None,
                "eta": None,
                "filename": "",
            })
        info = ydl.extract_info(url, download=True)
        filename = Path(ydl.prepare_filename(info))
    final_path = _merged_path(filename)
    if progress_callback:
        emit_progress({
            "status": "complete",
            "phase": "Complete",
            "downloaded_bytes": final_path.stat().st_size if final_path.exists() else 0,
            "total_bytes": final_path.stat().st_size if final_path.exists() else 0,
            "percent": 1.0,
            "speed": None,
            "eta": 0,
            "filename": str(final_path),
        })
    return {
        **inspect_video_url(url),
        "source_url": url,
        "path": str(final_path),
        "start_position": format_seconds(start_time_from_url(url)),
    }


def _merged_path(path: Path) -> Path:
    if path.exists():
        return path
    mp4 = path.with_suffix(".mp4")
    if mp4.exists():
        return mp4
    matches = sorted(path.parent.glob(f"{_glob_stem(path.stem)}.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    for item in matches:
        if item.suffix.lower() in {".mp4", ".mkv", ".webm"}:
            return item
    return path


def _glob_stem(stem: str) -> str:
    return re.sub(r"([*?\\[\\]])", r"[\1]", stem)


def _progress_payload(data: dict) -> dict:
    status = data.get("status") or "unknown"
    total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
    downloaded = data.get("downloaded_bytes") or 0
    fragment_index = _int_or_none(data.get("fragment_index"))
    fragment_count = _int_or_none(data.get("fragment_count"))
    if status == "finished" and total == 0 and downloaded:
        total = downloaded
    percent = (downloaded / total) if total else None
    if percent is None and fragment_index and fragment_count:
        percent = min(1.0, max(0.0, fragment_index / fragment_count))
    return {
        "status": status,
        "filename": data.get("filename") or "",
        "downloaded_bytes": downloaded,
        "total_bytes": total,
        "percent": percent,
        "fragment_index": fragment_index,
        "fragment_count": fragment_count,
        "speed": data.get("speed"),
        "eta": data.get("eta"),
        "phase": _phase_label(data),
    }


def _int_or_none(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _with_estimated_percent(payload: dict, started_at: float) -> dict:
    if payload.get("percent") is not None:
        return payload
    status = payload.get("status")
    if status not in {"preparing", "extracting", "downloading"}:
        return payload
    elapsed = max(0.0, time.monotonic() - started_at)
    # Unknown-size downloads still need visible activity. Cap below 95% until yt-dlp reports completion.
    estimate = min(0.95, 0.02 + elapsed / 180)
    return {**payload, "percent": estimate, "estimated": True}


def _phase_label(data: dict) -> str:
    status = data.get("status") or ""
    filename = str(data.get("filename") or "")
    if status == "finished":
        return "Merging" if filename else "Finishing"
    suffix = Path(filename).suffix.lower()
    if suffix in {".m4a", ".aac", ".mp3"}:
        return "Downloading audio"
    if suffix in {".mp4", ".m4s", ".webm", ".mkv"}:
        return "Downloading video"
    if status:
        return status.title()
    return "Preparing"
