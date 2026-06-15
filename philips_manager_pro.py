#!/usr/bin/env python3
__version__ = "3.4.0"
__build_date__ = "2026-06-15"

# ─────────────────────────────────────────────────────────────────────────────
# Auto-install required packages before anything else
# ─────────────────────────────────────────────────────────────────────────────
import sys
import subprocess
import importlib.util
import os

REQUIRED = [
    ("psutil",  "psutil"),
    ("PIL",     "Pillow"),
    ("PySide6", "PySide6"),
]

def _pip_install(pkg):
    print(f"Installing missing package: {pkg} …")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", pkg])

for _mod, _pkg in REQUIRED:
    if importlib.util.find_spec(_mod) is None:
        _pip_install(_pkg)

# ─────────────────────────────────────────────────────────────────────────────
# Standard / third-party imports
# ─────────────────────────────────────────────────────────────────────────────
import re
import io
import html
import shutil
import logging
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

import psutil
from PIL import Image, ImageOps

from PySide6.QtCore  import Qt, QTimer, QThread, Signal, QTime
from PySide6.QtGui   import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QTabWidget, QScrollArea, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QSlider, QComboBox, QLineEdit,
    QTextEdit, QSizePolicy, QMessageBox, QInputDialog,
    QFileDialog, QTimeEdit, QDialog,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
NS_MEDIA   = "{http://search.yahoo.com/mrss/}"

BLUE       = "#0B5ED7"
BLUE_LIGHT = "#E9EEF8"
RED        = "#C0392B"
GREEN      = "#118C4F"
SIDEBAR_BG = "#FFFFFF"
CARD_BG    = "#F9FAFC"
PANEL_BG   = "#F6F7FB"
WHITE      = "#FFFFFF"

# ─────────────────────────────────────────────────────────────────────────────
# Prefs: label↔value mappings  (display label → raw XML value)
# ─────────────────────────────────────────────────────────────────────────────
PREFS_MAP = {
    "twentyfour": [
        ("12h (AM/PM)",  "false"),
        ("24h (24-hour)","true"),
    ],
    "format": [
        ("Original (no crop)",    "0"),
        ("RadiantColor (enhance)","1"),
        ("Scale to fit",          "2"),
    ],
    "sequence": [
        ("In order",   "0"),
        ("Shuffle",    "1"),
    ],
    # Effect 0–16 (names from DPF manual, English UI)
    "effect": [
        ("No effect",            "0"),
        ("Random",               "1"),
        ("Pan and zoom",         "2"),
        ("Fade",                 "3"),
        ("Collage",              "4"),
        ("Steps",                "5"),
        ("Spiral",               "6"),
        ("Slide down",           "7"),
        ("Slide left",           "8"),
        ("Slide right",          "9"),
        ("Slide up",             "10"),
        ("Slide corner TL",      "11"),
        ("Slide corner BR",      "12"),
        ("Slide corner TR",      "13"),
        ("Slide corner BL",      "14"),
        ("Roll left",            "15"),
        ("Roll up",              "16"),
    ],
    "collage": [
        ("Off", "0"),
        ("On",  "1"),
    ],
    "calendar": [
        ("Week",   "0"),
        ("Month",  "1"),
        ("Clock",  "2"),
        ("None",   "3"),
    ],
    "open_at_startup": [
        ("Off – manual start", "0"),
        ("On  – auto start",   "1"),
    ],
    "auto_on_off": [
        ("Off (disabled)",     "0"),
        ("Time (schedule)",    "1"),
        ("Light + time",       "2"),
    ],
    "auto_tilt": [
        ("Off (manual)",     "false"),
        ("On  (automatic)",  "true"),
    ],
    "background_color": [
        ("Black",    "0"),
        ("White",    "1"),
        ("Gray",     "2"),
        ("Automatic","3"),
    ],
    "delete_enabled": [
        ("Delete disabled", "false"),
        ("Delete allowed",  "true"),
    ],
    "beep": [
        ("No sound", "false"),
        ("Beep on",  "true"),
    ],
    "demo_mode": [
        ("Normal",     "false"),
        ("Demo mode",  "true"),
    ],
    "language_code": [
        ("English (EN)",  "EN"),
        ("Deutsch (DE)",  "DE"),
        ("Français (FR)", "FR"),
        ("Español (ES)",  "ES"),
    ],
}

# Defaults as raw XML values (matching real .prefs)
PREFS_DEFAULTS = {
    "language_code":   "EN",
    "brightness":      "255",
    "twentyfour":      "false",
    "format":          "0",
    "timing":          "300",
    "sequence":        "0",
    "effect":          "0",
    "collage":         "0",
    "calendar":        "3",
    "open_at_startup": "1",
    "auto_on_off":     "2",
    "sensor_on":       "10",
    "sensor_off":      "4",
    "time_on":         "420",
    "time_off":        "1020",
    "auto_tilt":       "true",
    "background_color":"3",
    "delete_enabled":  "true",
    "beep":            "false",
    "demo_mode":       "false",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def parse_image_from_description(desc: str):
    if not desc:
        return None
    m = re.search(r'src=["\']([^"\']+)["\']', desc)
    return m.group(1) if m else None

def fetch_url_bytes(url: str, timeout: int = 15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        logging.error("Failed to load URL: %s (%s)", url, e)
        return None

def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def dir_stats(path: str):
    files = dirs = size = 0
    for root, subdirs, filenames in os.walk(path):
        dirs += len(subdirs)
        for fn in filenames:
            files += 1
            try:
                size += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return files, dirs, size

def pil_to_qpixmap(img: Image.Image, max_w: int = 0, max_h: int = 0) -> QPixmap:
    if max_w > 0 or max_h > 0:
        img = img.copy()
        img.thumbnail((max_w or 99999, max_h or 99999))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    data = img.tobytes("raw", img.mode)
    fmt  = QImage.Format.Format_RGBA8888 if img.mode == "RGBA" else QImage.Format.Format_RGB888
    qi   = QImage(data, img.width, img.height, fmt)
    return QPixmap.fromImage(qi)

def minutes_to_qtime(minutes: int) -> QTime:
    return QTime(minutes // 60, minutes % 60)

def qtime_to_minutes(t: QTime) -> int:
    return t.hour() * 60 + t.minute()

def btn(label: str, color: str = "", min_w: int = 0) -> QPushButton:
    b = QPushButton(label)
    style = "QPushButton { padding: 6px 14px; border-radius: 6px; font-size: 13px;"
    if color:
        style += f" background: {color}; color: white;"
    else:
        style += f" background: {BLUE}; color: white;"
    style += "} QPushButton:hover { filter: brightness(1.1); }"
    b.setStyleSheet(style)
    if min_w:
        b.setMinimumWidth(min_w)
    return b

def lbl(text: str, bold: bool = False, size: int = 13, color: str = "") -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    style = f"font-size: {size}px;"
    if bold:
        style += " font-weight: bold;"
    if color:
        style += f" color: {color};"
    l.setStyleSheet(style)
    return l

# ─────────────────────────────────────────────────────────────────────────────
# Prefs: combo helpers (display ↔ raw XML value)
# ─────────────────────────────────────────────────────────────────────────────
def make_map_combo(key: str, default_raw: str = "") -> QComboBox:
    """Create a QComboBox from PREFS_MAP[key]. Items show display labels."""
    cb = QComboBox()
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    pairs = PREFS_MAP[key]
    for display, _ in pairs:
        cb.addItem(display)
    raw_to_select = default_raw or PREFS_DEFAULTS.get(key, "")
    for i, (_, raw) in enumerate(pairs):
        if raw == raw_to_select:
            cb.setCurrentIndex(i)
            break
    return cb

def combo_get_raw(key: str, cb: QComboBox) -> str:
    idx = cb.currentIndex()
    pairs = PREFS_MAP.get(key, [])
    if 0 <= idx < len(pairs):
        return pairs[idx][1]
    return cb.currentText()

def combo_set_raw(key: str, cb: QComboBox, raw: str):
    pairs = PREFS_MAP.get(key, [])
    for i, (_, v) in enumerate(pairs):
        if v == raw:
            cb.setCurrentIndex(i)
            return
    idx = cb.findText(raw)
    if idx >= 0:
        cb.setCurrentIndex(idx)

# ─────────────────────────────────────────────────────────────────────────────
# Drop zone widget
# ─────────────────────────────────────────────────────────────────────────────
class DropZone(QLabel):
    paths_dropped = Signal(list)

    def __init__(self, text: str = "Drop album folders here", parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._normal_style()

    def _normal_style(self):
        self.setStyleSheet(
            f"background: {BLUE_LIGHT}; color: {BLUE}; border: 2px dashed {BLUE};"
            " border-radius: 10px; font-size: 14px; font-weight: bold; padding: 14px;"
        )

    def _hover_style(self):
        self.setStyleSheet(
            f"background: #C8D9F8; color: {BLUE}; border: 2px solid {BLUE};"
            " border-radius: 10px; font-size: 14px; font-weight: bold; padding: 14px;"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._normal_style()

    def dropEvent(self, event):
        self._normal_style()
        self.paths_dropped.emit([u.toLocalFile() for u in event.mimeData().urls()])

# ─────────────────────────────────────────────────────────────────────────────
# Image card
# ─────────────────────────────────────────────────────────────────────────────
class ImageCard(QFrame):
    edit_requested   = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, path: str, filename: str, thumb_size: int, parent=None):
        super().__init__(parent)
        self.path = path
        self.setStyleSheet(f"background: {CARD_BG}; border-radius: 12px;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setFixedSize(thumb_size, thumb_size)
        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)
            img_lbl.setPixmap(pil_to_qpixmap(img, thumb_size, thumb_size))
        except Exception:
            img_lbl.setText("Error")
        v.addWidget(img_lbl)

        name_lbl = QLabel(filename)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet("font-size: 11px;")
        name_lbl.setMaximumWidth(thumb_size + 20)
        v.addWidget(name_lbl)

        row = QHBoxLayout()
        row.setSpacing(4)
        b_edit   = btn("Edit",  min_w=60)
        b_rename = btn("✎",    min_w=30)
        b_del    = btn("🗑",  RED, min_w=30)
        b_edit.clicked.connect(lambda: self.edit_requested.emit(self.path))
        b_rename.clicked.connect(lambda: self.rename_requested.emit(self.path))
        b_del.clicked.connect(lambda: self.delete_requested.emit(self.path))
        row.addWidget(b_edit)
        row.addWidget(b_rename)
        row.addWidget(b_del)
        v.addLayout(row)

# ─────────────────────────────────────────────────────────────────────────────
# Editor canvas
# ─────────────────────────────────────────────────────────────────────────────
class EditorCanvas(QLabel):
    crop_point_picked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setStyleSheet("background: #F7F8FB;")
        self.crop_mode = False
        self._pixmap_orig: QPixmap | None = None
        self._img_size = (1, 1)

    def set_image(self, pil_img: Image.Image):
        self._img_size = pil_img.size
        px = pil_to_qpixmap(pil_img, 1100, 700)
        self._pixmap_orig = px
        self.setPixmap(px)
        self.setFixedSize(px.width() + 20, px.height() + 20)

    def mousePressEvent(self, event):
        if not self.crop_mode or self._pixmap_orig is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pw = self._pixmap_orig.width()
            ph = self._pixmap_orig.height()
            rx = int(event.position().x() * self._img_size[0] / pw)
            ry = int(event.position().y() * self._img_size[1] / ph)
            self.crop_point_picked.emit(rx, ry)

# ─────────────────────────────────────────────────────────────────────────────
# RSS fetch thread
# ─────────────────────────────────────────────────────────────────────────────
class RssFetchThread(QThread):
    done  = Signal(bytes)
    error = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        data = fetch_url_bytes(self.url)
        if data:
            self.done.emit(data)
        else:
            self.error.emit(f"Could not load: {self.url}")

# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Philips PhotoFrame Manager Pro v{__version__}")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        self.device_root: str | None        = None
        self.current_album_path: str | None = None
        self.current_album_name: str | None = None
        self.thumbnail_size     = 140
        self.album_page         = 0
        self.album_page_size    = 24
        self.album_items_current: list = []
        self.rss_feeds: list            = []
        self.rss_selected_index: int | None = None
        self.current_rss_feed           = None

        self.editor_original: Image.Image | None = None
        self.editor_work:     Image.Image | None = None
        self.current_edit_path: str | None       = None
        self.crop_points: list = []

        # Prefs widgets registry
        # Each entry: (widget, kind)
        # kind: "map_combo" | "slider" | "time" | "sensor_slider" | "line"
        self._prefs: dict[str, tuple] = {}

        # Extra refs for brightness and auto/sensor/time widgets
        self.brightness_slider:  QSlider | None = None
        self.brightness_val_lbl: QLabel  | None = None
        self.cb_auto_on_off:    QComboBox | None = None
        self.sensor_on_slider:  QSlider | None = None
        self.sensor_off_slider: QSlider | None = None
        self.time_on_edit:      QTimeEdit | None = None
        self.time_off_edit:     QTimeEdit | None = None

        self._rss_thread: RssFetchThread | None = None

        self._build_ui()
        self._apply_global_style()

        logging.info("Starting Philips PhotoFrame Manager Pro v%s (%s)", __version__, __build_date__)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_detect_tick)
        self._auto_timer.start(3000)
        QTimer.singleShot(1200, self._auto_detect_tick)

    # ── Global stylesheet ─────────────────────────────────────────────────────
    def _apply_global_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #F4F6FB; font-family: 'Segoe UI', Arial, sans-serif; }
            QTabWidget::pane  { border: none; background: #F4F6FB; }
            QTabBar::tab {
                background: #E2E8F4; color: #333; padding: 8px 22px;
                border-radius: 6px 6px 0 0; margin-right: 2px; font-size: 13px;
            }
            QTabBar::tab:selected { background: #0B5ED7; color: white; font-weight: bold; }
            QScrollArea  { border: none; }
            QLineEdit, QComboBox, QTextEdit, QTimeEdit {
                background: white; border: 1px solid #C8D3E8;
                border-radius: 6px; padding: 4px 8px; font-size: 13px;
            }
            QSlider::groove:horizontal { height: 6px; background: #C8D3E8; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #0B5ED7; width: 16px; height: 16px;
                border-radius: 8px; margin: -5px 0;
            }
            QSlider::sub-page:horizontal { background: #0B5ED7; border-radius: 3px; }
        """)

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        sidebar = self._build_sidebar()
        sidebar.setFixedWidth(290)
        splitter.addWidget(sidebar)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_albums_tab(), "Albums")
        self.tabs.addTab(self._build_editor_tab(), "Editor")
        self.tabs.addTab(self._build_prefs_tab(),  "Prefs")
        self.tabs.addTab(self._build_rss_tab(),    "RSS")
        self.tabs.addTab(self._build_tools_tab(),  "Tools")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {SIDEBAR_BG};")
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 22, 20, 20)
        v.setSpacing(6)

        title = QLabel("PHILIPS")
        title.setStyleSheet(f"color: {BLUE}; font-size: 32px; font-weight: bold;")
        v.addWidget(title)
        v.addWidget(lbl("PhotoFrame Manager Pro", size=14, color="#3C3C3C"))
        v.addWidget(lbl(f"Version {__version__} · Build {__build_date__}", size=11, color="#777"))
        v.addSpacing(8)

        self.status_lbl     = lbl("No device connected", color="#777")
        self.path_lbl       = lbl("Path: -",     color="#555")
        self.storage_lbl    = lbl("Storage: -",  color="#555")
        self.album_info_lbl = lbl("Albums: -",   color="#555")
        for w2 in [self.status_lbl, self.path_lbl, self.storage_lbl, self.album_info_lbl]:
            v.addWidget(w2)

        v.addSpacing(10)
        for label, slot in [
            ("Scan device",           self.scan_device),
            ("Select device manually", self.manual_select_device),
            ("Refresh",               self.refresh_all),
            ("Reload RSS",            self.load_rss_sources),
        ]:
            b = btn(label)
            b.clicked.connect(slot)
            v.addWidget(b)

        v.addSpacing(10)
        self.thumb_lbl = lbl(f"Thumbnail: {self.thumbnail_size}px")
        v.addWidget(self.thumb_lbl)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setMinimum(80); sl.setMaximum(240); sl.setValue(self.thumbnail_size)
        sl.valueChanged.connect(self._thumb_changed)
        v.addWidget(sl)

        v.addSpacing(6)
        v.addWidget(lbl("Images per page:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["12", "24", "48", "96"])
        self.page_size_combo.setCurrentText("24")
        self.page_size_combo.currentTextChanged.connect(self._page_size_changed)
        v.addWidget(self.page_size_combo)

        v.addStretch()
        v.addWidget(lbl("All actions are logged to the terminal.", size=11, color="#666"))
        return w

    def _thumb_changed(self, val: int):
        self.thumbnail_size = val
        self.thumb_lbl.setText(f"Thumbnail: {val}px")
        self.refresh_album_view()

    def _page_size_changed(self, val: str):
        try:
            self.album_page_size = int(val)
        except ValueError:
            self.album_page_size = 24
        self.album_page = 0
        self.refresh_album_view()

    # ── Albums tab ────────────────────────────────────────────────────────────
    def _build_albums_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        left = QFrame()
        left.setFixedWidth(300)
        left.setStyleSheet(f"background: {PANEL_BG}; border-radius: 12px;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)

        self.drop_zone = DropZone("⬇  Drop album folders here")
        self.drop_zone.setMinimumHeight(70)
        self.drop_zone.paths_dropped.connect(self._on_drop_albums)
        lv.addWidget(self.drop_zone)
        lv.addWidget(lbl("Detected albums", bold=True, size=14))

        self.album_list_widget = QWidget()
        self.album_list_layout = QVBoxLayout(self.album_list_widget)
        self.album_list_layout.setSpacing(4)
        self.album_list_layout.setContentsMargins(0, 0, 0, 0)
        self.album_list_layout.addStretch()
        sa = QScrollArea()
        sa.setWidget(self.album_list_widget)
        sa.setWidgetResizable(True)
        sa.setStyleSheet("background: transparent;")
        lv.addWidget(sa, 1)
        h.addWidget(left)

        right = QFrame()
        right.setStyleSheet(f"background: {WHITE}; border-radius: 12px;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)

        topbar = QHBoxLayout()
        self.album_title_lbl = lbl("No album selected", bold=True, size=16)
        topbar.addWidget(self.album_title_lbl, 1)
        self.page_info_lbl = lbl("Page 0/0")
        topbar.addWidget(self.page_info_lbl)
        b_prev = btn("◀", min_w=36); b_next = btn("▶", min_w=36)
        b_prev.clicked.connect(self.prev_page)
        b_next.clicked.connect(self.next_page)
        topbar.addWidget(b_prev); topbar.addWidget(b_next)
        rv.addLayout(topbar)

        self.album_loading_lbl = lbl("", color="#888")
        rv.addWidget(self.album_loading_lbl)

        self.image_area_widget = QWidget()
        self.image_area_layout = QGridLayout(self.image_area_widget)
        self.image_area_layout.setSpacing(10)
        self.image_area_layout.setContentsMargins(0, 0, 0, 0)
        si = QScrollArea()
        si.setWidget(self.image_area_widget)
        si.setWidgetResizable(True)
        rv.addWidget(si, 1)
        h.addWidget(right, 1)
        return w

    # ── Editor tab ────────────────────────────────────────────────────────────
    def _build_editor_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)

        top = QFrame()
        top.setStyleSheet(f"background: {WHITE}; border-radius: 8px;")
        th = QHBoxLayout(top)
        self.editor_title_lbl = lbl("No image loaded", bold=True, size=16)
        th.addWidget(self.editor_title_lbl, 1)
        for label, slot in [
            ("Rotate 90° left",  self.rotate_left),
            ("Rotate 90° right", self.rotate_right),
            ("Custom angle",     self.rotate_custom),
            ("Crop mode",        self.toggle_crop_mode),
            ("Reset",            self.reset_editor),
        ]:
            b = btn(label); b.clicked.connect(slot); th.addWidget(b)
        bs = btn("Save", BLUE)
        bs.clicked.connect(self.save_editor_image)
        th.addWidget(bs)
        v.addWidget(top)

        self.editor_canvas = EditorCanvas()
        self.editor_canvas.crop_point_picked.connect(self._on_crop_point)
        se = QScrollArea()
        se.setWidget(self.editor_canvas)
        se.setWidgetResizable(False)
        se.setStyleSheet("background: #F7F8FB;")
        v.addWidget(se, 1)

        bot = QFrame()
        bot.setStyleSheet(f"background: {WHITE}; border-radius: 8px;")
        bh = QHBoxLayout(bot)
        for label, slot in [
            ("Open image",   self.open_image_file),
            ("Rename image", self.rename_current_image),
            ("Delete image", self.delete_current_image),
            ("Save as copy", self.save_as_copy),
        ]:
            b = btn(label); b.clicked.connect(slot); bh.addWidget(b)
        v.addWidget(bot)
        return w

    # ── Prefs tab ─────────────────────────────────────────────────────────────
    def _build_prefs_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setStyleSheet(f"background: {WHITE};")
        form = QFormLayout(inner)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # ── Section: Language & Display ───────────────────────────────────────
        form.addRow(self._section_label("🌐  Language & display"))

        cb_lang = make_map_combo("language_code")
        self._prefs["language_code"] = (cb_lang, "map_combo")
        form.addRow("Language:", cb_lang)

        bri_container = QWidget()
        bh = QHBoxLayout(bri_container)
        bh.setContentsMargins(0, 0, 0, 0)
        sl_bri = QSlider(Qt.Orientation.Horizontal)
        sl_bri.setMinimum(0); sl_bri.setMaximum(255)
        sl_bri.setValue(int(PREFS_DEFAULTS["brightness"]))
        sl_bri.setFixedWidth(220)
        lbl_bri = QLabel(PREFS_DEFAULTS["brightness"])
        lbl_bri.setFixedWidth(36)
        sl_bri.valueChanged.connect(lambda v, l=lbl_bri: l.setText(str(v)))
        bh.addWidget(sl_bri)
        bh.addWidget(lbl_bri)
        bh.addWidget(lbl("(0 = dark, 255 = bright)", size=11, color="#888"))
        bh.addStretch()
        self.brightness_slider  = sl_bri
        self.brightness_val_lbl = lbl_bri
        self._prefs["brightness"] = (sl_bri, "slider")
        form.addRow("Brightness:", bri_container)

        cb_24h = make_map_combo("twentyfour")
        self._prefs["twentyfour"] = (cb_24h, "map_combo")
        form.addRow("Clock format:", cb_24h)

        # ── Section: Slideshow ────────────────────────────────────────────────
        form.addRow(self._section_label("🖼  Slideshow"))

        cb_fmt = make_map_combo("format")
        self._prefs["format"] = (cb_fmt, "map_combo")
        form.addRow("Image format:", cb_fmt)

        timing_container = QWidget()
        th = QHBoxLayout(timing_container)
        th.setContentsMargins(0, 0, 0, 0)
        sl_tim = QSlider(Qt.Orientation.Horizontal)
        sl_tim.setMinimum(5); sl_tim.setMaximum(3600)
        sl_tim.setValue(int(PREFS_DEFAULTS["timing"]))
        sl_tim.setFixedWidth(220)
        lbl_tim = QLabel(f"{PREFS_DEFAULTS['timing']} s")
        lbl_tim.setFixedWidth(60)
        sl_tim.valueChanged.connect(lambda v, l=lbl_tim: l.setText(f"{v} s"))
        th.addWidget(sl_tim); th.addWidget(lbl_tim)
        th.addWidget(lbl("(5 s … 3600 s)", size=11, color="#888")); th.addStretch()
        self._prefs["timing"] = (sl_tim, "slider")
        form.addRow("Interval:", timing_container)

        cb_seq = make_map_combo("sequence")
        self._prefs["sequence"] = (cb_seq, "map_combo")
        form.addRow("Order:", cb_seq)

        cb_eff = make_map_combo("effect")
        self._prefs["effect"] = (cb_eff, "map_combo")
        form.addRow("Transition:", cb_eff)

        cb_col = make_map_combo("collage")
        self._prefs["collage"] = (cb_col, "map_combo")
        form.addRow("Collage:", cb_col)

        cb_cal = make_map_combo("calendar")
        self._prefs["calendar"] = (cb_cal, "map_combo")
        form.addRow("Calendar/clock:", cb_cal)

        # ── Section: Power control ────────────────────────────────────────────
        form.addRow(self._section_label("⏰  Power control"))

        cb_oast = make_map_combo("open_at_startup")
        self._prefs["open_at_startup"] = (cb_oast, "map_combo")
        form.addRow("Start at power on:", cb_oast)

        cb_aoo = make_map_combo("auto_on_off")
        self._prefs["auto_on_off"] = (cb_aoo, "map_combo")
        self.cb_auto_on_off = cb_aoo
        form.addRow("Auto on/off:", cb_aoo)

        s_on_c = QWidget()
        so_h = QHBoxLayout(s_on_c)
        so_h.setContentsMargins(0, 0, 0, 0)
        sl_son = QSlider(Qt.Orientation.Horizontal)
        sl_son.setMinimum(0); sl_son.setMaximum(10)
        sl_son.setValue(int(PREFS_DEFAULTS["sensor_on"]))
        sl_son.setFixedWidth(160)
        lbl_son = QLabel(PREFS_DEFAULTS["sensor_on"])
        lbl_son.setFixedWidth(28)
        sl_son.valueChanged.connect(lambda v, l=lbl_son: l.setText(str(v)))
        so_h.addWidget(sl_son); so_h.addWidget(lbl_son)
        so_h.addWidget(lbl("(0 = dark, 10 = bright → turn ON)", size=11, color="#888"))
        so_h.addStretch()
        self._prefs["sensor_on"] = (sl_son, "slider")
        self.sensor_on_slider = sl_son
        form.addRow("Light sensor ON (max):", s_on_c)

        s_off_c = QWidget()
        sof_h = QHBoxLayout(s_off_c)
        sof_h.setContentsMargins(0, 0, 0, 0)
        sl_sof = QSlider(Qt.Orientation.Horizontal)
        sl_sof.setMinimum(0); sl_sof.setMaximum(10)
        sl_sof.setValue(int(PREFS_DEFAULTS["sensor_off"]))
        sl_sof.setFixedWidth(160)
        lbl_sof = QLabel(PREFS_DEFAULTS["sensor_off"])
        lbl_sof.setFixedWidth(28)
        sl_sof.valueChanged.connect(lambda v, l=lbl_sof: l.setText(str(v)))
        sof_h.addWidget(sl_sof); sof_h.addWidget(lbl_sof)
        sof_h.addWidget(lbl("(must be lower than ON)", size=11, color="#888"))
        sof_h.addStretch()
        self._prefs["sensor_off"] = (sl_sof, "slider")
        self.sensor_off_slider = sl_sof
        form.addRow("Light sensor OFF (min):", s_off_c)

        te_on = QTimeEdit()
        te_on.setDisplayFormat("HH:mm")
        te_on.setTime(minutes_to_qtime(int(PREFS_DEFAULTS["time_on"])))
        te_on.setFixedWidth(100)
        te_on_c = QWidget()
        te_on_h = QHBoxLayout(te_on_c)
        te_on_h.setContentsMargins(0, 0, 0, 0)
        te_on_h.addWidget(te_on)
        te_on_h.addWidget(lbl("frame switches ON", size=11, color="#888"))
        te_on_h.addStretch()
        self._prefs["time_on"] = (te_on, "time")
        self.time_on_edit = te_on
        form.addRow("Power on time:", te_on_c)

        te_off = QTimeEdit()
        te_off.setDisplayFormat("HH:mm")
        te_off.setTime(minutes_to_qtime(int(PREFS_DEFAULTS["time_off"])))
        te_off.setFixedWidth(100)
        te_off_c = QWidget()
        te_off_h = QHBoxLayout(te_off_c)
        te_off_h.setContentsMargins(0, 0, 0, 0)
        te_off_h.addWidget(te_off)
        te_off_h.addWidget(lbl("frame switches OFF", size=11, color="#888"))
        te_off_h.addStretch()
        self._prefs["time_off"] = (te_off, "time")
        self.time_off_edit = te_off
        form.addRow("Power off time:", te_off_c)

        # ── Section: Misc ─────────────────────────────────────────────────────
        form.addRow(self._section_label("⚙️  Misc"))

        cb_tilt = make_map_combo("auto_tilt")
        self._prefs["auto_tilt"] = (cb_tilt, "map_combo")
        form.addRow("Auto orientation:", cb_tilt)

        cb_bg = make_map_combo("background_color")
        self._prefs["background_color"] = (cb_bg, "map_combo")
        form.addRow("Background color:", cb_bg)

        cb_del = make_map_combo("delete_enabled")
        self._prefs["delete_enabled"] = (cb_del, "map_combo")
        form.addRow("Delete from frame:", cb_del)

        cb_beep = make_map_combo("beep")
        self._prefs["beep"] = (cb_beep, "map_combo")
        form.addRow("Sound:", cb_beep)

        cb_demo = make_map_combo("demo_mode")
        self._prefs["demo_mode"] = (cb_demo, "map_combo")
        form.addRow("Demo mode:", cb_demo)

        # Buttons
        btn_row = QHBoxLayout()
        b_load = btn("⬇  Load prefs")
        b_save = btn("💾  Save prefs")
        b_load.clicked.connect(self.load_prefs)
        b_save.clicked.connect(self.save_prefs)
        btn_row.addWidget(b_load); btn_row.addWidget(b_save)
        form.addRow(btn_row)

        # connect auto_on_off behavior
        cb_aoo.currentIndexChanged.connect(self._update_auto_on_off_widgets)
        self._update_auto_on_off_widgets()

        scroll.setWidget(inner)
        ov.addWidget(scroll)
        return outer

    @staticmethod
    def _section_label(title: str) -> QLabel:
        l = QLabel(title)
        l.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #0B5ED7;"
            " padding-top: 14px; padding-bottom: 2px;"
        )
        return l

    # ── Prefs get / set ───────────────────────────────────────────────────────
    def _prefs_get(self, key: str) -> str:
        entry = self._prefs.get(key)
        if not entry:
            return ""
        widget, kind = entry
        if kind == "map_combo":
            return combo_get_raw(key, widget)
        if kind == "slider":
            return str(widget.value())
        if kind == "time":
            return str(qtime_to_minutes(widget.time()))
        return ""

    def _prefs_set(self, key: str, value: str):
        entry = self._prefs.get(key)
        if not entry:
            return
        widget, kind = entry
        if kind == "map_combo":
            combo_set_raw(key, widget, value)
        elif kind == "slider":
            try:
                v = int(float(value))
                widget.setValue(v)
                if key == "brightness" and self.brightness_val_lbl:
                    self.brightness_val_lbl.setText(str(v))
            except ValueError:
                pass
        elif kind == "time":
            try:
                widget.setTime(minutes_to_qtime(int(value)))
            except ValueError:
                pass

        if key == "auto_on_off" and self.cb_auto_on_off is not None:
            self._update_auto_on_off_widgets()

    def _update_auto_on_off_widgets(self):
        if self.cb_auto_on_off is None:
            return
        mode_raw = combo_get_raw("auto_on_off", self.cb_auto_on_off)
        # 0 = Off, 1 = Time, 2 = Light+time
        sensor_enabled = mode_raw == "2"
        time_enabled   = mode_raw in ("1", "2")
        if self.sensor_on_slider:
            self.sensor_on_slider.setEnabled(sensor_enabled)
        if self.sensor_off_slider:
            self.sensor_off_slider.setEnabled(sensor_enabled)
        if self.time_on_edit:
            self.time_on_edit.setEnabled(time_enabled)
        if self.time_off_edit:
            self.time_off_edit.setEnabled(time_enabled)

    # ── RSS tab ───────────────────────────────────────────────────────────────
    def _build_rss_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        left = QFrame()
        left.setFixedWidth(290)
        left.setStyleSheet(f"background: {PANEL_BG}; border-radius: 12px;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.addWidget(lbl("RSS feeds", bold=True, size=14))

        rb = QHBoxLayout()
        ba = btn("Add feed"); bs = btn("Save feeds")
        ba.clicked.connect(self.add_rss_feed)
        bs.clicked.connect(self.save_rss_feeds)
        rb.addWidget(ba); rb.addWidget(bs)
        lv.addLayout(rb)

        self.feed_list_widget = QWidget()
        self.feed_list_layout = QVBoxLayout(self.feed_list_widget)
        self.feed_list_layout.setSpacing(4)
        self.feed_list_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_list_layout.addStretch()
        sf = QScrollArea(); sf.setWidget(self.feed_list_widget); sf.setWidgetResizable(True)
        lv.addWidget(sf, 1)

        br = btn("Reload feeds"); bd = btn("Delete feed", RED)
        br.clicked.connect(self.load_rss_sources)
        bd.clicked.connect(self.delete_selected_feed)
        lv.addWidget(br); lv.addWidget(bd)
        h.addWidget(left)

        right = QFrame()
        right.setStyleSheet(f"background: {WHITE}; border-radius: 12px;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)
        self.feed_title_lbl = lbl("No feed selected", bold=True, size=16)
        self.feed_meta_lbl  = lbl("", color="#666")
        rv.addWidget(self.feed_title_lbl)
        rv.addWidget(self.feed_meta_lbl)

        self.feed_gallery_widget = QWidget()
        self.feed_gallery_layout = QGridLayout(self.feed_gallery_widget)
        self.feed_gallery_layout.setSpacing(10)
        sg = QScrollArea(); sg.setWidget(self.feed_gallery_widget); sg.setWidgetResizable(True)
        rv.addWidget(sg, 1)
        h.addWidget(right, 1)
        return w

    # ── Tools tab ─────────────────────────────────────────────────────────────
    def _build_tools_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(10)
        v.addWidget(lbl("Device and folder statistics", bold=True, size=18))
        for label, slot in [
            ("Reload everything",   self.refresh_all),
            ("Scan device",         self.scan_device),
            ("Import album/folder", self.import_album_folder),
            ("Create backup (ZIP)", self.create_backup),
            ("Restore backup",      self.restore_backup),
        ]:
            b = btn(label); b.clicked.connect(slot); v.addWidget(b)

        b_dbg_prefs = btn("🔍  Debug: .prefs anzeigen", color="#5A4FCF")
        b_dbg_rss   = btn("🔍  Debug: rss.cfg anzeigen", color="#5A4FCF")
        b_dbg_prefs.clicked.connect(self.show_prefs_raw)
        b_dbg_rss.clicked.connect(self.show_rss_raw)
        v.addWidget(b_dbg_prefs)
        v.addWidget(b_dbg_rss)

        bx = btn("Exit", RED)
        bx.clicked.connect(self.close)
        v.addWidget(bx)
        self.stats_box = QTextEdit()
        self.stats_box.setReadOnly(True)
        self.stats_box.setStyleSheet(f"background: {WHITE}; border-radius: 8px; font-family: monospace;")
        v.addWidget(self.stats_box, 1)
        return w

    # ── Debug / prefs snapshot ────────────────────────────────────────────────
    def _current_prefs_as_xml(self) -> str:
        """Create a prefs XML that matches the real .prefs structure."""
        root = ET.Element("plist")
        setup = ET.SubElement(root, "setup")
        # Fixed order to mimic device .prefs
        order = [
            "language_code",
            "brightness",
            "twentyfour",
            "format",
            "timing",
            "sequence",
            "effect",
            "collage",
            "calendar",
            "open_at_startup",
            "auto_on_off",
            "sensor_on",
            "sensor_off",
            "time_on",
            "time_off",
            "auto_tilt",
            "background_color",
            "delete_enabled",
            "beep",
            "demo_mode",
        ]
        for key in order:
            node = ET.SubElement(setup, key)
            node.text = self._prefs_get(key)
        return ET.tostring(root, encoding="unicode")

    def _show_raw_file(self, filepath: str, title: str):
        if not filepath and title == ".prefs":
            content = self._current_prefs_as_xml()
            logging.info("[Debug] In-memory prefs snapshot (synthetic .prefs):\n%s", content)
            source = "In-memory prefs (no device, synthetic .prefs)"
        else:
            if not filepath:
                QMessageBox.warning(self, title, "No device connected.")
                return
            if not os.path.exists(filepath):
                msg = f"File not found:\n{filepath}"
                logging.warning("[Debug] %s – %s", title, msg)
                QMessageBox.warning(self, title, msg)
                return
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except Exception as e:
                msg = f"Error reading file:\n{filepath}\n\n{e}"
                logging.error("[Debug] %s – %s", title, msg)
                QMessageBox.critical(self, title, msg)
                return
            logging.info("[Debug] %s (%s):\n%s", title, filepath, content)
            source = filepath

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Debug – {title}")
        dlg.resize(800, 560)
        vlay = QVBoxLayout(dlg)
        vlay.setContentsMargins(12, 12, 12, 12)

        info = QLabel(f"<b>{source}</b>")
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 12px; color: #555; padding-bottom: 6px;")
        vlay.addWidget(info)

        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(content)
        te.setStyleSheet(
            "font-family: 'Courier New', Consolas, monospace; font-size: 13px;"
            f" background: {WHITE}; border: 1px solid #C8D3E8; border-radius: 6px;"
        )
        vlay.addWidget(te, 1)

        b_close = btn("Close", color="#666")
        b_close.clicked.connect(dlg.accept)
        vlay.addWidget(b_close)

        dlg.exec()

    def show_prefs_raw(self):
        if not self.device_root:
            self._show_raw_file("", ".prefs")
            return
        self._show_raw_file(os.path.join(self.device_root, ".prefs"), ".prefs")

    def show_rss_raw(self):
        if not self.device_root:
            self._show_raw_file("", "rss.cfg")
            return
        self._show_raw_file(os.path.join(self.device_root, ".config", "rss.cfg"), "rss.cfg")

    # ── Auto detect ───────────────────────────────────────────────────────────
    def _auto_detect_tick(self):
        try:
            self.scan_device(silent=True)
        except Exception:
            logging.exception("Auto-detect error")

    def manual_select_device(self):
        path = QFileDialog.getExistingDirectory(self, "Select PhotoFrame device folder")
        if not path:
            return
        self.device_root = path
        self.status_lbl.setText("Device (manual) connected")
        self.status_lbl.setStyleSheet(f"color: {GREEN};")
        self.path_lbl.setText(f"Path: {path}")
        self.refresh_all()

    def scan_device(self, silent: bool = False):
        try:
            found   = self._find_device_root()
            changed = found != self.device_root
            self.device_root = found
            if found:
                self.status_lbl.setText("Device connected")
                self.status_lbl.setStyleSheet(f"color: {GREEN};")
                self.path_lbl.setText(f"Path: {found}")
                self._update_storage_info()
                self._update_album_info()
                if changed:
                    logging.info("Device detected: %s", found)
                    self.refresh_all()
            else:
                self.status_lbl.setText("No device connected")
                self.status_lbl.setStyleSheet("color: #8A8A8A;")
                self.path_lbl.setText("Path: -")
                self.storage_lbl.setText("Storage: -")
                self.album_info_lbl.setText("Albums: -")
                if changed:
                    logging.info("Device disconnected")
                    self._clear_album_view()
            if not silent and not found:
                QMessageBox.warning(self, "Device not found",
                                    "No Philips PhotoFrame mountpoint detected.")
        except Exception:
            logging.exception("Scan error")

    def _find_device_root(self) -> str | None:
        candidates = []
        try:
            for part in psutil.disk_partitions(all=False):
                mp = part.mountpoint
                if not mp or not os.path.isdir(mp):
                    continue
                score = 0
                if os.path.exists(os.path.join(mp, ".prefs")):             score += 3
                if os.path.exists(os.path.join(mp, ".config", "rss.cfg")): score += 2
                if os.path.isdir(os.path.join(mp, "ALBUM")):               score += 4
                if os.path.isdir(os.path.join(mp, "Album")):               score += 4
                if score > 0:
                    candidates.append((score, mp))
        except Exception:
            logging.exception("disk_partitions failed")
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][1]

    # ── Refresh ───────────────────────────────────────────────────────────────
    def refresh_all(self):
        self.refresh_album_list()
        self.load_prefs()
        self.load_rss_sources()
        self._update_storage_info()
        self._update_album_info()
        self.refresh_album_view()
        self._refresh_stats()

    def _update_storage_info(self):
        if not self.device_root:
            return
        try:
            u = shutil.disk_usage(self.device_root)
            self.storage_lbl.setText(
                f"Storage: free {human_size(u.free)} / total {human_size(u.total)}"
            )
        except Exception:
            logging.exception("Storage info failed")

    def _album_root(self) -> str | None:
        if not self.device_root:
            return None
        for folder in ("ALBUM", "Album"):
            p = os.path.join(self.device_root, folder)
            if os.path.isdir(p):
                return p
        p = os.path.join(self.device_root, "ALBUM")
        try:
            os.makedirs(p, exist_ok=True)
            return p
        except Exception:
            return None

    def _update_album_info(self):
        root = self._album_root()
        if not root:
            self.album_info_lbl.setText("Albums: -")
            return
        try:
            albums = [os.path.join(root, d) for d in sorted(os.listdir(root))
                      if os.path.isdir(os.path.join(root, d))]
            total = sum(
                len([x for x in os.listdir(p)
                     if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                     and os.path.isfile(os.path.join(p, x))])
                for p in albums
            )
            self.album_info_lbl.setText(f"Albums: {len(albums)} folders · {total} images")
        except Exception:
            logging.exception("Album info failed")

    def _refresh_stats(self):
        if not self.device_root:
            return
        root = self._album_root()
        if not root:
            return
        lines = [f"Device: {self.device_root}", f"Build: {__version__} / {__build_date__}", ""]
        try:
            for d in sorted(os.listdir(root)):
                p = os.path.join(root, d)
                if os.path.isdir(p):
                    files, subdirs, size = dir_stats(p)
                    ic = len([x for x in os.listdir(p)
                              if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                              and os.path.isfile(os.path.join(p, x))])
                    lines.append(f"{d}: {ic} images, {files} files, "
                                 f"{subdirs} subfolders, {human_size(size)}")
        except Exception:
            logging.exception("Stats failed")
        self.stats_box.setPlainText("\n".join(lines))

    # ── Albums / editor / backup / RSS etc. (unchanged logic from 3.3.0) ─────
    # …

    # ── Prefs load / save ─────────────────────────────────────────────────────
    def load_prefs(self):
        if not self.device_root:
            return
        prefs_file = os.path.join(self.device_root, ".prefs")
        if not os.path.exists(prefs_file):
            logging.warning(".prefs not found: %s", prefs_file)
            return
        try:
            tree = ET.parse(prefs_file)
            root = tree.getroot()
            for setup in root.iter("setup"):
                for key in self._prefs:
                    node = setup.find(key)
                    if node is not None and node.text is not None:
                        self._prefs_set(key, node.text)
            logging.info(".prefs loaded")
            self._update_auto_on_off_widgets()
        except Exception:
            logging.exception("Prefs load failed")

    def save_prefs(self):
        if not self.device_root:
            return
        prefs_file = os.path.join(self.device_root, ".prefs")
        if not os.path.exists(prefs_file):
            QMessageBox.warning(self, "Prefs", ".prefs not found on device.")
            return

        sensor_on  = int(self._prefs_get("sensor_on") or "0")
        sensor_off = int(self._prefs_get("sensor_off") or "0")
        if sensor_on <= sensor_off:
            QMessageBox.warning(
                self,
                "Light sensor",
                "'ON (max)' must be greater than 'OFF (min)'.\n"
                "Please adjust the sliders before saving.",
            )
            return

        raw_preview = self._current_prefs_as_xml()
        reply_dbg = QMessageBox.question(
            self,
            "Save prefs",
            "Do you want to inspect the raw prefs before saving?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply_dbg == QMessageBox.StandardButton.Yes:
            logging.info("[Debug] Raw prefs to be saved:\n%s", raw_preview)
            dlg = QDialog(self)
            dlg.setWindowTitle("Prefs – raw preview")
            dlg.resize(800, 560)
            vlay = QVBoxLayout(dlg)
            vlay.setContentsMargins(12, 12, 12, 12)
            info = QLabel("These are the values that will be written to .prefs.")
            info.setWordWrap(True)
            info.setStyleSheet("font-size: 12px; color: #555; padding-bottom: 6px;")
            vlay.addWidget(info)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(raw_preview)
            te.setStyleSheet(
                "font-family: 'Courier New', Consolas, monospace; font-size: 13px;"
                f" background: {WHITE}; border: 1px solid #C8D3E8; border-radius: 6px;"
            )
            vlay.addWidget(te, 1)
            row = QHBoxLayout()
            b_cancel = btn("Cancel", color="#666")
            b_ok     = btn("Write .prefs")
            b_cancel.clicked.connect(dlg.reject)
            b_ok.clicked.connect(dlg.accept)
            row.addWidget(b_cancel); row.addWidget(b_ok)
            vlay.addLayout(row)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

        backup_path = prefs_file + ".bak"
        try:
            shutil.copy2(prefs_file, backup_path)
            logging.info(".prefs backup created: %s", backup_path)
        except Exception:
            logging.exception("Prefs backup failed")

        try:
            tree = ET.parse(prefs_file)
            root = tree.getroot()
            for setup in root.iter("setup"):
                for key in self._prefs:
                    node = setup.find(key)
                    if node is not None:
                        node.text = self._prefs_get(key)
            tree.write(prefs_file, encoding="UTF-8", xml_declaration=True)
            logging.info(".prefs saved")
            QMessageBox.information(self, "Saved", "Preferences saved.")
        except Exception:
            logging.exception("Prefs save failed")
            QMessageBox.critical(self, "Error", "Preferences could not be saved.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Philips PhotoFrame Manager Pro")
    app.setApplicationVersion(__version__)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
