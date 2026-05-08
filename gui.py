"""Auto-Cast GUI — Modern PySide6 interface for DLNA/AirPlay casting."""

import asyncio
import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSlider, QFrame, QMessageBox,
    QCheckBox, QSpinBox, QComboBox, QTabWidget, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup
from PySide6.QtGui import QColor, QGraphicsDropShadowEffect

from device import Device, DeviceType
from scanner import scan_all
from media_server import MediaServer
import dlna_controller
import airplay_controller
from config import SUPPORTED_EXTENSIONS, MIME_TYPES
from capture import list_windows, get_monitors, ScreenStreamer


# ── Signals Bridge ──────────────────────────────────────────────────────────

class SignalBridge(QObject):
    devices_found = Signal(list)
    status_update = Signal(str)
    error_occurred = Signal(str)


# ── Animation Helpers ──────────────────────────────────────────────────────

class FadeLabel(QLabel):
    """Label with fade-in animation when text changes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(300)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def setText(self, text: str):
        if text == self.text():
            return
        self._fade.stop()
        super().setWindowOpacity(0.0)
        super().setText(text)
        self._fade.start()


class ScanAnimation(QObject):
    """Pulsing glow animation for the scan button during scanning."""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._glow = QGraphicsDropShadowEffect(button)
        self._glow.setColor(QColor("#e94560"))
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        button.setGraphicsEffect(self._glow)

        self._pulse_up = QPropertyAnimation(self._glow, b"blurRadius")
        self._pulse_up.setDuration(900)
        self._pulse_up.setStartValue(0)
        self._pulse_up.setEndValue(18)
        self._pulse_up.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._pulse_down = QPropertyAnimation(self._glow, b"blurRadius")
        self._pulse_down.setDuration(900)
        self._pulse_down.setStartValue(18)
        self._pulse_down.setEndValue(0)
        self._pulse_down.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._group = QSequentialAnimationGroup(button)
        self._group.addAnimation(self._pulse_up)
        self._group.addAnimation(self._pulse_down)
        self._group.setLoopCount(-1)

    def start(self):
        self._btn.setObjectName("scanningBtn")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)
        self._group.start()

    def stop(self):
        self._group.stop()
        self._glow.setBlurRadius(0)
        self._btn.setObjectName("")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)


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
    transition-duration: 0.2s;
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

QPushButton#scanningBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e94560, stop:0.5 #ff6b6b, stop:1 #e94560);
    color: white;
    border: none;
    font-weight: bold;
}

QPushButton#secondaryBtn {
    background-color: #0f3460;
    border: 1px solid #533483;
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

QListWidget {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 8px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #0f3460;
    border-radius: 4px;
}

QListWidget::item:selected {
    background-color: #533483;
    color: white;
}

QListWidget::item:hover {
    background-color: #0f3460;
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

QLabel#sectionTitle {
    font-size: 16px;
    font-weight: bold;
    color: #e94560;
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

QCheckBox {
    color: #e0e0e0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #0f3460;
    border-radius: 4px;
    background-color: #16213e;
}

QCheckBox::indicator:checked {
    background-color: #e94560;
    border-color: #e94560;
}

QSpinBox {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e0e0e0;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: #0f3460;
    border: none;
    width: 20px;
}

QComboBox {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 6px 12px;
    color: #e0e0e0;
    min-height: 20px;
}

QComboBox:hover {
    border: 1px solid #533483;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #e0e0e0;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #16213e;
    border: 1px solid #0f3460;
    color: #e0e0e0;
    selection-background-color: #533483;
}

QTabWidget::pane {
    border: 1px solid #0f3460;
    border-radius: 8px;
    background-color: #1a1a2e;
}

QTabBar::tab {
    background-color: #16213e;
    color: #888;
    border: 1px solid #0f3460;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 24px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1a1a2e;
    color: #e94560;
    font-weight: bold;
    border-bottom: 2px solid #e94560;
}

QTabBar::tab:hover:!selected {
    background-color: #0f3460;
    color: #e0e0e0;
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

        # Screen capture
        self.streamer = ScreenStreamer(fps=10, quality=70)
        self.is_streaming = False
        self.windows_list = []
        self.monitors_list = []

        # Auto-refresh timer
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self._do_auto_scan)
        self.is_auto_refreshing = False
        self.scan_count = 0

        self._init_ui()
        self._connect_signals()
        self._refresh_windows()

    def _init_ui(self):
        self.setWindowTitle("Auto-Cast")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("Auto-Cast")
        title.setObjectName("title")
        subtitle = QLabel("DLNA / AirPlay / Chromecast")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        main_layout.addLayout(header)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(sep)

        # ── Main Content ──
        content = QHBoxLayout()
        content.setSpacing(16)

        # ── Left Panel: Devices ──
        left_panel = QFrame()
        left_panel.setObjectName("card")
        left_layout = QVBoxLayout(left_panel)

        device_header = QHBoxLayout()
        device_label = QLabel("Devices")
        device_label.setObjectName("sectionTitle")

        self.auto_refresh_cb = QCheckBox("Auto Refresh")
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(3, 60)
        self.refresh_interval.setValue(10)
        self.refresh_interval.setSuffix(" sec")
        self.refresh_interval.setMinimumWidth(85)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setMinimumWidth(100)

        device_header.addWidget(device_label)
        device_header.addStretch()
        device_header.addWidget(self.auto_refresh_cb)
        device_header.addWidget(self.refresh_interval)
        device_header.addWidget(self.scan_btn)
        left_layout.addLayout(device_header)

        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["Name", "Type", "IP Address", "Status"])
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.device_table.setColumnWidth(1, 120)
        self.device_table.setColumnWidth(2, 180)
        self.device_table.setColumnWidth(3, 100)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.device_table.setMinimumHeight(200)
        left_layout.addWidget(self.device_table)

        self.device_count = QLabel("0 devices found")
        self.device_count.setObjectName("subtitle")
        left_layout.addWidget(self.device_count)

        content.addWidget(left_panel, stretch=3)

        # ── Right Panel: Controls with Tabs ──
        right_panel = QFrame()
        right_panel.setObjectName("card")
        right_layout = QVBoxLayout(right_panel)

        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)

        # Tab 1: Media File
        file_tab = QWidget()
        file_layout = QVBoxLayout(file_tab)
        file_layout.setSpacing(16)

        media_label = QLabel("Media File")
        media_label.setObjectName("sectionTitle")
        file_layout.addWidget(media_label)

        self.media_path_label = QLabel("No file selected")
        self.media_path_label.setObjectName("subtitle")
        self.media_path_label.setWordWrap(True)
        self.media_path_label.setMinimumHeight(40)
        file_layout.addWidget(self.media_path_label)

        self.browse_btn = QPushButton("Browse...")
        file_layout.addWidget(self.browse_btn)

        file_layout.addStretch()
        self.tabs.addTab(file_tab, "Media File")

        # Tab 2: Window Cast
        window_tab = QWidget()
        window_layout = QVBoxLayout(window_tab)
        window_layout.setSpacing(12)

        win_header = QHBoxLayout()
        win_label = QLabel("Select Window")
        win_label.setObjectName("sectionTitle")
        self.refresh_windows_btn = QPushButton("Refresh")
        self.refresh_windows_btn.setMinimumWidth(80)
        self.refresh_windows_btn.setObjectName("secondaryBtn")
        win_header.addWidget(win_label)
        win_header.addStretch()
        win_header.addWidget(self.refresh_windows_btn)
        window_layout.addLayout(win_header)

        self.window_list = QListWidget()
        self.window_list.setMinimumHeight(200)
        window_layout.addWidget(self.window_list)

        self.window_info_label = QLabel("Select a window to cast")
        self.window_info_label.setObjectName("subtitle")
        window_layout.addWidget(self.window_info_label)

        self.cast_window_btn = QPushButton("Cast Window")
        self.cast_window_btn.setObjectName("primaryBtn")
        window_layout.addWidget(self.cast_window_btn)

        window_layout.addStretch()
        self.tabs.addTab(window_tab, "Window Cast")

        # Tab 3: Screen Cast
        screen_tab = QWidget()
        screen_layout = QVBoxLayout(screen_tab)
        screen_layout.setSpacing(12)

        monitor_label = QLabel("Select Monitor")
        monitor_label.setObjectName("sectionTitle")
        screen_layout.addWidget(monitor_label)

        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumHeight(36)
        screen_layout.addWidget(self.monitor_combo)

        self.refresh_monitors_btn = QPushButton("Refresh Monitors")
        self.refresh_monitors_btn.setObjectName("secondaryBtn")
        screen_layout.addWidget(self.refresh_monitors_btn)

        screen_layout.addSpacing(16)

        fps_label = QLabel("Frame Rate")
        fps_label.setStyleSheet("font-weight: bold;")
        screen_layout.addWidget(fps_label)

        fps_row = QHBoxLayout()
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setRange(1, 30)
        self.fps_slider.setValue(10)
        self.fps_value = QLabel("10 FPS")
        self.fps_value.setMinimumWidth(60)
        fps_row.addWidget(self.fps_slider)
        fps_row.addWidget(self.fps_value)
        screen_layout.addLayout(fps_row)

        self.cast_screen_btn = QPushButton("Cast Screen")
        self.cast_screen_btn.setObjectName("primaryBtn")
        screen_layout.addWidget(self.cast_screen_btn)

        screen_layout.addStretch()
        self.tabs.addTab(screen_tab, "Screen Cast")

        # ── Common Controls ──
        right_layout.addWidget(self._make_separator())

        play_label = QLabel("Playback")
        play_label.setObjectName("sectionTitle")
        right_layout.addWidget(play_label)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primaryBtn")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("dangerBtn")
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.stop_btn)
        right_layout.addLayout(btn_row)

        vol_label = QLabel("Volume")
        vol_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(vol_label)

        vol_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_value = QLabel("70%")
        self.volume_value.setMinimumWidth(45)
        vol_row.addWidget(self.volume_slider)
        vol_row.addWidget(self.volume_value)
        right_layout.addLayout(vol_row)

        content.addWidget(right_panel, stretch=2)
        main_layout.addLayout(content, stretch=1)

        # ── Status Bar ──
        self.status_label = FadeLabel("Ready")
        self.status_label.setObjectName("status")
        main_layout.addWidget(self.status_label)

        # ── Scan Animation ──
        self._scan_anim = ScanAnimation(self.scan_btn)

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        return sep

    def _animate_button_click(self, btn: QPushButton):
        """Quick scale pulse on button click."""
        anim = QPropertyAnimation(btn, b"geometry")
        anim.setDuration(150)
        rect = btn.geometry()
        # Small inward scale (2px)
        anim.setKeyValueAt(0.0, rect)
        anim.setKeyValueAt(0.3, rect.adjusted(2, 1, -2, -1))
        anim.setKeyValueAt(1.0, rect)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.start()
        # Keep reference so it's not garbage collected
        btn._click_anim = anim

    def _connect_signals(self):
        # Device scanning
        self.scan_btn.clicked.connect(self._on_scan)
        self.auto_refresh_cb.toggled.connect(self._on_auto_refresh_toggle)
        self.refresh_interval.valueChanged.connect(self._on_interval_change)
        self.device_table.itemSelectionChanged.connect(self._on_device_select)

        # Media file
        self.browse_btn.clicked.connect(self._on_browse)
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn.clicked.connect(self._on_stop)
        self.volume_slider.valueChanged.connect(self._on_volume_change)

        # Window cast
        self.refresh_windows_btn.clicked.connect(self._refresh_windows)
        self.cast_window_btn.clicked.connect(self._on_cast_window)
        self.window_list.currentRowChanged.connect(self._on_window_select)

        # Screen cast
        self.refresh_monitors_btn.clicked.connect(self._refresh_monitors)
        self.cast_screen_btn.clicked.connect(self._on_cast_screen)
        self.fps_slider.valueChanged.connect(lambda v: self.fps_value.setText(f"{v} FPS"))

        # Signals
        self.bridge.devices_found.connect(self._on_devices_found)
        self.bridge.status_update.connect(self._on_status_update)
        self.bridge.error_occurred.connect(self._on_error)

    # ── Device Scanning ──────────────────────────────────────────────────────

    def _on_auto_refresh_toggle(self, checked: bool):
        if checked:
            self.is_auto_refreshing = True
            self.scan_count = 0
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText("Auto...")
            self._scan_anim.start()
            interval_ms = self.refresh_interval.value() * 1000
            self.auto_refresh_timer.start(interval_ms)
            self.status_label.setText("Auto-refresh: scanning...")
            self._do_auto_scan()
        else:
            self.is_auto_refreshing = False
            self._scan_anim.stop()
            self.auto_refresh_timer.stop()
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("Scan")
            self.status_label.setText("Auto-refresh disabled")

    def _on_interval_change(self, value: int):
        if self.is_auto_refreshing:
            self.auto_refresh_timer.setInterval(value * 1000)

    def _do_auto_scan(self):
        self.status_label.setText("Scanning...")

        def do_scan():
            try:
                loop = asyncio.new_event_loop()
                devices = loop.run_until_complete(scan_all(timeout=4.0))
                self.bridge.devices_found.emit(devices)
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_scan(self):
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self._scan_anim.start()
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
        prev_ip = self.selected_device.ip if self.selected_device else None
        self.selected_device = None

        self.devices = devices
        self.device_table.setRowCount(len(devices))

        type_icons = {
            DeviceType.DLNA: "📺",
            DeviceType.AIRPLAY: "🍎",
            DeviceType.CHROMECAST: "📱",
        }

        for i, d in enumerate(devices):
            name_item = QTableWidgetItem(d.name)
            name_item.setToolTip(d.name)
            self.device_table.setItem(i, 0, name_item)
            self.device_table.setItem(i, 1, QTableWidgetItem(f"{type_icons.get(d.device_type, '')} {d.display_type}"))
            self.device_table.setItem(i, 2, QTableWidgetItem(f"{d.ip}:{d.port}"))
            self.device_table.setItem(i, 3, QTableWidgetItem("Available"))

            if prev_ip and d.ip == prev_ip:
                self.device_table.selectRow(i)
                self.selected_device = d

        self.device_count.setText(f"{len(devices)} device(s) found")

        if not self.is_auto_refreshing:
            self._scan_anim.stop()
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("Scan")
            self.status_label.setText(f"Found {len(devices)} device(s)")
        else:
            self.scan_count += 1
            next_sec = self.refresh_interval.value()
            self.status_label.setText(f"Auto-refresh #{self.scan_count}: {len(devices)} device(s) — next in {next_sec}s")

    def _on_device_select(self):
        rows = self.device_table.selectionModel().selectedRows()
        if rows:
            idx = rows[0].row()
            if idx < len(self.devices):
                self.selected_device = self.devices[idx]

    # ── Media File ───────────────────────────────────────────────────────────

    def _on_browse(self):
        self._animate_button_click(self.browse_btn)
        ext_list = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Media File", "",
            f"Media Files ({ext_list});;All Files (*)"
        )
        if filepath:
            self.media_path = filepath
            name = Path(filepath).name
            self.media_path_label.setText(name)
            self.media_path_label.setToolTip(filepath)
            self.status_label.setText(f"Selected: {name}")

    def _on_play(self):
        self._animate_button_click(self.play_btn)
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
                    self.bridge.error_occurred.emit(f"Unsupported: {device.device_type}")
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))
            finally:
                self.play_btn.setEnabled(True)

        threading.Thread(target=do_play, daemon=True).start()

    # ── Window Cast ──────────────────────────────────────────────────────────

    def _refresh_windows(self):
        self.window_list.clear()
        self.windows_list = list_windows()

        for w in self.windows_list:
            icon = "📺" if not w.process_name.lower().startswith(("chrome", "firefox", "edge")) else "🌐"
            item = QListWidgetItem(f"{icon} {w.title}")
            item.setToolTip(f"Process: {w.process_name}\nPID: {w.pid}\nSize: {w.rect[2]}x{w.rect[3]}")
            self.window_list.addItem(item)

        self.window_info_label.setText(f"{len(self.windows_list)} window(s) found")

    def _on_window_select(self, index: int):
        if 0 <= index < len(self.windows_list):
            w = self.windows_list[index]
            self.window_info_label.setText(f"{w.process_name} — {w.rect[2]}x{w.rect[3]}")

    def _on_cast_window(self):
        self._animate_button_click(self.cast_window_btn)
        if not self.selected_device:
            QMessageBox.warning(self, "Warning", "Please select a target device first.")
            return

        idx = self.window_list.currentRow()
        if idx < 0 or idx >= len(self.windows_list):
            QMessageBox.warning(self, "Warning", "Please select a window to cast.")
            return

        window = self.windows_list[idx]
        device = self.selected_device
        fps = self.fps_slider.value()

        self.status_label.setText(f"Casting '{window.title}' to {device.name}...")
        self.is_streaming = True
        self.cast_window_btn.setEnabled(False)
        self.streamer.fps = fps

        def do_cast():
            try:
                self.streamer.start_window(window.hwnd)

                loop = asyncio.new_event_loop()
                server = MediaServer()
                loop.run_until_complete(server.start())

                streamer_ref = self.streamer

                async def stream_handle(request):
                    from aiohttp import web
                    frame = streamer_ref.get_frame()
                    if frame:
                        return web.Response(
                            body=frame,
                            content_type="image/jpeg",
                            headers={"Cache-Control": "no-cache"},
                        )
                    return web.Response(status=204)

                server._app.router.add_get("/stream", stream_handle)
                stream_url = f"http://{server._local_ip}:{server._actual_port}/stream"

                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.play(device, stream_url, "image/jpeg"))
                elif device.device_type == DeviceType.AIRPLAY:
                    pass

                self.bridge.status_update.emit(f"Casting '{window.title}' to {device.name}")
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))
                self.is_streaming = False
                self.cast_window_btn.setEnabled(True)

        threading.Thread(target=do_cast, daemon=True).start()

    # ── Screen Cast ──────────────────────────────────────────────────────────

    def _refresh_monitors(self):
        self.monitor_combo.clear()
        self.monitors_list = get_monitors()

        for m in self.monitors_list:
            self.monitor_combo.addItem(m["name"])

    def _on_cast_screen(self):
        self._animate_button_click(self.cast_screen_btn)
        if not self.selected_device:
            QMessageBox.warning(self, "Warning", "Please select a target device first.")
            return

        idx = self.monitor_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "Warning", "Please select a monitor.")
            return

        monitor = self.monitors_list[idx]
        device = self.selected_device
        fps = self.fps_slider.value()

        self.status_label.setText(f"Casting {monitor['name']} to {device.name}...")
        self.is_streaming = True
        self.cast_screen_btn.setEnabled(False)
        self.streamer.fps = fps

        def do_cast():
            try:
                self.streamer.start_monitor(monitor["index"])

                loop = asyncio.new_event_loop()
                server = MediaServer()
                loop.run_until_complete(server.start())

                streamer_ref = self.streamer

                async def stream_handle(request):
                    from aiohttp import web
                    frame = streamer_ref.get_frame()
                    if frame:
                        return web.Response(
                            body=frame,
                            content_type="image/jpeg",
                            headers={"Cache-Control": "no-cache"},
                        )
                    return web.Response(status=204)

                server._app.router.add_get("/stream", stream_handle)
                stream_url = f"http://{server._local_ip}:{server._actual_port}/stream"

                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.play(device, stream_url, "image/jpeg"))
                elif device.device_type == DeviceType.AIRPLAY:
                    pass

                self.bridge.status_update.emit(f"Casting {monitor['name']} to {device.name}")
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))
                self.is_streaming = False
                self.cast_screen_btn.setEnabled(True)

        threading.Thread(target=do_cast, daemon=True).start()

    # ── Stop & Volume ────────────────────────────────────────────────────────

    def _on_stop(self):
        self._animate_button_click(self.stop_btn)
        if not self.selected_device:
            return

        device = self.selected_device
        self.status_label.setText("Stopping...")

        if self.is_streaming:
            self.streamer.stop()
            self.is_streaming = False
            self.cast_window_btn.setEnabled(True)
            self.cast_screen_btn.setEnabled(True)

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

    # ── Status ───────────────────────────────────────────────────────────────

    def _on_status_update(self, msg: str):
        self.status_label.setText(msg)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self.play_btn.setEnabled(True)
        self.cast_window_btn.setEnabled(True)
        self.cast_screen_btn.setEnabled(True)


# ── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    window = AutoCastGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
