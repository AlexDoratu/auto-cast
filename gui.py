"""Auto-Cast GUI — Modern PySide6 interface for DLNA/AirPlay casting."""

import asyncio
import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSlider, QFrame, QProgressBar, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QPainter, QLinearGradient

from device import Device, DeviceType
from scanner import scan_all, scan_by_type
from media_server import MediaServer
import dlna_controller
import airplay_controller
from config import SUPPORTED_EXTENSIONS, MIME_TYPES


# ── Signals Bridge ──────────────────────────────────────────────────────────

class SignalBridge(QObject):
    devices_found = Signal(list)
    status_update = Signal(str)
    error_occurred = Signal(str)


# ── Async Worker ────────────────────────────────────────────────────────────

class AsyncWorker(threading.Thread):
    def __init__(self, coro, callback=None, error_callback=None):
        super().__init__(daemon=True)
        self._coro = coro
        self._callback = callback
        self._error_callback = error_callback

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self._coro)
            if self._callback:
                self._callback(result)
        except Exception as e:
            if self._error_callback:
                self._error_callback(str(e))


# ── Styles ──────────────────────────────────────────────────────────────────

DARK_STYLE = """
QMainWindow {
    background-color: #1a1a2e;
}

QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}

QPushButton {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #0f3460;
    border: 1px solid #533483;
}

QPushButton:pressed {
    background-color: #533483;
}

QPushButton#primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e94560, stop:1 #533483);
    color: white;
    border: none;
    font-size: 14px;
}

QPushButton#primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6b6b, stop:1 #6c5ce7);
}

QPushButton#dangerBtn {
    background-color: #c0392b;
    border: none;
}

QPushButton#dangerBtn:hover {
    background-color: #e74c3c;
}

QTableWidget {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    gridline-color: #0f3460;
    selection-background-color: #533483;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #0f3460;
}

QTableWidget::item:selected {
    background-color: #533483;
    color: white;
}

QHeaderView::section {
    background-color: #0f3460;
    color: #e0e0e0;
    padding: 10px;
    border: none;
    border-bottom: 2px solid #e94560;
    font-weight: bold;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #0f3460;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #e94560;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e94560, stop:1 #533483);
    border-radius: 3px;
}

QProgressBar {
    background-color: #0f3460;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: white;
    height: 8px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e94560, stop:1 #533483);
    border-radius: 4px;
}

QLabel#title {
    font-size: 24px;
    font-weight: bold;
    color: #e94560;
}

QLabel#subtitle {
    color: #888;
    font-size: 12px;
}

QLabel#status {
    color: #533483;
    font-weight: bold;
}

QFrame#card {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 12px;
    padding: 16px;
}

QFrame#separator {
    background-color: #0f3460;
    max-height: 1px;
}
"""


# ── Main Window ─────────────────────────────────────────────────────────────

class AutoCastGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.devices: list[Device] = []
        self.selected_device: Device | None = None
        self.media_path: str | None = None
        self.media_server: MediaServer | None = None
        self.is_playing = False
        self.bridge = SignalBridge()

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        self.setWindowTitle("Auto-Cast")
        self.setMinimumSize(900, 650)
        self.resize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("Auto-Cast")
        title.setObjectName("title")
        subtitle = QLabel("DLNA / AirPlay / Chromecast")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        # ── Separator ──
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── Content Area ──
        content = QHBoxLayout()
        content.setSpacing(16)

        # Left: Device list
        left_panel = QFrame()
        left_panel.setObjectName("card")
        left_layout = QVBoxLayout(left_panel)

        device_header = QHBoxLayout()
        device_label = QLabel("Devices")
        device_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e94560;")
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setFixedWidth(100)
        device_header.addWidget(device_label)
        device_header.addStretch()
        device_header.addWidget(self.scan_btn)
        left_layout.addLayout(device_header)

        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["Name", "Type", "IP", "Status"])
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self.device_table)

        self.device_count = QLabel("0 devices found")
        self.device_count.setObjectName("subtitle")
        left_layout.addWidget(self.device_count)

        content.addWidget(left_panel, stretch=2)

        # Right: Controls
        right_panel = QFrame()
        right_panel.setObjectName("card")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(20)

        # Media selection
        media_label = QLabel("Media File")
        media_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e94560;")
        right_layout.addWidget(media_label)

        self.media_path_label = QLabel("No file selected")
        self.media_path_label.setObjectName("subtitle")
        self.media_path_label.setWordWrap(True)
        right_layout.addWidget(self.media_path_label)

        self.browse_btn = QPushButton("Browse...")
        right_layout.addWidget(self.browse_btn)

        # Separator
        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(sep2)

        # Playback controls
        play_label = QLabel("Playback")
        play_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #e94560;")
        right_layout.addWidget(play_label)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primaryBtn")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("dangerBtn")
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.stop_btn)
        right_layout.addLayout(btn_row)

        # Volume
        vol_label = QLabel("Volume")
        vol_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(vol_label)

        vol_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_value = QLabel("70%")
        self.volume_value.setFixedWidth(40)
        vol_row.addWidget(self.volume_slider)
        vol_row.addWidget(self.volume_value)
        right_layout.addLayout(vol_row)

        right_layout.addStretch()

        content.addWidget(right_panel, stretch=1)
        layout.addLayout(content, stretch=1)

        # ── Status Bar ──
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        self.scan_btn.clicked.connect(self._on_scan)
        self.browse_btn.clicked.connect(self._on_browse)
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn.clicked.connect(self._on_stop)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        self.device_table.itemSelectionChanged.connect(self._on_device_select)

        self.bridge.devices_found.connect(self._on_devices_found)
        self.bridge.status_update.connect(self._on_status_update)
        self.bridge.error_occurred.connect(self._on_error)

    def _on_scan(self):
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.status_label.setText("Scanning for devices...")

        def do_scan():
            try:
                loop = asyncio.new_event_loop()
                devices = loop.run_until_complete(scan_all(timeout=5.0))
                self.bridge.devices_found.emit(devices)
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_devices_found(self, devices: list[Device]):
        self.devices = devices
        self.device_table.setRowCount(len(devices))

        type_icons = {
            DeviceType.DLNA: "📺",
            DeviceType.AIRPLAY: "🍎",
            DeviceType.CHROMECAST: "📱",
        }

        for i, d in enumerate(devices):
            self.device_table.setItem(i, 0, QTableWidgetItem(d.name))
            self.device_table.setItem(i, 1, QTableWidgetItem(f"{type_icons.get(d.device_type, '')} {d.display_type}"))
            self.device_table.setItem(i, 2, QTableWidgetItem(f"{d.ip}:{d.port}"))
            self.device_table.setItem(i, 3, QTableWidgetItem("Available"))

        self.device_count.setText(f"{len(devices)} device(s) found")
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan")
        self.status_label.setText(f"Found {len(devices)} device(s)")

    def _on_browse(self):
        ext_list = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Media File", "",
            f"Media Files ({ext_list});;All Files (*)"
        )
        if filepath:
            self.media_path = filepath
            name = Path(filepath).name
            self.media_path_label.setText(name)
            self.status_label.setText(f"Selected: {name}")

    def _on_device_select(self):
        rows = self.device_table.selectionModel().selectedRows()
        if rows:
            idx = rows[0].row()
            if idx < len(self.devices):
                self.selected_device = self.devices[idx]

    def _on_play(self):
        if not self.selected_device:
            QMessageBox.warning(self, "Warning", "Please select a device first.")
            return
        if not self.media_path:
            QMessageBox.warning(self, "Warning", "Please select a media file first.")
            return

        self.is_playing = True
        self.status_label.setText(f"Playing on {self.selected_device.name}...")
        self.play_btn.setEnabled(False)

        device = self.selected_device
        media_path = self.media_path
        ext = Path(media_path).suffix.lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        def do_play():
            try:
                if device.device_type == DeviceType.DLNA:
                    loop = asyncio.new_event_loop()
                    server = MediaServer()
                    loop.run_until_complete(server.start())
                    server.register_file(media_path)
                    url = server.get_url(media_path)
                    self.media_server = server
                    loop.run_until_complete(dlna_controller.play(device, url, content_type))
                    self.bridge.status_update.emit(f"Playing on {device.name}")
                elif device.device_type == DeviceType.AIRPLAY:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(airplay_controller.play(device, media_path))
                    self.bridge.status_update.emit(f"Playing on {device.name}")
                else:
                    self.bridge.error_occurred.emit(f"Unsupported device type: {device.device_type}")
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))
            finally:
                self.play_btn.setEnabled(True)

        threading.Thread(target=do_play, daemon=True).start()

    def _on_stop(self):
        if not self.selected_device:
            return

        device = self.selected_device
        self.status_label.setText("Stopping...")

        def do_stop():
            try:
                loop = asyncio.new_event_loop()
                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.stop(device))
                    if self.media_server:
                        loop.run_until_complete(self.media_server.stop())
                        self.media_server = None
                elif device.device_type == DeviceType.AIRPLAY:
                    loop.run_until_complete(airplay_controller.stop(device))
                self.bridge.status_update.emit("Stopped")
                self.is_playing = False
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))

        threading.Thread(target=do_stop, daemon=True).start()

    def _on_volume_change(self, value: int):
        self.volume_value.setText(f"{value}%")

        if not self.selected_device or not self.is_playing:
            return

        device = self.selected_device

        def do_volume():
            try:
                loop = asyncio.new_event_loop()
                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.set_volume(device, value))
                elif device.device_type == DeviceType.AIRPLAY:
                    loop.run_until_complete(airplay_controller.set_volume(device, value))
            except Exception:
                pass

        threading.Thread(target=do_volume, daemon=True).start()

    def _on_status_update(self, msg: str):
        self.status_label.setText(msg)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self.play_btn.setEnabled(True)


# ── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    window = AutoCastGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
