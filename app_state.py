"""Persist small GUI resume state across app restarts."""

import json
import threading
from dataclasses import asdict, dataclass
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


def load_state(path: Path = STATE_PATH) -> ResumeState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ResumeState()
    if not isinstance(data, dict):
        return ResumeState()
    allowed = ResumeState.__dataclass_fields__.keys()
    cleaned = {key: data[key] for key in allowed if key in data}
    if "live_url" in cleaned:
        cleaned["live_url"] = redact_url(str(cleaned["live_url"]))
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
