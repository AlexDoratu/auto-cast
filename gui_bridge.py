"""Line-delimited JSON bridge for the Flutter GUI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from uuid import uuid4
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiohttp import web

import airplay_controller
import dlna_controller
from app_state import ResumeState, load_state, save_state, state_for_device, matches_device
from capture import ScreenStreamer, get_monitors, list_windows
from config import MIME_TYPES
from device import Device, DeviceType
from live_resolver import resolve_live_url
from media_server import MediaServer
from scanner import scan_all
from video_resolver import CACHE_DIR, cache_video_url, inspect_video_url

TV_STATUS_TIMEOUT_SECONDS = 2.5

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def device_to_json(device: Device) -> dict[str, Any]:
    data = asdict(device)
    capabilities = _device_capabilities(device)
    data["device_type"] = device.device_type.value
    data["display_type"] = _display_type_for_capabilities(capabilities)
    data["capabilities"] = capabilities
    return data


def device_from_json(data: dict[str, Any]) -> Device:
    services = list(data.get("services") if data.get("services") is not None else data.get("capabilities") or [])
    return Device(
        name=str(data.get("name", "")),
        device_type=DeviceType(str(data.get("device_type", "dlna"))),
        ip=str(data.get("ip", "")),
        port=int(data.get("port", 0)),
        control_url=data.get("control_url"),
        rendering_control_url=data.get("rendering_control_url"),
        manufacturer=str(data.get("manufacturer", "")),
        model=str(data.get("model", "")),
        uid=str(data.get("uid", "")),
        services=services,
    )


def _device_capabilities(device: Device) -> list[str]:
    known = {item.value for item in DeviceType}
    capabilities = []
    for item in device.services or []:
        value = str(item).lower()
        if value in known and value not in capabilities:
            capabilities.append(value)
    if device.device_type.value not in capabilities:
        capabilities.insert(0, device.device_type.value)
    return capabilities


def _display_type_for_capabilities(capabilities: list[str]) -> str:
    labels = {
        DeviceType.DLNA.value: "DLNA",
        DeviceType.AIRPLAY.value: "AirPlay",
        DeviceType.CHROMECAST.value: "Cast",
    }
    ordered = [item for item in [DeviceType.AIRPLAY.value, DeviceType.DLNA.value, DeviceType.CHROMECAST.value] if item in capabilities]
    if not ordered:
        return "Unknown"
    return " + ".join(labels[item] for item in ordered)


def _is_ip_name(value: str, ip: str) -> bool:
    return not value or value == ip or value.lower() == "unknown device"


def _merge_devices_by_ip(devices: list[Device]) -> list[Device]:
    merged: dict[str, Device] = {}
    order: list[str] = []

    for device in devices:
        if not device.ip:
            key = f"{device.device_type.value}:{device.name}:{device.port}"
        else:
            key = device.ip
        existing = merged.get(key)
        if not existing:
            merged[key] = Device(
                name=device.name,
                device_type=device.device_type,
                ip=device.ip,
                port=device.port,
                control_url=device.control_url,
                rendering_control_url=device.rendering_control_url,
                manufacturer=device.manufacturer,
                model=device.model,
                uid=device.uid,
                services=_device_capabilities(device),
            )
            order.append(key)
            continue

        capabilities = _device_capabilities(existing)
        for capability in _device_capabilities(device):
            if capability not in capabilities:
                capabilities.append(capability)

        if device.device_type == DeviceType.DLNA:
            existing.device_type = DeviceType.DLNA
            existing.port = device.port
            existing.control_url = device.control_url or existing.control_url
            existing.rendering_control_url = device.rendering_control_url or existing.rendering_control_url
            existing.uid = device.uid or existing.uid
            existing.manufacturer = device.manufacturer or existing.manufacturer
            existing.model = existing.model or device.model
            if _is_ip_name(existing.name, existing.ip) and not _is_ip_name(device.name, device.ip):
                existing.name = device.name
        else:
            if _is_ip_name(existing.name, existing.ip) and not _is_ip_name(device.name, device.ip):
                existing.name = device.name
            existing.model = existing.model or device.model
            existing.manufacturer = existing.manufacturer or device.manufacturer
            existing.uid = existing.uid or device.uid

        existing.services = capabilities

    return [merged[key] for key in order]


async def scan_devices_with_capabilities(timeout: float = 5.0) -> list[Device]:
    devices = await scan_all(timeout)
    ips_with_dlna = {device.ip for device in devices if device.device_type == DeviceType.DLNA and device.ip}
    probe_targets = [device for device in devices if device.ip and device.device_type != DeviceType.DLNA and device.ip not in ips_with_dlna]
    if not probe_targets:
        return _merge_devices_by_ip(devices)

    semaphore = asyncio.Semaphore(4)
    probe_timeout = min(4.0, max(1.0, timeout))

    async def probe(device: Device) -> Device | None:
        async with semaphore:
            try:
                return await asyncio.wait_for(dlna_controller.discover_dlna(device.ip), timeout=probe_timeout)
            except Exception:
                return None

    discovered = await asyncio.gather(*(probe(device) for device in probe_targets))
    devices.extend(device for device in discovered if device)
    return _merge_devices_by_ip(devices)


def window_to_json(window) -> dict[str, Any]:
    return {
        "hwnd": window.hwnd,
        "title": window.title,
        "process_name": window.process_name,
        "pid": window.pid,
        "rect": list(window.rect),
        "is_visible": window.is_visible,
    }


def _position_to_seconds(position: str) -> int:
    parts = str(position or "").split(":")
    if len(parts) != 3:
        return 0
    try:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(float(seconds))
    except ValueError:
        return 0


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pick_media_file() -> dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(f"File picker is unavailable: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(
            title="Choose media file",
            filetypes=[
                ("Media files", "*.mp4 *.mkv *.avi *.mov *.webm *.mp3 *.wav *.flac *.aac *.ogg *.jpg *.jpeg *.png *.gif *.bmp"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()
    return {"path": path or ""}


class BridgeSession:
    def __init__(self, event_sink=None):
        self.media_server: MediaServer | None = None
        self.playback_device: Device | None = None
        self.streamer = ScreenStreamer(fps=10, quality=70)
        self.is_streaming = False
        self.generation = 0
        self._lock = threading.RLock()
        self.state = load_state()
        self.event_sink = event_sink
        self.last_download_progress: dict[str, Any] | None = None
        self.download_tasks: dict[str, dict[str, Any]] = {}
        self.current_session: dict[str, Any] = {}

    def close(self):
        self.generation += 1
        self.streamer.stop()
        self.is_streaming = False
        self._stop_server()

    async def handle(self, command: dict[str, Any]) -> dict[str, Any]:
        name = str(command.get("command", ""))
        if name == "scan":
            timeout = float(command.get("timeout", 5.0))
            devices = await scan_devices_with_capabilities(timeout)
            return {"devices": [device_to_json(item) for item in devices]}
        if name == "windows":
            return {"windows": [window_to_json(item) for item in list_windows()]}
        if name == "monitors":
            return {"monitors": get_monitors()}
        if name == "pick_file":
            return await asyncio.to_thread(pick_media_file)
        if name == "state":
            return {
                "state": asdict(self.state),
                "playing": self.playback_device is not None,
                "cache_dir": str(CACHE_DIR),
            }
        if name == "playback_status":
            return await self.playback_status()
        if name == "resume_last":
            timeout = float(command.get("timeout", 5.0))
            return await self.resume_last(timeout)
        if name == "restart_stream":
            return await self.restart_stream(command)
        if name == "play_media":
            return await self.play_media(command)
        if name == "play_live":
            return await self.play_live(command)
        if name == "inspect_video":
            return await asyncio.to_thread(inspect_video_url, str(command.get("url", "")))
        if name == "cache_video":
            return self.start_cache_video(str(command.get("url", "")))
        if name == "cancel_cache":
            return self.cancel_cache(str(command.get("task_id", "")))
        if name == "play_cached_video":
            return await self.play_cached_video(command)
        if name == "cast_window":
            return await self.cast_capture(command, "window")
        if name == "cast_screen":
            return await self.cast_capture(command, "screen")
        if name == "stop":
            return await self.stop()
        if name == "set_volume":
            return await self.set_volume(command)
        if name == "seek":
            return await self.seek(command)
        raise ValueError(f"Unknown command: {name}")

    async def play_media(self, command: dict[str, Any]) -> dict[str, Any]:
        device = device_from_json(command["device"])
        media_path = str(command.get("path", ""))
        position = str(command.get("position", "") or "")
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(media_path)
        content_type = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
        generation = self._next_generation()
        self._stop_server()

        if device.device_type == DeviceType.DLNA:
            server = MediaServer()
            try:
                server.start_background(target_ip=device.ip)
                url = server.get_url(media_path)
                self._store_server_if_current(server, generation)
                await dlna_controller.play(device, url, content_type)
                self._set_playback_device(device, generation)
            except Exception:
                self._drop_server(server)
                raise
            if position:
                await dlna_controller.seek(device, position)
            self._remember(device, "media", media_path=media_path, position=position)
            self.current_session = {"kind": "media", "device": device_to_json(device), "path": media_path, "position": position}
            return {"status": "playing", "url": url, "position": position}

        if device.device_type == DeviceType.AIRPLAY:
            try:
                await airplay_controller.play(device, media_path)
                self._set_playback_device(device, generation)
                self._remember(device, "media", media_path=media_path)
                self.current_session = {"kind": "media", "device": device_to_json(device), "path": media_path, "position": position}
                return {"status": "playing", "transport": "airplay"}
            except Exception:
                dlna_device = await self._dlna_target(device)
                result = await self._play_dlna_file(dlna_device, media_path)
                if position:
                    await dlna_controller.seek(dlna_device, position)
                self._remember(dlna_device, "media", media_path=media_path, position=position)
                self.current_session = {"kind": "media", "device": device_to_json(dlna_device), "path": media_path, "position": position}
                return {**result, "transport": "dlna-fallback", "position": position}

        raise RuntimeError(f"Unsupported device type: {device.device_type.value}")

    def _cache_video_with_progress(self, url: str) -> dict[str, Any]:
        def on_progress(payload: dict):
            self.last_download_progress = payload
            self._emit_event("download_progress", payload)

        result = cache_video_url(url, on_progress)
        self.last_download_progress = {**result, "status": "complete", "phase": "Complete", "percent": 1.0}
        self._emit_event("download_complete", result)
        return result

    def start_cache_video(self, url: str) -> dict[str, Any]:
        if not url.strip():
            raise ValueError("Video URL is empty")
        task_id = uuid4().hex
        cancel_event = threading.Event()
        task = {
            "id": task_id,
            "url": url,
            "status": "running",
            "cancel": cancel_event,
            "result": None,
            "error": "",
        }
        self.download_tasks[task_id] = task
        thread = threading.Thread(target=self._run_cache_task, args=(task_id,), daemon=True)
        task["thread"] = thread
        thread.start()
        return {"task_id": task_id, "status": "started"}

    def cancel_cache(self, task_id: str) -> dict[str, Any]:
        task = self.download_tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found"}
        task["cancel"].set()
        task["status"] = "cancel_requested"
        self._emit_event("download_cancel_requested", {"task_id": task_id})
        return {"task_id": task_id, "status": "cancel_requested"}

    def _run_cache_task(self, task_id: str):
        task = self.download_tasks[task_id]
        url = task["url"]
        cancel_event: threading.Event = task["cancel"]

        def on_progress(payload: dict):
            payload = {**payload, "task_id": task_id}
            if cancel_event.is_set():
                raise RuntimeError("Download cancelled")
            self.last_download_progress = payload
            self._emit_event("download_progress", payload)

        try:
            result = cache_video_url(url, on_progress)
            result = {**result, "task_id": task_id}
            task["status"] = "completed"
            task["result"] = result
            self.last_download_progress = {**result, "status": "complete", "phase": "Complete", "percent": 1.0}
            self._emit_event("download_complete", result)
        except Exception as exc:
            status = "cancelled" if cancel_event.is_set() or "cancelled" in str(exc).lower() else "failed"
            task["status"] = status
            task["error"] = str(exc)
            self.last_download_progress = None
            self._emit_event("download_failed", {"task_id": task_id, "status": status, "error": str(exc)})

    async def play_cached_video(self, command: dict[str, Any]) -> dict[str, Any]:
        device = await self._dlna_target(device_from_json(command["device"]))
        media_path = str(command.get("path", ""))
        position = str(command.get("position", ""))
        result = await self._play_dlna_file(device, media_path)
        if position:
            await dlna_controller.seek(device, position)
        self._remember(device, "media", media_path=media_path, position=position)
        self.current_session = {"kind": "media", "device": device_to_json(device), "path": media_path, "position": position}
        return {**result, "position": position}

    async def _play_dlna_file(self, device: Device, media_path: str) -> dict[str, Any]:
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(media_path)
        content_type = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
        generation = self._next_generation()
        self._stop_server()
        server = MediaServer()
        try:
            server.start_background(target_ip=device.ip)
            url = server.get_url(media_path)
            self._store_server_if_current(server, generation)
            await dlna_controller.play(device, url, content_type)
            self._set_playback_device(device, generation)
        except Exception:
            self._drop_server(server)
            raise
        return {"status": "playing", "url": url}

    async def play_live(self, command: dict[str, Any]) -> dict[str, Any]:
        device = await self._dlna_target(device_from_json(command["device"]))
        live_url = str(command.get("url", "")).strip()
        bitrate = str(command.get("video_bitrate", "3500k"))
        if not live_url:
            raise ValueError("Live URL is empty")
        generation = self._next_generation()
        self._stop_server()

        stream_url, _content_type = resolve_live_url(live_url)
        server = MediaServer()
        try:
            server.start_background(target_ip=device.ip)
            transcoded_url = server.register_live_stream(stream_url, video_bitrate=bitrate)
            self._store_server_if_current(server, generation)
            await dlna_controller.play(device, transcoded_url, "video/mp2t")
            self._set_playback_device(device, generation)
        except Exception:
            self._drop_server(server)
            raise
        self._remember(device, "live", live_url=live_url)
        self.current_session = {"kind": "live", "device": device_to_json(device), "url": live_url, "video_bitrate": bitrate}
        return {"status": "playing", "url": transcoded_url}

    async def cast_capture(self, command: dict[str, Any], source_type: str) -> dict[str, Any]:
        device = await self._dlna_target(device_from_json(command["device"]))
        source_id = int(command.get("hwnd" if source_type == "window" else "monitor_index", 1))
        label = str(command.get("label", source_type))
        fps = max(1, min(30, int(command.get("fps", 10))))
        bitrate = str(command.get("video_bitrate", "3500k"))
        generation = self._next_generation()
        self._stop_server()

        self.streamer.fps = fps
        if source_type == "window":
            self.streamer.start_window(source_id)
        else:
            self.streamer.start_monitor(source_id)
        self.is_streaming = True

        server = MediaServer()
        streamer = self.streamer

        async def stream_handle(_request):
            response = web.StreamResponse(
                status=200,
                reason="OK",
                headers={
                    "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
            await response.prepare(_request)
            while self.is_streaming and generation == self.generation:
                frame = streamer.get_frame()
                if frame:
                    await response.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                    )
                await asyncio.sleep(1 / fps)
            return response

        try:
            server._app.router.add_get("/stream", stream_handle)
            server.start_background(target_ip=device.ip)
            stream_url = f"http://{server._local_ip}:{server._actual_port}/stream"
            transcoded_url = server.register_live_stream(stream_url, input_format="mjpeg", video_bitrate=bitrate)
            self._store_server_if_current(server, generation)
            await dlna_controller.play(device, transcoded_url, "video/mp2t")
            self._set_playback_device(device, generation)
        except Exception:
            self.streamer.stop()
            self.is_streaming = False
            self._drop_server(server)
            raise
        self._remember(device, source_type, capture_label=label)
        self.current_session = {
            "kind": source_type,
            "device": device_to_json(device),
            "source_id": source_id,
            "label": label,
            "fps": fps,
            "video_bitrate": bitrate,
        }
        return {"status": "casting", "url": transcoded_url}

    async def stop(self) -> dict[str, Any]:
        device = self.playback_device
        self.generation += 1
        self.streamer.stop()
        self.is_streaming = False
        self._stop_server()
        self.playback_device = None
        if device and device.device_type == DeviceType.DLNA:
            await dlna_controller.stop(device)
        elif device and device.device_type == DeviceType.AIRPLAY:
            await airplay_controller.stop(device)
        return {"status": "stopped"}

    async def set_volume(self, command: dict[str, Any]) -> dict[str, Any]:
        device = self.playback_device or device_from_json(command["device"])
        volume = max(0, min(100, int(command.get("volume", 70))))
        if device.device_type == DeviceType.DLNA:
            await dlna_controller.set_volume(device, volume)
        elif device.device_type == DeviceType.AIRPLAY:
            await airplay_controller.set_volume(device, volume)
        else:
            raise RuntimeError(f"Volume is unsupported for {device.device_type.value}")
        return {"status": "ok", "volume": volume}

    async def resume_last(self, timeout: float = 5.0) -> dict[str, Any]:
        self.state = load_state()
        if not self.state.auto_resume_enabled or not self.state.source_type:
            return {"status": "skipped", "reason": "No resumable state"}
        devices = await scan_devices_with_capabilities(timeout)
        matched = next((device for device in devices if matches_device(self.state, device)), None)
        if not matched:
            return {"status": "searching", "reason": "Last device not found", "devices": [device_to_json(item) for item in devices]}

        if self.state.source_type == "media" and self.state.media_path:
            return await self.play_media({
                "device": device_to_json(matched),
                "path": self.state.media_path,
                "position": self.state.position,
            })
        if self.state.source_type == "live" and self.state.live_url:
            return await self.play_live({
                "device": device_to_json(matched),
                "url": self.state.live_url,
            })
        if self.state.source_type == "screen":
            monitors = get_monitors()
            if not monitors:
                return {"status": "skipped", "reason": "No monitor found"}
            return await self.cast_capture({
                "device": device_to_json(matched),
                "monitor_index": monitors[0]["index"],
                "label": monitors[0]["name"],
            }, "screen")
        return {"status": "skipped", "reason": f"Resume unsupported for {self.state.source_type}"}

    async def restart_stream(self, command: dict[str, Any]) -> dict[str, Any]:
        bitrate = str(command.get("video_bitrate", "3500k"))
        session = dict(self.current_session)
        kind = session.get("kind")
        if kind == "live":
            return await self.play_live({
                "device": session["device"],
                "url": session["url"],
                "video_bitrate": bitrate,
            })
        if kind in {"window", "screen"}:
            return await self.cast_capture({
                "device": session["device"],
                "hwnd": session.get("source_id"),
                "monitor_index": session.get("source_id"),
                "label": session.get("label", kind),
                "fps": session.get("fps", 10),
                "video_bitrate": bitrate,
            }, kind)
        return {"status": "skipped", "reason": "Current playback is not a restartable stream"}

    async def seek(self, command: dict[str, Any]) -> dict[str, Any]:
        device = self.playback_device
        if not device:
            raise RuntimeError("No active playback device")
        if device.device_type != DeviceType.DLNA:
            raise RuntimeError("Seek is only supported for DLNA playback")
        position = str(command.get("position", ""))
        if not position:
            seconds = int(command.get("seconds", 0))
            position = _format_seconds(seconds)
        await dlna_controller.seek(device, position)
        return {"status": "ok", "position": position}

    async def playback_status(self) -> dict[str, Any]:
        device = self.playback_device
        if not device:
            return {
                "playing": False,
                "state": "IDLE",
                "status": "No active playback",
                "position": "",
                "duration": "",
                "position_seconds": 0,
                "duration_seconds": 0,
                "volume": None,
                "device": None,
                "source_type": self.state.source_type,
                "streaming": self.is_streaming,
                "generation": self.generation,
                "download": self.last_download_progress,
                "checked_at": time.time(),
                "latency_ms": None,
            }

        base = {
            "playing": True,
            "state": "UNKNOWN",
            "status": "",
            "position": "",
            "duration": "",
            "position_seconds": 0,
            "duration_seconds": 0,
            "volume": None,
            "device": device_to_json(device),
            "source_type": self.state.source_type,
            "streaming": self.is_streaming,
            "generation": self.generation,
            "download": self.last_download_progress,
            "checked_at": time.time(),
            "latency_ms": None,
        }
        if device.device_type != DeviceType.DLNA:
            base.update({
                "state": "PLAYING",
                "status": f"{device.display_type} playback active; detailed transport status is unavailable",
            })
            return base

        started = time.perf_counter()
        position_info, transport_info, volume = await asyncio.gather(
            self._tv_query("position", dlna_controller.get_position_info(device), {}),
            self._tv_query("transport", dlna_controller.get_transport_info(device), {}),
            self._tv_query("volume", dlna_controller.get_volume(device), "?"),
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        position = position_info.get("RelTime", "") or "00:00:00"
        duration = position_info.get("TrackDuration", "") or ""
        transport_state = transport_info.get("CurrentTransportState", "") or "UNKNOWN"
        transport_status = transport_info.get("CurrentTransportStatus", "") or ""
        base.update({
            "state": transport_state,
            "status": transport_status,
            "position": position,
            "duration": duration,
            "position_seconds": _position_to_seconds(position),
            "duration_seconds": _position_to_seconds(duration),
            "volume": _parse_int(volume),
            "checked_at": time.time(),
            "latency_ms": latency_ms,
        })
        return base

    async def _tv_query(self, label: str, awaitable, fallback):
        try:
            return await asyncio.wait_for(awaitable, timeout=TV_STATUS_TIMEOUT_SECONDS)
        except Exception:
            return fallback

    async def _dlna_target(self, device: Device) -> Device:
        if device.device_type == DeviceType.DLNA:
            return device
        discovered = await dlna_controller.discover_dlna(device.ip)
        if not discovered:
            raise RuntimeError(f"No DLNA service found on {device.ip}")
        return discovered

    def _next_generation(self) -> int:
        with self._lock:
            self.generation += 1
            return self.generation

    def _store_server_if_current(self, server: MediaServer, generation: int):
        with self._lock:
            if generation != self.generation:
                server.stop_background()
                raise RuntimeError("Playback was superseded")
            self.media_server = server

    def _set_playback_device(self, device: Device, generation: int):
        with self._lock:
            if generation != self.generation:
                raise RuntimeError("Playback was superseded")
            self.playback_device = device

    def _stop_server(self):
        with self._lock:
            server = self.media_server
            self.media_server = None
        if server:
            server.stop_background()

    def _drop_server(self, server: MediaServer):
        with self._lock:
            if self.media_server is server:
                self.media_server = None
        server.stop_background()

    def _remember(self, device: Device, source_type: str, **values):
        self.state = state_for_device(device, source_type, **values)
        save_state(self.state)

    def _emit_event(self, name: str, payload: dict[str, Any]):
        if self.event_sink:
            self.event_sink({"event": name, "payload": payload})


async def run_stdio():
    def emit(message: dict[str, Any]):
        print(json.dumps(message, ensure_ascii=False), flush=True)

    session = BridgeSession(event_sink=emit)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            request_id = None
            try:
                command = json.loads(line)
                request_id = command.get("id")
                result = await session.handle(command)
                print(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(
                    json.dumps(
                        {"id": request_id, "ok": False, "error": str(exc), "error_type": type(exc).__name__},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        session.close()


async def run_once(command: dict[str, Any]):
    session = BridgeSession()
    try:
        result = await session.handle(command)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Auto-Cast JSON bridge")
    parser.add_argument("--stdio", action="store_true", help="Run as a persistent line-delimited JSON bridge")
    parser.add_argument("--command", help="Run one JSON command and exit")
    args = parser.parse_args()
    if args.stdio:
        asyncio.run(run_stdio())
    elif args.command:
        asyncio.run(run_once(json.loads(args.command)))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
