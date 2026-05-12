"""Persist small GUI resume state across app restarts."""

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from device import Device

_STATE_LOCK = threading.Lock()

STATE_PATH = Path.home() / ".auto-cast" / "state.json"


@dataclass(frozen=True)
class ResumeState:
    auto_resume_enabled: bool = True
    device_name: str = ""
    device_type: str = ""
    device_ip: str = ""
    device_uid: str = ""
    source_type: str = ""
    media_path: str = ""
    live_url: str = ""
    capture_label: str = ""
    queue: list[str] = field(default_factory=list)
    queue_index: int = 0
    position: str = ""


def load_state(path: Path = STATE_PATH) -> ResumeState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ResumeState()
    if not isinstance(data, dict):
        return ResumeState()
    allowed = ResumeState.__dataclass_fields__.keys()
    cleaned = {key: data[key] for key in allowed if key in data}
    for key in ["device_name", "device_type", "device_ip", "device_uid", "source_type", "media_path", "live_url", "capture_label"]:
        if key in cleaned and not isinstance(cleaned[key], str):
            cleaned[key] = ""
    if "auto_resume_enabled" in cleaned and not isinstance(cleaned["auto_resume_enabled"], bool):
        cleaned["auto_resume_enabled"] = True
    if "live_url" in cleaned:
        cleaned["live_url"] = redact_url(cleaned["live_url"])
    if "queue" in cleaned and not isinstance(cleaned["queue"], list):
        cleaned["queue"] = []
    if "queue" in cleaned:
        cleaned["queue"] = [str(item) for item in cleaned["queue"]]
    if "queue_index" in cleaned and not isinstance(cleaned["queue_index"], int):
        cleaned["queue_index"] = 0
    if "position" in cleaned and not isinstance(cleaned["position"], str):
        cleaned["position"] = ""
    return ResumeState(**cleaned)


def save_state(state: ResumeState, path: Path = STATE_PATH):
    data = json.dumps(asdict(state), ensure_ascii=False, indent=2)
    with _STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(data, encoding="utf-8")
        temp_path.replace(path)


def state_for_device(device: Device, source_type: str, **values) -> ResumeState:
    return ResumeState(
        device_name=device.name,
        device_type=device.device_type.value,
        device_ip=device.ip,
        device_uid=device.uid or "",
        source_type=source_type,
        media_path=values.get("media_path", ""),
        live_url=values.get("live_url", ""),
        capture_label=values.get("capture_label", ""),
        queue=list(values.get("queue", [])),
        queue_index=values.get("queue_index", 0),
        position=values.get("position", ""),
    )


def matches_device(state: ResumeState, device: Device) -> bool:
    if not state.auto_resume_enabled or not state.device_ip:
        return False
    if state.device_uid and device.uid:
        return state.device_ip == device.ip and state.device_uid == device.uid
    return state.device_ip == device.ip and bool(state.device_name) and state.device_name == device.name


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
