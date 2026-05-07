"""Configuration management for auto-cast."""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    scan_timeout: float = 5.0
    media_server_host: str = "0.0.0.0"
    media_server_port: int = 0
    default_device_type: str | None = None
    verbose: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            scan_timeout=float(os.environ.get("AUTOCAST_SCAN_TIMEOUT", "5.0")),
            media_server_host=os.environ.get("AUTOCAST_SERVER_HOST", "0.0.0.0"),
            media_server_port=int(os.environ.get("AUTOCAST_SERVER_PORT", "0")),
            default_device_type=os.environ.get("AUTOCAST_DEVICE_TYPE"),
            verbose=os.environ.get("AUTOCAST_VERBOSE", "").lower() in ("1", "true", "yes"),
        )


SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
}

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}
