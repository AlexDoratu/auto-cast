"""Auto-Cast GUI — Modern PySide6 interface for DLNA/AirPlay casting."""

import asyncio
import logging
import sys
import threading
from pathlib import Path

# Log to file for debugging packaged exe
_log_path = Path(__file__).parent / "autocast-debug.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(_log_path, encoding="utf-8")],
)
logger = logging.getLogger("autocast-gui")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSlider, QFrame, QMessageBox,
    QCheckBox, QSpinBox, QComboBox, QTabWidget, QListWidget, QListWidgetItem,
    QGraphicsOpacityEffect, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup
from PySide6.QtGui import QColor, QFont, QShortcut, QKeySequence, QIcon
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from device import Device, DeviceType
from scanner import scan_all
from media_server import MediaServer
import dlna_controller
import airplay_controller
from config import SUPPORTED_EXTENSIONS, MIME_TYPES
from capture import list_windows, get_monitors, ScreenStreamer
from live_resolver import resolve_live_url
from app_state import load_state, matches_device, redact_url, save_state, state_for_device


# ── Color Palette ────────────────────────────────────────────────────────────

class C:
    """Centralized color constants for consistent styling."""
    BG          = "#0b0b0f"
    SURFACE     = "#15151a"
    CARD        = "#1a1a21"
    CARD_BORDER = "#242430"
    INPUT_BG    = "#1e1e28"
    INPUT_BORDER= "#2a2a38"
    HOVER       = "#22222e"
    SELECTED    = "#1a2744"
    TEXT        = "#e8e8ee"
    TEXT_DIM    = "#7a7a8a"
    TEXT_MUTED  = "#55556a"
    ACCENT      = "#38bdf8"
    ACCENT_DIM  = "#1e3a5f"
    DANGER      = "#ef4444"
    DANGER_DIM  = "#7f1d1d"
    SUCCESS     = "#34d399"
    PURPLE      = "#a78bfa"
    PINK        = "#f472b6"
    PRIMARY     = "#2563eb"
    PRIMARY_HOV = "#3b82f6"
    PRIMARY_ACT = "#1d4ed8"
    PRIMARY_DIS = "#1e3a5f"
    SEPARATOR   = "#1e1e28"


# ── Stylesheet ───────────────────────────────────────────────────────────────

DARK_STYLE = f"""
/* ── Base ─────────────────────────────────────────────────────────────── */

QMainWindow {{
    background-color: {C.BG};
}}

QWidget {{
    background-color: transparent;
    color: {C.TEXT};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}}

QDialog, QMessageBox {{
    background-color: {C.SURFACE};
}}

/* ── Cards ────────────────────────────────────────────────────────────── */

QFrame#card {{
    background-color: {C.CARD};
    border: 1px solid {C.CARD_BORDER};
    border-radius: 16px;
}}

QFrame#statusBar {{
    background-color: {C.SURFACE};
    border: 1px solid {C.CARD_BORDER};
    border-radius: 12px;
}}

QFrame#separator {{
    background-color: {C.SEPARATOR};
    max-height: 1px;
}}

/* ── Typography ───────────────────────────────────────────────────────── */

QLabel#title {{
    font-size: 26px;
    font-weight: 700;
    color: {C.TEXT};
    letter-spacing: -0.5px;
    background: transparent;
}}

QLabel#subtitle {{
    color: {C.TEXT_DIM};
    font-size: 11px;
    background: transparent;
}}

QLabel#status {{
    color: {C.ACCENT};
    font-weight: 500;
    font-size: 12px;
    padding: 0;
    background: transparent;
}}

QLabel#sectionTitle {{
    font-size: 10px;
    font-weight: 700;
    color: {C.TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 1px;
    background: transparent;
}}

QLabel#accentLabel {{
    color: {C.ACCENT};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}

QLabel#emptyState {{
    color: {C.TEXT_MUTED};
    font-size: 13px;
    font-style: italic;
    background: transparent;
}}

/* ── Buttons ──────────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {C.INPUT_BG};
    color: {C.TEXT};
    border: 1px solid {C.INPUT_BORDER};
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 500;
    font-size: 13px;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {C.HOVER};
    border-color: #3a3a4a;
    color: #f4f4f8;
}}

QPushButton:pressed {{
    background-color: #2a2a38;
}}

QPushButton:disabled {{
    background-color: #131318;
    color: #3a3a4a;
    border-color: {C.SEPARATOR};
}}

QPushButton#primaryBtn {{
    background-color: {C.PRIMARY};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}

QPushButton#primaryBtn:hover {{
    background-color: {C.PRIMARY_HOV};
}}

QPushButton#primaryBtn:pressed {{
    background-color: {C.PRIMARY_ACT};
}}

QPushButton#primaryBtn:disabled {{
    background-color: {C.PRIMARY_DIS};
    color: #2d4a7a;
}}

QPushButton#dangerBtn {{
    background-color: {C.DANGER_DIM};
    color: #fca5a5;
    border: 1px solid #991b1b;
}}

QPushButton#dangerBtn:hover {{
    background-color: #991b1b;
    color: #fecaca;
}}

QPushButton#dangerBtn:pressed {{
    background-color: {C.DANGER_DIM};
}}

QPushButton#scanBtn {{
    background-color: {C.ACCENT_DIM};
    color: {C.ACCENT};
    border: 1px solid #1e4d7a;
    font-weight: 600;
    padding: 10px 28px;
    border-radius: 10px;
    letter-spacing: 0.3px;
}}

QPushButton#scanBtn:hover {{
    background-color: #1e4d7a;
    color: #7dd3fc;
    border-color: #2563a0;
}}

QPushButton#scanBtn:pressed {{
    background-color: #17355a;
}}

QPushButton#scanningBtn {{
    background-color: {C.ACCENT_DIM};
    color: {C.ACCENT};
    border: 1px solid #1e4d7a;
    font-weight: 600;
}}

QPushButton#iconBtn {{
    background-color: transparent;
    border: 1px solid {C.INPUT_BORDER};
    padding: 6px 10px;
    font-size: 14px;
    border-radius: 8px;
    min-width: 32px;
}}

QPushButton#iconBtn:hover {{
    background-color: {C.HOVER};
    border-color: #3a3a4a;
}}

/* ── Table ────────────────────────────────────────────────────────────── */

QTableWidget {{
    background-color: {C.CARD};
    border: 1px solid {C.CARD_BORDER};
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: transparent;
    outline: none;
}}

QTableWidget::item {{
    padding: 12px 10px;
    border-bottom: 1px solid #181820;
    color: {C.TEXT};
}}

QTableWidget::item:selected {{
    background-color: {C.SELECTED};
    color: #e4e4e7;
    border-left: 2px solid {C.ACCENT};
    border-bottom: 1px solid {C.SELECTED};
}}

QTableWidget::item:hover {{
    background-color: {C.HOVER};
}}

QTableWidget::item:selected:hover {{
    background-color: {C.SELECTED};
}}

QHeaderView::section {{
    background-color: {C.CARD};
    color: {C.TEXT_MUTED};
    padding: 12px 10px;
    border: none;
    border-bottom: 1px solid {C.SEPARATOR};
    font-weight: 700;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}

/* ── List ─────────────────────────────────────────────────────────────── */

QListWidget {{
    background-color: {C.CARD};
    border: 1px solid {C.CARD_BORDER};
    border-radius: 12px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-bottom: 1px solid #181820;
    border-radius: 8px;
    color: {C.TEXT};
}}

QListWidget::item:selected {{
    background-color: {C.SELECTED};
    color: #e4e4e7;
}}

QListWidget::item:hover {{
    background-color: {C.HOVER};
}}

/* ── Slider ───────────────────────────────────────────────────────────── */

QSlider::groove:horizontal {{
    height: 4px;
    background: {C.SEPARATOR};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {C.TEXT};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {C.ACCENT};
}}

QSlider::sub-page:horizontal {{
    background: {C.PRIMARY};
    border-radius: 2px;
}}

/* ── Checkbox ─────────────────────────────────────────────────────────── */

QCheckBox {{
    color: {C.TEXT};
    spacing: 8px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid #3a3a4a;
    border-radius: 4px;
    background-color: transparent;
}}

QCheckBox::indicator:hover {{
    border-color: #52525b;
}}

QCheckBox::indicator:checked {{
    background-color: {C.PRIMARY};
    border-color: {C.PRIMARY};
}}

/* ── SpinBox ──────────────────────────────────────────────────────────── */

QSpinBox {{
    background-color: {C.INPUT_BG};
    border: 1px solid {C.INPUT_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    color: {C.TEXT};
}}

QSpinBox:focus {{
    border-color: {C.ACCENT};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {C.HOVER};
    border: none;
    width: 20px;
}}

/* ── ComboBox ─────────────────────────────────────────────────────────── */

QComboBox {{
    background-color: {C.INPUT_BG};
    border: 1px solid {C.INPUT_BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    color: {C.TEXT};
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: #3a3a4a;
}}

QComboBox:focus {{
    border-color: {C.ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.TEXT_DIM};
    margin-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {C.SURFACE};
    border: 1px solid {C.INPUT_BORDER};
    color: {C.TEXT};
    selection-background-color: {C.SELECTED};
    selection-color: #e4e4e7;
    border-radius: 10px;
    padding: 4px;
}}

/* ── Tabs ─────────────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: 1px solid {C.CARD_BORDER};
    border-radius: 12px;
    background-color: {C.CARD};
    top: -1px;
}}

QTabBar {{
    background: transparent;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {C.TEXT_DIM};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 22px;
    margin-right: 2px;
    font-weight: 500;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    color: {C.ACCENT};
    font-weight: 600;
    border-bottom: 2px solid {C.ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: #b0b0bc;
    border-bottom: 2px solid {C.INPUT_BORDER};
}}

/* ── Scrollbar ────────────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {C.INPUT_BORDER};
    border-radius: 3px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: #3a3a4a;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {C.INPUT_BORDER};
    border-radius: 3px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #3a3a4a;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


# ── Signals Bridge ────────────────────────────────────────────────────────────

class SignalBridge(QObject):
    devices_found = Signal(list, int)
    status_update = Signal(str)
    error_occurred = Signal(str)
    playback_finished = Signal()


# ── Animation Helpers ─────────────────────────────────────────────────────────

class FadeLabel(QLabel):
    """Label with fade-in animation when text changes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(250)
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


class AnimatedTabWidget(QTabWidget):
    """Tab widget with fade transition between tabs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._transitioning = False
        self._tab_anim = None
        self.currentChanged.connect(self._on_tab_change)

    def _on_tab_change(self, index: int):
        if self._transitioning:
            return
        widget = self.widget(index)
        if widget is None:
            return
        self._transitioning = True
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self._cleanup(widget, effect))
        anim.start()
        self._tab_anim = anim

    def _cleanup(self, widget: QWidget, effect: QGraphicsOpacityEffect):
        widget.setGraphicsEffect(None)
        self._transitioning = False


class ScanAnimation(QObject):
    """Pulsing glow animation for the scan button during scanning."""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._glow = QGraphicsDropShadowEffect(button)
        self._glow.setColor(QColor(C.ACCENT))
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        button.setGraphicsEffect(self._glow)

        self._pulse_up = QPropertyAnimation(self._glow, b"blurRadius")
        self._pulse_up.setDuration(800)
        self._pulse_up.setStartValue(0)
        self._pulse_up.setEndValue(25)
        self._pulse_up.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._pulse_down = QPropertyAnimation(self._glow, b"blurRadius")
        self._pulse_down.setDuration(800)
        self._pulse_down.setStartValue(25)
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
        self._btn.setObjectName("scanBtn")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)


# ── Main Window ───────────────────────────────────────────────────────────────

class AutoCastGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.devices: list[Device] = []
        self.selected_device: Device | None = None
        self.media_path: str | None = None
        self.media_server: MediaServer | None = None
        self.playback_device: Device | None = None
        self.is_scanning = False
        self.scan_generation = 0
        self.is_playing = False
        self.resume_state = load_state()
        self._resume_attempted = False
        self._state_lock = threading.RLock()
        self.bridge = SignalBridge()

        # Screen capture
        self.streamer = ScreenStreamer(fps=10, quality=70)
        self.is_streaming = False
        self.windows_list: list = []
        self.monitors_list: list = []

        # Auto-refresh timer
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self._do_auto_scan)
        self.is_auto_refreshing = False
        self.scan_count = 0

        self._init_ui()
        self._connect_signals()
        self._refresh_windows()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("Auto-Cast")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 20, 24, 20)

        self._build_header(main_layout)
        self._build_content(main_layout)
        self._build_status_bar(main_layout)

    def _build_header(self, parent: QVBoxLayout):
        header = QHBoxLayout()
        header.setSpacing(16)

        # Title
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Auto-Cast")
        title.setObjectName("title")
        subtitle = QLabel("DLNA  /  AirPlay  /  Chromecast")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()

        # Scan button — prominent in header
        self.scan_btn = QPushButton("  Scan Devices")
        self.scan_btn.setObjectName("scanBtn")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.setMinimumWidth(140)
        self._scan_anim = ScanAnimation(self.scan_btn)
        header.addWidget(self.scan_btn)

        # Auto-refresh toggle
        self.auto_refresh_cb = QCheckBox("Auto")
        self.auto_refresh_cb.setToolTip("Auto-refresh device list")
        self.auto_resume_cb = QCheckBox("Resume")
        self.auto_resume_cb.setToolTip("Auto-play the last file or live URL when the same remembered device is found")
        self.auto_resume_cb.setChecked(self.resume_state.auto_resume_enabled)
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(3, 60)
        self.refresh_interval.setValue(10)
        self.refresh_interval.setSuffix("s")
        self.refresh_interval.setFixedWidth(64)
        self.refresh_interval.setToolTip("Refresh interval")
        header.addWidget(self.auto_refresh_cb)
        header.addWidget(self.auto_resume_cb)
        header.addWidget(self.refresh_interval)

        parent.addLayout(header)

    def _build_content(self, parent: QVBoxLayout):
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._build_device_panel(), stretch=2)
        content.addWidget(self._build_control_panel(), stretch=3)
        parent.addLayout(content, stretch=1)

    def _build_device_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 16)

        # Section title
        label = QLabel("DEVICES")
        label.setObjectName("sectionTitle")
        layout.addWidget(label)

        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["Name", "Type", "IP", "Status"])
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.device_table.setColumnWidth(1, 100)
        self.device_table.setColumnWidth(2, 160)
        self.device_table.setColumnWidth(3, 80)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.device_table.setMinimumHeight(200)
        self.device_table.setShowGrid(False)
        layout.addWidget(self.device_table)

        self.device_count = QLabel("No devices")
        self.device_count.setObjectName("subtitle")
        layout.addWidget(self.device_count)

        return panel

    def _build_control_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        self.tabs = AnimatedTabWidget()
        self.tabs.addTab(self._build_media_tab(), "Media File")
        self.tabs.addTab(self._build_live_tab(), "Live URL")
        self.tabs.addTab(self._build_window_tab(), "Window Cast")
        self.tabs.addTab(self._build_screen_tab(), "Screen Cast")
        layout.addWidget(self.tabs)

        layout.addWidget(self._make_separator())

        # Playback
        play_label = QLabel("PLAYBACK")
        play_label.setObjectName("sectionTitle")
        layout.addWidget(play_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.play_btn = QPushButton("  Play")
        self.play_btn.setObjectName("primaryBtn")
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn = QPushButton("  Stop")
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # Volume
        vol_label = QLabel("VOLUME")
        vol_label.setObjectName("sectionTitle")
        layout.addWidget(vol_label)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(12)
        vol_min = QLabel("0")
        vol_min.setObjectName("subtitle")
        vol_min.setFixedWidth(16)
        vol_min.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_row.addWidget(vol_min)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        vol_row.addWidget(self.volume_slider)
        vol_max = QLabel("100")
        vol_max.setObjectName("subtitle")
        vol_max.setFixedWidth(28)
        vol_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_row.addWidget(vol_max)
        self.volume_value = QLabel("70%")
        self.volume_value.setObjectName("accentLabel")
        self.volume_value.setFixedWidth(40)
        vol_row.addWidget(self.volume_value)
        layout.addLayout(vol_row)

        return panel

    def _build_media_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.media_path_label = QLabel("No file selected")
        self.media_path_label.setObjectName("emptyState")
        self.media_path_label.setWordWrap(True)
        self.media_path_label.setMinimumHeight(36)
        layout.addWidget(self.media_path_label)

        self.browse_btn = QPushButton("  Browse...")
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.browse_btn)
        layout.addStretch()
        return tab

    def _build_live_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        label = QLabel("BILIBILI / LIVE URL")
        label.setObjectName("sectionTitle")
        layout.addWidget(label)

        self.live_url_input = QLineEdit()
        self.live_url_input.setPlaceholderText("Paste Bilibili live URL, e.g. https://live.bilibili.com/...")
        self.live_url_input.setClearButtonEnabled(True)
        self.live_url_input.setMinimumHeight(40)
        layout.addWidget(self.live_url_input)

        hint = QLabel("The app resolves the real stream in the background and pushes it to the selected TV.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return tab

    def _build_window_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QHBoxLayout()
        header.addStretch()
        self.refresh_windows_btn = QPushButton("Refresh")
        self.refresh_windows_btn.setMinimumWidth(75)
        self.refresh_windows_btn.setObjectName("iconBtn")
        self.refresh_windows_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(self.refresh_windows_btn)
        layout.addLayout(header)

        self.window_list = QListWidget()
        self.window_list.setMinimumHeight(200)
        layout.addWidget(self.window_list)

        self.window_info_label = QLabel("Select a window to cast")
        self.window_info_label.setObjectName("subtitle")
        layout.addWidget(self.window_info_label)

        self.cast_window_btn = QPushButton("Cast Window")
        self.cast_window_btn.setObjectName("primaryBtn")
        self.cast_window_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.cast_window_btn)
        layout.addStretch()
        return tab

    def _build_screen_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        monitor_label = QLabel("MONITOR")
        monitor_label.setObjectName("sectionTitle")
        layout.addWidget(monitor_label)

        self.monitor_combo = QComboBox()
        self.monitor_combo.setFixedHeight(40)
        layout.addWidget(self.monitor_combo)

        self.refresh_monitors_btn = QPushButton("Refresh Monitors")
        self.refresh_monitors_btn.setObjectName("iconBtn")
        self.refresh_monitors_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.refresh_monitors_btn)

        layout.addSpacing(4)

        # FPS slider
        s1, r1, self.fps_slider, self.fps_value = self._make_slider_row(
            "FRAME RATE", "1", "30", 1, 30, 10, " FPS"
        )
        layout.addWidget(s1)
        layout.addLayout(r1)

        # Bitrate slider
        s2, r2, self.bitrate_slider, self.bitrate_value = self._make_slider_row(
            "VIDEO BITRATE", "Auto", "5M", 0, 25, 5, "", unlimited_label="Auto"
        )
        layout.addWidget(s2)
        layout.addLayout(r2)

        self.cast_screen_btn = QPushButton("Cast Screen")
        self.cast_screen_btn.setObjectName("primaryBtn")
        self.cast_screen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.cast_screen_btn)
        layout.addStretch()
        return tab

    def _build_status_bar(self, parent: QVBoxLayout):
        frame = QFrame()
        frame.setObjectName("statusBar")
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 2)
        frame.setGraphicsEffect(shadow)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {C.ACCENT}; font-size: 8px; background: transparent;")
        layout.addWidget(dot)

        self.status_label = FadeLabel("Ready")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)
        layout.addStretch()

        parent.addWidget(frame)

    # ── UI Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        return sep

    @staticmethod
    def _make_slider_row(
        title: str, min_text: str, max_text: str,
        range_min: int, range_max: int, default: int,
        suffix: str = "", unlimited_label: str = "",
    ) -> tuple[QLabel, QHBoxLayout, QSlider, QLabel]:
        label = QLabel(title)
        label.setObjectName("sectionTitle")

        row = QHBoxLayout()
        row.setSpacing(12)

        min_lbl = QLabel(min_text)
        min_lbl.setObjectName("subtitle")
        min_lbl.setFixedWidth(22)
        min_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(min_lbl)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(range_min, range_max)
        slider.setValue(default)
        row.addWidget(slider)

        max_lbl = QLabel(max_text)
        max_lbl.setObjectName("subtitle")
        max_lbl.setFixedWidth(28)
        max_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(max_lbl)

        if default == 0 and unlimited_label:
            init_text = unlimited_label
        elif suffix:
            init_text = f"{default}{suffix}"
        else:
            init_text = str(default)
        value_lbl = QLabel(init_text)
        value_lbl.setObjectName("accentLabel")
        value_lbl.setFixedWidth(70)
        row.addWidget(value_lbl)

        return label, row, slider, value_lbl

    def _animate_button_click(self, btn: QPushButton):
        anim = QPropertyAnimation(btn, b"geometry")
        anim.setDuration(100)
        rect = btn.geometry()
        anim.setKeyValueAt(0.0, rect)
        anim.setKeyValueAt(0.3, rect.adjusted(1, 1, -1, -1))
        anim.setKeyValueAt(1.0, rect)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.start()
        btn._click_anim = anim

    def _fade_table_in(self):
        effect = QGraphicsOpacityEffect(self.device_table)
        self.device_table.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.device_table.setGraphicsEffect(None))
        anim.start()
        self._table_fade = anim

    # ── Signal Wiring ──────────────────────────────────────────────────────────

    def _connect_signals(self):
        # Scanning
        self.scan_btn.clicked.connect(self._on_scan)
        self.auto_refresh_cb.toggled.connect(self._on_auto_refresh_toggle)
        self.refresh_interval.valueChanged.connect(self._on_interval_change)
        self.device_table.itemSelectionChanged.connect(self._on_device_select)

        # Media
        self.browse_btn.clicked.connect(self._on_browse)
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn.clicked.connect(self._on_stop)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        self.auto_resume_cb.toggled.connect(self._on_auto_resume_toggled)

        # Window cast
        self.refresh_windows_btn.clicked.connect(self._refresh_windows)
        self.cast_window_btn.clicked.connect(self._on_cast_window)
        self.window_list.currentRowChanged.connect(self._on_window_select)

        # Screen cast
        self.refresh_monitors_btn.clicked.connect(self._refresh_monitors)
        self.cast_screen_btn.clicked.connect(self._on_cast_screen)
        self.fps_slider.valueChanged.connect(lambda v: self.fps_value.setText(f"{v} FPS"))
        self.bitrate_slider.valueChanged.connect(self._on_bitrate_change)

        # Bridge
        self.bridge.devices_found.connect(self._on_devices_found)
        self.bridge.status_update.connect(self._on_status_update)
        self.bridge.error_occurred.connect(self._on_error)
        self.bridge.playback_finished.connect(self._on_playback_finished)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+O"), self, self._on_browse)
        QShortcut(QKeySequence("F5"), self, self._on_scan)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)

    # ── Device Scanning ───────────────────────────────────────────────────────

    def _on_auto_refresh_toggle(self, checked: bool):
        if checked:
            self.is_auto_refreshing = True
            self.scan_count = 0
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText("  Scanning...")
            self._scan_anim.start()
            self.auto_refresh_timer.start(self.refresh_interval.value() * 1000)
            self.status_label.setText("Auto-refresh enabled")
            self._do_auto_scan()
        else:
            self.is_auto_refreshing = False
            self._scan_anim.stop()
            self.auto_refresh_timer.stop()
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("  Scan Devices")
            self.status_label.setText("Auto-refresh disabled")

    def _on_interval_change(self, value: int):
        if self.is_auto_refreshing:
            self.auto_refresh_timer.setInterval(value * 1000)

    def _do_auto_scan(self):
        if self.is_scanning:
            return
        self.status_label.setText("Scanning...")
        self.is_scanning = True
        self.scan_generation += 1
        generation = self.scan_generation

        def do_scan():
            loop = asyncio.new_event_loop()
            try:
                logger.info("Auto-scan starting...")
                devices = loop.run_until_complete(scan_all(timeout=4.0))
                logger.info(f"Auto-scan complete: {len(devices)} device(s)")
                self.bridge.devices_found.emit(devices, generation)
            except Exception as e:
                logger.exception("Auto-scan failed")
                self.bridge.error_occurred.emit(str(e))
            finally:
                loop.close()
                self.is_scanning = False

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_scan(self):
        if self.is_scanning:
            return
        self.is_scanning = True
        self.scan_generation += 1
        generation = self.scan_generation
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("  Scanning...")
        self._scan_anim.start()
        self.status_label.setText("Scanning for devices...")

        def do_scan():
            loop = asyncio.new_event_loop()
            try:
                logger.info("Starting device scan...")
                devices = loop.run_until_complete(scan_all(timeout=5.0))
                logger.info(f"Scan complete: {len(devices)} device(s) found")
                self.bridge.devices_found.emit(devices, generation)
            except Exception as e:
                logger.exception("Scan failed")
                self.bridge.error_occurred.emit(str(e))
            finally:
                loop.close()
                self.is_scanning = False

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_devices_found(self, devices: list[Device], generation: int = 0):
        if generation and generation != self.scan_generation:
            return
        prev_ip = self.selected_device.ip if self.selected_device else None
        self.selected_device = None
        self.devices = devices
        self.device_table.setRowCount(len(devices))

        type_colors = {
            DeviceType.DLNA: QColor(C.ACCENT),
            DeviceType.AIRPLAY: QColor(C.PURPLE),
            DeviceType.CHROMECAST: QColor(C.PINK),
        }

        playback_ip = self.playback_device.ip if self.playback_device else None
        has_playback_device = False

        for i, d in enumerate(devices):
            name_item = QTableWidgetItem(d.name)
            name_item.setToolTip(d.name)
            self.device_table.setItem(i, 0, name_item)

            type_item = QTableWidgetItem(d.display_type)
            type_item.setForeground(type_colors.get(d.device_type, QColor(C.TEXT)))
            type_item.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            self.device_table.setItem(i, 1, type_item)

            self.device_table.setItem(i, 2, QTableWidgetItem(f"{d.ip}:{d.port}"))

            status_item = QTableWidgetItem("● Online")
            status_item.setForeground(QColor(C.SUCCESS))
            self.device_table.setItem(i, 3, status_item)

            if playback_ip and d.ip == playback_ip:
                has_playback_device = True
            if prev_ip and d.ip == prev_ip:
                self.device_table.selectRow(i)
                self.selected_device = d
            elif not self.selected_device and matches_device(self.resume_state, d):
                self.device_table.selectRow(i)
                self.selected_device = d

        self.device_count.setText(f"{len(devices)} device(s) found")
        self._fade_table_in()

        if not self.is_auto_refreshing:
            self._scan_anim.stop()
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("  Scan Devices")
            self.status_label.setText(f"Found {len(devices)} device(s)")
        else:
            self.scan_count += 1
            next_sec = self.refresh_interval.value()
            self.status_label.setText(f"Auto #{self.scan_count}: {len(devices)} device(s) — next in {next_sec}s")

        if self.is_playing and playback_ip and not has_playback_device:
            self._cleanup_local_playback()
            self._resume_attempted = False

        if self.selected_device and matches_device(self.resume_state, self.selected_device):
            self._auto_resume_if_ready()

    def _on_device_select(self):
        rows = self.device_table.selectionModel().selectedRows()
        if rows:
            idx = rows[0].row()
            if idx < len(self.devices):
                self.selected_device = self.devices[idx]
                self.status_label.setText(f"Selected {self.selected_device.name}; volume changes are sent live when supported")

    def _on_auto_resume_toggled(self, enabled: bool):
        with self._state_lock:
            self.resume_state = self.resume_state.__class__(**{**self.resume_state.__dict__, "auto_resume_enabled": enabled})
            state = self.resume_state
        save_state(state)
        if enabled:
            self._resume_attempted = False
            if self.selected_device and matches_device(self.resume_state, self.selected_device):
                self._auto_resume_if_ready()

    def _remember_playback(self, device: Device, source_type: str, auto_resume_enabled: bool, **values):
        state = state_for_device(device, source_type, **values)
        state = state.__class__(**{**state.__dict__, "auto_resume_enabled": auto_resume_enabled})
        with self._state_lock:
            self.resume_state = state
        save_state(state)

    def _auto_resume_if_ready(self):
        if self._resume_attempted or self.is_playing or not self.resume_state.auto_resume_enabled:
            return
        self._resume_attempted = True
        if self.resume_state.source_type == "media" and self.resume_state.media_path:
            path = Path(self.resume_state.media_path)
            if not path.exists():
                self.status_label.setText(f"Remembered file missing: {path.name}")
                return
            self.media_path = str(path)
            self.tabs.setCurrentIndex(0)
            self.media_path_label.setText(path.name)
            self.media_path_label.setToolTip(str(path))
            self.status_label.setText(f"Auto-resuming {path.name} on {self.selected_device.name}")
            self._on_play()
        elif self.resume_state.source_type == "live" and self.resume_state.live_url:
            self.tabs.setCurrentIndex(1)
            self.live_url_input.setText(self.resume_state.live_url)
            self.status_label.setText(f"Auto-resuming live URL on {self.selected_device.name}")
            self._on_play_live_url()
        elif self.resume_state.source_type in {"window", "screen"}:
            self.status_label.setText("Remembered capture source found; choose the window/screen again to cast")

    # ── Media File ─────────────────────────────────────────────────────────────

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
            self.media_path_label.setObjectName("subtitle")
            self.media_path_label.style().unpolish(self.media_path_label)
            self.media_path_label.style().polish(self.media_path_label)
            metrics = self.media_path_label.fontMetrics()
            elided = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, 280)
            self.media_path_label.setText(elided)
            self.media_path_label.setToolTip(filepath)
            self.status_label.setText(f"Selected: {name}")

    def _on_play(self):
        self._animate_button_click(self.play_btn)
        tab_text = self.tabs.tabText(self.tabs.currentIndex())
        if tab_text == "Window Cast":
            self._on_cast_window()
            return
        if tab_text == "Screen Cast":
            self._on_cast_screen()
            return
        if not self.selected_device:
            QMessageBox.warning(self, "Warning", "Please select a device first.")
            return
        if tab_text == "Live URL":
            self._on_play_live_url()
            return
        if not self.media_path:
            QMessageBox.warning(self, "Warning", "Please select a media file first.")
            return

        self._stop_local_services()
        self.is_playing = True
        self.status_label.setText(f"Playing on {self.selected_device.name}...")
        self.play_btn.setEnabled(False)

        device = self.selected_device
        media_path = self.media_path
        auto_resume_enabled = self.auto_resume_cb.isChecked()
        ext = Path(media_path).suffix.lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")

        def do_play():
            loop = asyncio.new_event_loop()
            try:
                if device.device_type == DeviceType.DLNA:
                    server = MediaServer()
                    server.start_background(target_ip=device.ip)
                    server.register_file(media_path)
                    url = server.get_url(media_path)
                    with self._state_lock:
                        self.media_server = server
                    loop.run_until_complete(dlna_controller.play(device, url, content_type))
                    self._set_playback_device(device)
                    self._remember_playback(device, "media", auto_resume_enabled, media_path=media_path)
                    self.bridge.status_update.emit(f"Playing on {device.name}")
                elif device.device_type == DeviceType.AIRPLAY:
                    try:
                        loop.run_until_complete(airplay_controller.play(device, media_path))
                        self._set_playback_device(device)
                        self._remember_playback(device, "media", auto_resume_enabled, media_path=media_path)
                        self.bridge.status_update.emit(f"Playing on {device.name}")
                    except Exception:
                        dlna_device = loop.run_until_complete(dlna_controller.discover_dlna(device.ip))
                        if not dlna_device:
                            raise RuntimeError(f"No DLNA service on {device.ip}")
                        server = MediaServer()
                        server.start_background(target_ip=dlna_device.ip)
                        server.register_file(media_path)
                        url = server.get_url(media_path)
                        with self._state_lock:
                            self.media_server = server
                        loop.run_until_complete(dlna_controller.play(dlna_device, url, content_type))
                        self._set_playback_device(dlna_device)
                        self._remember_playback(dlna_device, "media", auto_resume_enabled, media_path=media_path)
                        self.bridge.status_update.emit(f"Playing on {device.name} (via DLNA)")
                else:
                    self.bridge.error_occurred.emit(f"Unsupported: {device.device_type}")
            except Exception as e:
                self._cleanup_local_playback()
                self.bridge.error_occurred.emit(str(e))
            finally:
                self.bridge.playback_finished.emit()
                loop.close()

        threading.Thread(target=do_play, daemon=True).start()

    def _on_play_live_url(self):
        live_url = self.live_url_input.text().strip()
        if not live_url:
            QMessageBox.warning(self, "Warning", "Please paste a live URL first.")
            return

        self._stop_local_services()
        self.is_playing = True
        self.status_label.setText("Resolving live stream...")
        self.play_btn.setEnabled(False)
        device = self.selected_device
        auto_resume_enabled = self.auto_resume_cb.isChecked()

        def do_play_live():
            loop = asyncio.new_event_loop()
            try:
                stream_url, content_type = resolve_live_url(live_url)
                target_device = device
                if device.device_type == DeviceType.AIRPLAY:
                    dlna_device = loop.run_until_complete(dlna_controller.discover_dlna(device.ip))
                    if not dlna_device:
                        raise RuntimeError(f"No DLNA service found on {device.ip} for live casting")
                    target_device = dlna_device
                elif device.device_type != DeviceType.DLNA:
                    self.bridge.error_occurred.emit(f"Unsupported: {device.device_type}")
                    return

                server = MediaServer()
                server.start_background(target_ip=target_device.ip)
                transcoded_url = server.register_live_stream(stream_url, video_bitrate=self._video_bitrate())
                with self._state_lock:
                    self.media_server = server
                loop.run_until_complete(dlna_controller.play(target_device, transcoded_url, "video/mp2t"))
                self._set_playback_device(target_device)
                self._remember_playback(target_device, "live", auto_resume_enabled, live_url=redact_url(live_url))
                self.bridge.status_update.emit(f"Playing transcoded live stream on {device.name}")
            except Exception as e:
                self._cleanup_local_playback()
                self.bridge.error_occurred.emit(str(e))
            finally:
                self.bridge.playback_finished.emit()
                loop.close()

        threading.Thread(target=do_play_live, daemon=True).start()

    # ── Streaming (shared) ────────────────────────────────────────────────────

    def _start_stream(self, source_type: str, source_id, device: Device, label: str):
        fps = self.fps_slider.value()
        video_kbps = self._video_bitrate_kbps()
        auto_resume_enabled = self.auto_resume_cb.isChecked()
        self.streamer.fps = fps
        self.streamer.bitrate_limit = video_kbps // 8 if video_kbps else 0
        self.is_playing = True
        self.is_streaming = True

        def do_cast():
            loop = asyncio.new_event_loop()
            try:
                if source_type == "window":
                    self.streamer.start_window(source_id)
                else:
                    self.streamer.start_monitor(source_id)

                server = MediaServer()
                streamer_ref = self.streamer

                async def stream_handle(request):
                    from aiohttp import web
                    response = web.StreamResponse(
                        status=200, reason="OK",
                        headers={
                            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                        },
                    )
                    await response.prepare(request)
                    while self.is_streaming:
                        frame = streamer_ref.get_frame()
                        if frame:
                            await response.write(
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n"
                                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                                + frame + b"\r\n"
                            )
                        await asyncio.sleep(1.0 / streamer_ref.fps)
                    return response

                server._app.router.add_get("/stream", stream_handle)
                server.start_background(target_ip=device.ip)
                with self._state_lock:
                    self.media_server = server
                stream_url = f"http://{server._local_ip}:{server._actual_port}/stream"

                transcoded_url = server.register_live_stream(stream_url, input_format="mjpeg", video_bitrate=self._video_bitrate())
                target_device = device
                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.play(device, transcoded_url, "video/mp2t"))
                elif device.device_type == DeviceType.AIRPLAY:
                    dlna_device = loop.run_until_complete(dlna_controller.discover_dlna(device.ip))
                    if not dlna_device:
                        raise RuntimeError(f"No DLNA service found on {device.ip} for capture casting")
                    target_device = dlna_device
                    loop.run_until_complete(dlna_controller.play(dlna_device, transcoded_url, "video/mp2t"))
                else:
                    raise RuntimeError(f"Unsupported: {device.device_type}")

                self._set_playback_device(target_device)
                self._remember_playback(target_device, source_type, auto_resume_enabled, capture_label=label)
                self.bridge.status_update.emit(f"Casting {label} to {device.name}")
            except Exception as e:
                self._cleanup_local_playback()
                self.bridge.error_occurred.emit(str(e))
            finally:
                self.bridge.playback_finished.emit()
                loop.close()

        threading.Thread(target=do_cast, daemon=True).start()

    # ── Window Cast ───────────────────────────────────────────────────────────

    def _refresh_windows(self):
        self.window_list.clear()
        self.windows_list = list_windows()
        for w in self.windows_list:
            is_browser = w.process_name.lower().startswith(("chrome", "firefox", "edge"))
            icon = "◆" if is_browser else "■"
            item = QListWidgetItem(f"{icon}  {w.title}")
            item.setToolTip(f"Process: {w.process_name}\nPID: {w.pid}\nSize: {w.rect[2]}x{w.rect[3]}")
            if is_browser:
                item.setForeground(QColor(C.ACCENT))
            self.window_list.addItem(item)
        self.window_info_label.setText(f"{len(self.windows_list)} window(s)")

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
        self.cast_window_btn.setEnabled(False)
        self.status_label.setText(f"Casting '{window.title}'...")
        self._start_stream("window", window.hwnd, self.selected_device, f"'{window.title}'")

    # ── Screen Cast ───────────────────────────────────────────────────────────

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
        self.cast_screen_btn.setEnabled(False)
        self.status_label.setText(f"Casting {monitor['name']}...")
        self._start_stream("screen", monitor["index"], self.selected_device, monitor["name"])

    # ── Stop & Volume ─────────────────────────────────────────────────────────

    def _on_stop(self):
        self._animate_button_click(self.stop_btn)
        device = self._get_playback_device()
        if not device:
            return
        self.status_label.setText("Stopping...")

        if self.is_streaming:
            self.streamer.stop()
            self.is_streaming = False
            self.cast_window_btn.setEnabled(True)
            self.cast_screen_btn.setEnabled(True)

        def do_stop():
            loop = asyncio.new_event_loop()
            try:
                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.stop(device))
                elif device.device_type == DeviceType.AIRPLAY:
                    loop.run_until_complete(airplay_controller.stop(device))
                self.bridge.status_update.emit("Stopped")
            except Exception as e:
                self.bridge.error_occurred.emit(str(e))
            finally:
                self._cleanup_local_playback()
                loop.close()

        threading.Thread(target=do_stop, daemon=True).start()

    def _set_playback_device(self, device: Device | None):
        with self._state_lock:
            self.playback_device = device

    def _get_playback_device(self) -> Device | None:
        with self._state_lock:
            return self.playback_device or self.selected_device

    def _cleanup_local_playback(self):
        self.streamer.stop()
        self.is_playing = False
        self.is_streaming = False
        self.cast_window_btn.setEnabled(True)
        self.cast_screen_btn.setEnabled(True)
        self._stop_local_services()

    def _stop_local_services(self, loop: asyncio.AbstractEventLoop | None = None):
        with self._state_lock:
            server = self.media_server
            self.media_server = None
            self.playback_device = None
        if not server:
            return
        server.stop_background()

    def closeEvent(self, event):
        self.streamer.stop()
        self.is_streaming = False
        self._stop_local_services()
        event.accept()

    def _on_volume_change(self, value: int):
        self.volume_value.setText(f"{value}%")
        if not self.is_playing:
            return
        device = self._get_playback_device()
        if not device:
            return

        def do_volume():
            try:
                loop = asyncio.new_event_loop()
                if device.device_type == DeviceType.DLNA:
                    loop.run_until_complete(dlna_controller.set_volume(device, value))
                elif device.device_type == DeviceType.AIRPLAY:
                    loop.run_until_complete(airplay_controller.set_volume(device, value))
            except Exception as e:
                logger.warning(f"Volume update failed: {e}")
                self.bridge.status_update.emit(f"Volume update failed: {e}")
            finally:
                loop.close()

        threading.Thread(target=do_volume, daemon=True).start()

    def _on_bitrate_change(self, value: int):
        kbps = self._video_bitrate_kbps()
        if kbps == 0:
            self.bitrate_value.setText("Auto")
        else:
            self.bitrate_value.setText(self._format_video_bitrate(kbps))
        self.streamer.bitrate_limit = kbps // 8 if kbps else 0
        if self.is_playing:
            self.status_label.setText("Bitrate changes apply on the next play/cast")

    def _video_bitrate(self) -> str:
        kbps = self._video_bitrate_kbps()
        if kbps == 0:
            return "3500k"
        return f"{kbps}k"

    def _video_bitrate_kbps(self) -> int:
        return self.bitrate_slider.value() * 200

    def _format_video_bitrate(self, kbps: int) -> str:
        if kbps >= 1000 and kbps % 1000 == 0:
            return f"{kbps // 1000} Mbps"
        return f"{kbps} Kbps"

    # ── Status ────────────────────────────────────────────────────────────────

    def _on_status_update(self, msg: str):
        self.status_label.setText(msg)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        self._cleanup_local_playback()
        self.play_btn.setEnabled(True)

    def _on_playback_finished(self):
        self.play_btn.setEnabled(True)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    window = AutoCastGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
