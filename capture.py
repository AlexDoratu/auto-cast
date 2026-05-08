"""Screen and window capture for streaming to DLNA/AirPlay devices."""

import asyncio
import io
import time
import threading
from dataclasses import dataclass
from typing import Optional

import mss
import mss.tools
from PIL import Image
import win32gui
import win32con
import win32process
import psutil


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    pid: int
    rect: tuple[int, int, int, int]  # x, y, width, height
    is_visible: bool


def list_windows(include_minimized: bool = False) -> list[WindowInfo]:
    """List all visible windows with their info."""
    windows = []

    def enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd)
        if not title or title in ("", "Default IME", "MSCTFIME UI"):
            return True

        rect = win32gui.GetWindowRect(hwnd)
        x, y, right, bottom = rect
        width = right - x
        height = bottom - y

        if width < 100 or height < 100:
            return True

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process_name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = "Unknown"

        is_iconic = win32gui.IsIconic(hwnd)

        if not include_minimized and is_iconic:
            return True

        windows.append(WindowInfo(
            hwnd=hwnd,
            title=title,
            process_name=process_name,
            pid=pid,
            rect=(x, y, width, height),
            is_visible=not is_iconic,
        ))
        return True

    win32gui.EnumWindows(enum_callback, None)
    return windows


def get_monitors() -> list[dict]:
    """List available monitors/screens."""
    with mss.mss() as sct:
        monitors = []
        for i, mon in enumerate(sct.monitors):
            if i == 0:
                continue  # Skip "all in one" monitor
            monitors.append({
                "index": i,
                "left": mon["left"],
                "top": mon["top"],
                "width": mon["width"],
                "height": mon["height"],
                "name": f"Monitor {i} ({mon['width']}x{mon['height']})",
            })
        return monitors


def capture_window(hwnd: int, quality: int = 70, scale: float = 1.0) -> bytes:
    """Capture a specific window and return JPEG bytes."""
    try:
        rect = win32gui.GetWindowRect(hwnd)
        x, y, right, bottom = rect
        width = right - x
        height = bottom - y

        if width <= 0 or height <= 0:
            return b""

        with mss.mss() as sct:
            monitor = {"left": x, "top": y, "width": width, "height": height}
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            if scale < 1.0:
                img = img.resize(
                    (int(img.width * scale), int(img.height * scale)),
                    Image.Resampling.LANCZOS,
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
    except Exception:
        return b""


def capture_monitor(monitor_index: int = 1, quality: int = 70, scale: float = 1.0) -> bytes:
    """Capture a specific monitor and return JPEG bytes."""
    try:
        with mss.mss() as sct:
            if monitor_index >= len(sct.monitors):
                monitor_index = 1
            screenshot = sct.grab(sct.monitors[monitor_index])
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            if scale < 1.0:
                img = img.resize(
                    (int(img.width * scale), int(img.height * scale)),
                    Image.Resampling.LANCZOS,
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
    except Exception:
        return b""


class ScreenStreamer:
    """Continuously captures and serves frames via HTTP."""

    def __init__(self, fps: int = 10, quality: int = 70, bitrate_limit: int = 0):
        self.fps = fps
        self.quality = quality
        self.bitrate_limit = bitrate_limit  # KB/s, 0 = unlimited
        self._running = False
        self._frame: bytes = b""
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._target_hwnd: Optional[int] = None
        self._target_monitor: Optional[int] = None
        # Bitrate tracking
        self._bytes_sent: list[tuple[float, int]] = []
        self._current_quality = quality
        self._current_scale = 1.0

    def start_window(self, hwnd: int):
        """Start capturing a specific window."""
        self.stop()
        self._target_hwnd = hwnd
        self._target_monitor = None
        self._running = True
        self._bytes_sent = []
        self._current_quality = self.quality
        self._current_scale = 1.0
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def start_monitor(self, monitor_index: int = 1):
        """Start capturing a specific monitor."""
        self.stop()
        self._target_hwnd = None
        self._target_monitor = monitor_index
        self._running = True
        self._bytes_sent = []
        self._current_quality = self.quality
        self._current_scale = 1.0
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop capturing."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def get_frame(self) -> bytes:
        """Get the latest captured frame."""
        with self._lock:
            return self._frame

    def _track_bitrate(self, frame_size: int):
        """Track bitrate and adjust quality/scale dynamically."""
        now = time.time()
        self._bytes_sent.append((now, frame_size))
        # Keep last 1 second of data for faster reaction
        cutoff = now - 1.0
        self._bytes_sent = [(t, b) for t, b in self._bytes_sent if t > cutoff]

        if self.bitrate_limit <= 0:
            return

        # Calculate current bitrate (KB/s)
        if len(self._bytes_sent) < 2:
            return
        total_bytes = sum(b for _, b in self._bytes_sent)
        duration = self._bytes_sent[-1][0] - self._bytes_sent[0][0]
        if duration <= 0:
            return
        current_kbps = (total_bytes / 1024.0) / duration

        # Aggressive adjustment
        if current_kbps > self.bitrate_limit:
            if self._current_quality > 5:
                drop = 10 if current_kbps > self.bitrate_limit * 1.5 else 5
                self._current_quality = max(5, self._current_quality - drop)
            else:
                # Quality at minimum, scale down resolution
                self._current_scale = max(0.25, self._current_scale - 0.1)
        elif current_kbps < self.bitrate_limit * 0.7:
            if self._current_scale < 1.0:
                self._current_scale = min(1.0, self._current_scale + 0.05)
            else:
                self._current_quality = min(self.quality, self._current_quality + 1)

    def _capture_loop(self):
        """Main capture loop running in a thread."""
        interval = 1.0 / self.fps

        while self._running:
            start = time.time()

            try:
                if self._target_hwnd is not None:
                    frame = capture_window(self._target_hwnd, self._current_quality, self._current_scale)
                elif self._target_monitor is not None:
                    frame = capture_monitor(self._target_monitor, self._current_quality, self._current_scale)
                else:
                    frame = b""

                if frame:
                    self._track_bitrate(len(frame))
                    with self._lock:
                        self._frame = frame
            except Exception:
                pass

            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
