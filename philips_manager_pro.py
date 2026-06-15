#!/usr/bin/env python3
__version__ = "3.0.0"
__build_date__ = "2026-06-15"

# ─────────────────────────────────────────────────────────────────────────────
# Auto-install required packages before anything else
# ─────────────────────────────────────────────────────────────────────────────
import sys
import subprocess
import importlib.util
import os

REQUIRED = [
    ("psutil",   "psutil"),
    ("PIL",      "Pillow"),
    ("PySide6",  "PySide6"),
]

def _pip_install(pkg):
    print(f"Installing missing package: {pkg} …")
    cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", pkg]
    subprocess.check_call(cmd)

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
from pathlib import Path

import psutil
from PIL import Image, ImageOps

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QSize, QPoint, QRect,
)
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPalette, QIcon,
    QPainter, QPen, QBrush, QAction,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QTabWidget, QScrollArea, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QSlider, QComboBox, QLineEdit,
    QTextEdit, QSizePolicy, QMessageBox, QInputDialog,
    QFileDialog, QScrollBar, QSpacerItem,
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

def btn(label: str, color: str = "", min_w: int = 0) -> QPushButton:
    b = QPushButton(label)
    style = "QPushButton { padding: 6px 14px; border-radius: 6px; font-size: 13px;"
    if color:
        style += f" background: {color}; color: white;"
    else:
        style += " background: #0B5ED7; color: white;"
    style += "} QPushButton:hover { opacity: 0.85; filter: brightness(1.1); }"
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
# Drag & Drop drop zone widget (pure Qt, no tkinterdnd2)
# ─────────────────────────────────────────────────────────────────────────────
class DropZone(QLabel):
    """A label that accepts folder/file drops and emits paths_dropped."""
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
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self.paths_dropped.emit(paths)

# ─────────────────────────────────────────────────────────────────────────────
# Image card widget for album view
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
            px  = pil_to_qpixmap(img, thumb_size, thumb_size)
            img_lbl.setPixmap(px)
        except Exception:
            img_lbl.setText("Error")
        v.addWidget(img_lbl)

        name_lbl = QLabel(filename)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet("font-size: 11px;")
        name_lbl.setMaximumWidth(thumb_size + 20)
        v.addWidget(name_lbl)

        btns_row = QHBoxLayout()
        btns_row.setSpacing(4)
        b_edit   = btn("Edit", min_w=60)
        b_rename = btn("✎", min_w=30)
        b_del    = btn("🗑", RED, min_w=30)
        b_edit.clicked.connect(lambda: self.edit_requested.emit(self.path))
        b_rename.clicked.connect(lambda: self.rename_requested.emit(self.path))
        b_del.clicked.connect(lambda: self.delete_requested.emit(self.path))
        btns_row.addWidget(b_edit)
        btns_row.addWidget(b_rename)
        btns_row.addWidget(b_del)
        v.addLayout(btns_row)

# ─────────────────────────────────────────────────────────────────────────────
# Editor canvas (with crop support via mouse clicks)
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

    def clear(self):
        self._pixmap_orig = None
        self.clear()
        self.setStyleSheet("background: #F7F8FB;")

    def mousePressEvent(self, event):
        if not self.crop_mode or self._pixmap_orig is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            px = self._pixmap_orig.width()
            py = self._pixmap_orig.height()
            rx = int(event.position().x() * self._img_size[0] / px)
            ry = int(event.position().y() * self._img_size[1] / py)
            self.crop_point_picked.emit(rx, ry)

# ─────────────────────────────────────────────────────────────────────────────
# Background thread for RSS feed loading
# ─────────────────────────────────────────────────────────────────────────────
class RssFetchThread(QThread):
    done = Signal(bytes)
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

        # State
        self.device_root: str | None  = None
        self.current_album_path: str | None = None
        self.current_album_name: str | None = None
        self.thumbnail_size = 140
        self.album_page = 0
        self.album_page_size = 24
        self.album_items_current: list = []
        self.rss_feeds: list  = []
        self.rss_selected_index: int | None = None
        self.current_rss_feed = None

        # Editor state
        self.editor_original: Image.Image | None = None
        self.editor_work: Image.Image | None     = None
        self.current_edit_path: str | None       = None
        self.crop_points: list = []

        # prefs widgets dict (key -> QWidget)
        self.prefs_widgets: dict = {}
        self.brightness_slider: QSlider | None    = None
        self.brightness_val_lbl: QLabel | None    = None

        self._rss_thread: RssFetchThread | None = None

        self._build_ui()
        self._apply_global_style()

        logging.info("Starting Philips PhotoFrame Manager Pro v%s (%s)", __version__, __build_date__)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_detect_tick)
        self._auto_timer.start(3000)
        QTimer.singleShot(1200, self._auto_detect_tick)

    # ─── Global stylesheet ────────────────────────────────────────────────────
    def _apply_global_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #F4F6FB; font-family: 'Segoe UI', Arial, sans-serif; }
            QTabWidget::pane { border: none; background: #F4F6FB; }
            QTabBar::tab {
                background: #E2E8F4; color: #333; padding: 8px 22px;
                border-radius: 6px 6px 0 0; margin-right: 2px; font-size: 13px;
            }
            QTabBar::tab:selected { background: #0B5ED7; color: white; font-weight: bold; }
            QScrollArea { border: none; }
            QLineEdit, QComboBox, QTextEdit {
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

    # ─── Build UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        sidebar = self._build_sidebar()
        sidebar.setFixedWidth(290)
        splitter.addWidget(sidebar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_albums_tab(),  "Albums")
        self.tabs.addTab(self._build_editor_tab(),  "Editor")
        self.tabs.addTab(self._build_prefs_tab(),   "Prefs")
        self.tabs.addTab(self._build_rss_tab(),     "RSS")
        self.tabs.addTab(self._build_tools_tab(),   "Tools")
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

    # ─── Sidebar ──────────────────────────────────────────────────────────────
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
        self.status_lbl = lbl("No device connected", color="#777")
        v.addWidget(self.status_lbl)
        self.path_lbl   = lbl("Path: -",    color="#555")
        self.storage_lbl = lbl("Storage: -", color="#555")
        self.album_info_lbl = lbl("Albums: -", color="#555")
        v.addWidget(self.path_lbl)
        v.addWidget(self.storage_lbl)
        v.addWidget(self.album_info_lbl)

        v.addSpacing(10)
        for label, slot in [
            ("Scan device",          self.scan_device),
            ("Select device manually", self.manual_select_device),
            ("Refresh",              self.refresh_all),
            ("Reload RSS",           self.load_rss_sources),
        ]:
            b = btn(label)
            b.clicked.connect(slot)
            v.addWidget(b)

        v.addSpacing(10)
        self.thumb_lbl = lbl(f"Thumbnail: {self.thumbnail_size}px")
        v.addWidget(self.thumb_lbl)
        self.thumb_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumb_slider.setMinimum(80)
        self.thumb_slider.setMaximum(240)
        self.thumb_slider.setValue(self.thumbnail_size)
        self.thumb_slider.valueChanged.connect(self._thumb_changed)
        v.addWidget(self.thumb_slider)

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

    # ─── Albums tab ───────────────────────────────────────────────────────────
    def _build_albums_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # Left panel
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

        scroll_albums = QScrollArea()
        scroll_albums.setWidget(self.album_list_widget)
        scroll_albums.setWidgetResizable(True)
        scroll_albums.setStyleSheet("background: transparent;")
        lv.addWidget(scroll_albums, 1)
        h.addWidget(left)

        # Right panel
        right = QFrame()
        right.setStyleSheet(f"background: {WHITE}; border-radius: 12px;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)

        topbar = QHBoxLayout()
        self.album_title_lbl = lbl("No album selected", bold=True, size=16)
        topbar.addWidget(self.album_title_lbl, 1)
        self.page_info_lbl = lbl("Page 0/0")
        topbar.addWidget(self.page_info_lbl)
        b_prev = btn("◀", min_w=36)
        b_next = btn("▶", min_w=36)
        b_prev.clicked.connect(self.prev_page)
        b_next.clicked.connect(self.next_page)
        topbar.addWidget(b_prev)
        topbar.addWidget(b_next)
        rv.addLayout(topbar)

        self.album_loading_lbl = lbl("", color="#888")
        rv.addWidget(self.album_loading_lbl)

        self.image_area_widget = QWidget()
        self.image_area_layout = QGridLayout(self.image_area_widget)
        self.image_area_layout.setSpacing(10)
        self.image_area_layout.setContentsMargins(0, 0, 0, 0)

        scroll_imgs = QScrollArea()
        scroll_imgs.setWidget(self.image_area_widget)
        scroll_imgs.setWidgetResizable(True)
        rv.addWidget(scroll_imgs, 1)

        h.addWidget(right, 1)
        return w

    # ─── Editor tab ───────────────────────────────────────────────────────────
    def _build_editor_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)

        # Top bar
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
            b = btn(label)
            b.clicked.connect(slot)
            th.addWidget(b)
        b_save = btn("Save", BLUE)
        b_save.clicked.connect(self.save_editor_image)
        th.addWidget(b_save)
        v.addWidget(top)

        # Canvas
        self.editor_canvas = EditorCanvas()
        self.editor_canvas.crop_point_picked.connect(self._on_crop_point)
        scroll_editor = QScrollArea()
        scroll_editor.setWidget(self.editor_canvas)
        scroll_editor.setWidgetResizable(False)
        scroll_editor.setStyleSheet("background: #F7F8FB;")
        v.addWidget(scroll_editor, 1)

        # Bottom bar
        bot = QFrame()
        bot.setStyleSheet(f"background: {WHITE}; border-radius: 8px;")
        bh = QHBoxLayout(bot)
        for label, slot in [
            ("Open image",       self.open_image_file),
            ("Rename image",     self.rename_current_image),
            ("Delete image",     self.delete_current_image),
            ("Save as copy",     self.save_as_copy),
        ]:
            b = btn(label)
            b.clicked.connect(slot)
            bh.addWidget(b)
        v.addWidget(bot)
        return w

    # ─── Prefs tab ────────────────────────────────────────────────────────────
    def _build_prefs_tab(self) -> QWidget:
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setStyleSheet(f"background: {WHITE};")
        form = QFormLayout(inner)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)

        FIELDS = [
            ("language_code",    "Language",                     "combo",  ["EN", "DE", "FR", "ES"]),
            ("brightness",       "Brightness (0-255)",           "slider", None),
            ("twentyfour",       "24h clock",                    "bool",   None),
            ("format",           "Format (0=Original,1=RadiantColor,2=Scale)", "line", None),
            ("timing",           "Slideshow interval (seconds)", "line",   None),
            ("sequence",         "Sequence (0=Ordered,1=Shuffle)","line",  None),
            ("effect",           "Transition effect (0-16)",     "line",   None),
            ("collage",          "Collage (0=Off,1=On)",         "line",   None),
            ("calendar",         "Calendar/Clock (0-3)",         "line",   None),
            ("open_at_startup",  "Open at startup (1/0)",        "line",   None),
            ("auto_on_off",      "Auto on/off (0-2)",            "line",   None),
            ("sensor_on",        "Sensor on (0-10)",             "line",   None),
            ("sensor_off",       "Sensor off (0-10)",            "line",   None),
            ("time_on",          "Time on (min from 0:00)",      "line",   None),
            ("time_off",         "Time off (min from 0:00)",     "line",   None),
            ("auto_tilt",        "Auto tilt",                    "bool",   None),
            ("background_color", "Background color (0-3)",       "line",   None),
            ("delete_enabled",   "Deleting enabled",             "bool",   None),
            ("beep",             "Beep",                         "bool",   None),
            ("demo_mode",        "Demo mode",                    "bool",   None),
        ]

        DEFAULTS = {
            "language_code": "EN", "brightness": "255", "twentyfour": "false",
            "format": "0", "timing": "300", "sequence": "1", "effect": "0",
            "collage": "0", "calendar": "0", "open_at_startup": "1",
            "auto_on_off": "2", "sensor_on": "10", "sensor_off": "4",
            "time_on": "420", "time_off": "1020", "auto_tilt": "true",
            "background_color": "3", "delete_enabled": "true",
            "beep": "false", "demo_mode": "false",
        }

        for key, label, kind, opts in FIELDS:
            if kind == "combo":
                w = QComboBox()
                w.addItems(opts)
                w.setCurrentText(DEFAULTS.get(key, opts[0]))
                self.prefs_widgets[key] = w
            elif kind == "bool":
                w = QComboBox()
                w.addItems(["true", "false"])
                w.setCurrentText(DEFAULTS.get(key, "false"))
                self.prefs_widgets[key] = w
            elif kind == "slider":
                container = QWidget()
                sh = QHBoxLayout(container)
                sh.setContentsMargins(0, 0, 0, 0)
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setMinimum(0); sl.setMaximum(255)
                sl.setValue(int(DEFAULTS.get(key, "255")))
                val_lbl = QLabel(DEFAULTS.get(key, "255"))
                val_lbl.setFixedWidth(36)
                sl.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
                sh.addWidget(sl)
                sh.addWidget(val_lbl)
                self.brightness_slider  = sl
                self.brightness_val_lbl = val_lbl
                self.prefs_widgets[key] = sl
                w = container
            else:
                w = QLineEdit(DEFAULTS.get(key, ""))
                self.prefs_widgets[key] = w
            form.addRow(label, w)

        btn_row = QHBoxLayout()
        b_load = btn("Load prefs")
        b_save = btn("Save prefs")
        b_load.clicked.connect(self.load_prefs)
        b_save.clicked.connect(self.save_prefs)
        btn_row.addWidget(b_load)
        btn_row.addWidget(b_save)
        form.addRow(btn_row)

        scroll.setWidget(inner)
        ov.addWidget(scroll)
        return outer

    def _prefs_get(self, key: str) -> str:
        w = self.prefs_widgets.get(key)
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QSlider):
            return str(w.value())
        if isinstance(w, QLineEdit):
            return w.text()
        return ""

    def _prefs_set(self, key: str, value: str):
        w = self.prefs_widgets.get(key)
        if isinstance(w, QComboBox):
            idx = w.findText(value)
            if idx >= 0:
                w.setCurrentIndex(idx)
        elif isinstance(w, QSlider):
            try:
                w.setValue(int(value))
                if self.brightness_val_lbl:
                    self.brightness_val_lbl.setText(value)
            except ValueError:
                pass
        elif isinstance(w, QLineEdit):
            w.setText(value)

    # ─── RSS tab ──────────────────────────────────────────────────────────────
    def _build_rss_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # Left
        left = QFrame()
        left.setFixedWidth(290)
        left.setStyleSheet(f"background: {PANEL_BG}; border-radius: 12px;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.addWidget(lbl("RSS feeds", bold=True, size=14))

        row_btns = QHBoxLayout()
        b_add  = btn("Add feed")
        b_save = btn("Save feeds")
        b_add.clicked.connect(self.add_rss_feed)
        b_save.clicked.connect(self.save_rss_feeds)
        row_btns.addWidget(b_add)
        row_btns.addWidget(b_save)
        lv.addLayout(row_btns)

        self.feed_list_widget  = QWidget()
        self.feed_list_layout  = QVBoxLayout(self.feed_list_widget)
        self.feed_list_layout.setSpacing(4)
        self.feed_list_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_list_layout.addStretch()
        scroll_feeds = QScrollArea()
        scroll_feeds.setWidget(self.feed_list_widget)
        scroll_feeds.setWidgetResizable(True)
        lv.addWidget(scroll_feeds, 1)

        reload_btn = btn("Reload feeds")
        reload_btn.clicked.connect(self.load_rss_sources)
        del_btn    = btn("Delete feed", RED)
        del_btn.clicked.connect(self.delete_selected_feed)
        lv.addWidget(reload_btn)
        lv.addWidget(del_btn)
        h.addWidget(left)

        # Right
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
        scroll_gallery = QScrollArea()
        scroll_gallery.setWidget(self.feed_gallery_widget)
        scroll_gallery.setWidgetResizable(True)
        rv.addWidget(scroll_gallery, 1)
        h.addWidget(right, 1)
        return w

    # ─── Tools tab ────────────────────────────────────────────────────────────
    def _build_tools_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(10)

        v.addWidget(lbl("Device and folder statistics", bold=True, size=18))

        for label, slot in [
            ("Reload everything",    self.refresh_all),
            ("Scan device",          self.scan_device),
            ("Import album/folder",  self.import_album_folder),
            ("Create backup (ZIP)",  self.create_backup),
            ("Restore backup",       self.restore_backup),
        ]:
            b = btn(label)
            b.clicked.connect(slot)
            v.addWidget(b)

        b_exit = btn("Exit", RED)
        b_exit.clicked.connect(self.close)
        v.addWidget(b_exit)

        self.stats_box = QTextEdit()
        self.stats_box.setReadOnly(True)
        self.stats_box.setStyleSheet(f"background: {WHITE}; border-radius: 8px; font-family: monospace;")
        v.addWidget(self.stats_box, 1)
        return w

    # ─── Auto detect ──────────────────────────────────────────────────────────
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
                if os.path.exists(os.path.join(mp, ".prefs")):           score += 3
                if os.path.exists(os.path.join(mp, ".config", "rss.cfg")): score += 2
                if os.path.isdir(os.path.join(mp, "ALBUM")):             score += 4
                if os.path.isdir(os.path.join(mp, "Album")):             score += 4
                if score > 0:
                    candidates.append((score, mp))
        except Exception:
            logging.exception("disk_partitions failed")
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        logging.info("Device candidates: %s", candidates)
        return candidates[0][1]

    # ─── Refresh ──────────────────────────────────────────────────────────────
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
            logging.exception("Could not create ALBUM folder")
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
                    img_count = len([x for x in os.listdir(p)
                                     if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                                     and os.path.isfile(os.path.join(p, x))])
                    lines.append(f"{d}: {img_count} images, {files} files, "
                                 f"{subdirs} subfolders, {human_size(size)}")
        except Exception:
            logging.exception("Stats failed")
        self.stats_box.setPlainText("\n".join(lines))

    # ─── Albums ───────────────────────────────────────────────────────────────
    def _clear_album_view(self):
        self._clear_layout(self.album_list_layout)
        self._clear_grid(self.image_area_layout)
        self.album_title_lbl.setText("No album selected")
        self.page_info_lbl.setText("Page 0/0")
        self.album_items_current = []
        self.current_album_path  = None
        self.current_album_name  = None
        self.album_page = 0

    def _clear_layout(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_grid(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh_album_list(self):
        self._clear_layout(self.album_list_layout)
        if not self.device_root:
            self.album_list_layout.addWidget(lbl("No device detected"))
            self.album_list_layout.addStretch()
            return
        root_dir = self._album_root()
        if not root_dir:
            self.album_list_layout.addWidget(lbl("No ALBUM/Album folder found"))
            self.album_list_layout.addStretch()
            return
        albums = []
        try:
            for name in sorted(os.listdir(root_dir)):
                full = os.path.join(root_dir, name)
                if os.path.isdir(full):
                    files, _, size = dir_stats(full)
                    img_count = len([x for x in os.listdir(full)
                                     if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                                     and os.path.isfile(os.path.join(full, x))])
                    albums.append((name, full, img_count, human_size(size)))
        except Exception:
            logging.exception("Failed to read album list")
        if not albums:
            self.album_list_layout.addWidget(lbl("No albums found"))
            self.album_list_layout.addStretch()
            return
        for name, full, img_count, size in albums:
            self._add_album_row(name, full, img_count, size)
        self.album_list_layout.addStretch()

    def _add_album_row(self, name: str, path: str, img_count: int, size: str):
        row = QFrame()
        row.setStyleSheet(f"background: {WHITE}; border-radius: 8px;")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        txt_btn = QPushButton(f"{name}\n{img_count} images · {size}")
        txt_btn.setStyleSheet(
            "background: transparent; color: #111; text-align: left; "
            "border: none; font-size: 12px; padding: 2px;"
        )
        txt_btn.clicked.connect(lambda _=False, p=path, n=name: self.open_album(p, n))
        h.addWidget(txt_btn, 1)
        b_ren = btn("✎", min_w=30)
        b_del = btn("🗑", RED, min_w=30)
        b_ren.clicked.connect(lambda _=False, p=path: self.rename_path(p))
        b_del.clicked.connect(lambda _=False, p=path: self.delete_path(p))
        h.addWidget(b_ren)
        h.addWidget(b_del)
        self.album_list_layout.insertWidget(self.album_list_layout.count() - 1, row)

    def open_album(self, path: str, name: str):
        self.current_album_path = path
        self.current_album_name = name
        self.album_page = 0
        logging.info("Album opened: %s", path)
        self.album_title_lbl.setText(name)
        self.album_loading_lbl.setText("Loading album…")
        QApplication.processEvents()
        self.refresh_album_view()
        self.album_loading_lbl.setText("")

    def refresh_album_view(self):
        self._clear_grid(self.image_area_layout)
        if not self.current_album_path or not os.path.isdir(self.current_album_path):
            return
        try:
            files = [f for f in sorted(os.listdir(self.current_album_path))
                     if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
            total  = len(files)
            self.album_items_current = files
            pages  = max(1, (total + self.album_page_size - 1) // self.album_page_size)
            if self.album_page >= pages:
                self.album_page = max(0, pages - 1)
            start  = self.album_page * self.album_page_size
            view   = files[start: start + self.album_page_size]
            self.page_info_lbl.setText(f"Page {self.album_page + 1}/{pages} · {total} images")
            if not view:
                self.image_area_layout.addWidget(lbl("No images found"), 0, 0)
                return
            cols = 4
            for idx, filename in enumerate(view):
                path = os.path.join(self.current_album_path, filename)
                card = ImageCard(path, filename, self.thumbnail_size)
                card.edit_requested.connect(self.open_image_path)
                card.rename_requested.connect(self.rename_path)
                card.delete_requested.connect(self.delete_path)
                self.image_area_layout.addWidget(card, idx // cols, idx % cols)
        except Exception:
            logging.exception("Album view failed")
            QMessageBox.critical(self, "Error", "Album could not be loaded.")

    def prev_page(self):
        if self.current_album_path and self.album_page > 0:
            self.album_page -= 1
            self.refresh_album_view()

    def next_page(self):
        if not self.current_album_path:
            return
        total = len(self.album_items_current)
        pages = max(1, (total + self.album_page_size - 1) // self.album_page_size)
        if self.album_page + 1 < pages:
            self.album_page += 1
            self.refresh_album_view()

    def _on_drop_albums(self, paths: list):
        if not self.device_root:
            QMessageBox.warning(self, "No device", "No PhotoFrame detected.")
            return
        dest_base = self._album_root()
        if not dest_base:
            QMessageBox.critical(self, "Error", "No ALBUM/Album folder found.")
            return
        copied = 0
        for src in paths:
            if os.path.isdir(src):
                dst = os.path.join(dest_base, os.path.basename(src))
                try:
                    logging.info("Copy: %s -> %s", src, dst)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    copied += 1
                except Exception:
                    logging.exception("Copy failed: %s", src)
        self.refresh_all()
        QMessageBox.information(self, "Done", f"Copied {copied} album folder(s).")

    # ─── Rename / Delete ──────────────────────────────────────────────────────
    def rename_path(self, path: str):
        base = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "Rename", f"New name for:\n{base}",
                                            text=base)
        if not ok or not new_name or new_name == base:
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        try:
            logging.info("Rename: %s -> %s", path, new_path)
            os.rename(path, new_path)
            self.refresh_all()
        except Exception:
            logging.exception("Rename failed")
            QMessageBox.critical(self, "Error", "Rename failed.")

    def delete_path(self, path: str):
        name = os.path.basename(path)
        reply = QMessageBox.question(self, "Delete", f"Really delete?\n{name}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            logging.info("Delete: %s", path)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            self.refresh_all()
        except Exception:
            logging.exception("Delete failed")
            QMessageBox.critical(self, "Error", "Delete failed.")

    # ─── Editor ───────────────────────────────────────────────────────────────
    def open_image_path(self, path: str):
        try:
            self.current_edit_path = path
            self.editor_original   = Image.open(path)
            self.editor_original   = ImageOps.exif_transpose(self.editor_original)
            self.editor_work       = self.editor_original.copy()
            self.crop_points       = []
            self.editor_canvas.crop_mode = False
            self.editor_title_lbl.setText(os.path.basename(path))
            self.tabs.setCurrentIndex(1)
            self._refresh_editor_preview()
            logging.info("Editor opened: %s", path)
        except Exception:
            logging.exception("Image open failed")
            QMessageBox.critical(self, "Image error", "Image could not be opened.")

    def open_image_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.gif *.webp)"
        )
        if path:
            self.open_image_path(path)

    def _refresh_editor_preview(self):
        if self.editor_work is None:
            self.editor_canvas.clear()
            return
        self.editor_canvas.set_image(self.editor_work)

    def rotate_left(self):
        if self.editor_work:
            self.editor_work = self.editor_work.rotate(90, expand=True)
            self._refresh_editor_preview()

    def rotate_right(self):
        if self.editor_work:
            self.editor_work = self.editor_work.rotate(-90, expand=True)
            self._refresh_editor_preview()

    def rotate_custom(self):
        if not self.editor_work:
            return
        angle, ok = QInputDialog.getDouble(self, "Rotate", "Angle in degrees:", 15.0, -360, 360, 1)
        if ok:
            self.editor_work = self.editor_work.rotate(-angle, expand=True)
            self._refresh_editor_preview()

    def toggle_crop_mode(self):
        self.editor_canvas.crop_mode = not self.editor_canvas.crop_mode
        self.crop_points = []
        msg = "Crop mode active: click two points." if self.editor_canvas.crop_mode else "Crop mode disabled."
        QMessageBox.information(self, "Crop", msg)

    def _on_crop_point(self, rx: int, ry: int):
        self.crop_points.append((rx, ry))
        if len(self.crop_points) == 2 and self.editor_work:
            (x1, y1), (x2, y2) = self.crop_points
            left   = min(x1, x2); upper = min(y1, y2)
            right  = max(x1, x2); lower = max(y1, y2)
            if right > left and lower > upper:
                self.editor_work = self.editor_work.crop((left, upper, right, lower))
                logging.info("Crop applied: %s", (left, upper, right, lower))
            self.editor_canvas.crop_mode = False
            self.crop_points = []
            self._refresh_editor_preview()

    def reset_editor(self):
        if self.editor_original:
            self.editor_work = self.editor_original.copy()
            self.editor_canvas.crop_mode = False
            self.crop_points = []
            self._refresh_editor_preview()

    def save_editor_image(self):
        if not self.editor_work or not self.current_edit_path:
            return
        try:
            self.editor_work.save(self.current_edit_path)
            logging.info("Image saved: %s", self.current_edit_path)
            self.refresh_all()
            QMessageBox.information(self, "Saved", "Image saved.")
        except Exception:
            logging.exception("Save failed")
            QMessageBox.critical(self, "Error", "Image could not be saved.")

    def save_as_copy(self):
        if not self.editor_work:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as copy", "",
            "JPEG (*.jpg);;PNG (*.png);;WEBP (*.webp)"
        )
        if path:
            try:
                self.editor_work.save(path)
                logging.info("Copy saved: %s", path)
                QMessageBox.information(self, "Saved", "Copy saved.")
            except Exception:
                logging.exception("Copy save failed")
                QMessageBox.critical(self, "Error", "Copy could not be saved.")

    def rename_current_image(self):
        if self.current_edit_path:
            self.rename_path(self.current_edit_path)

    def delete_current_image(self):
        if self.current_edit_path:
            self.delete_path(self.current_edit_path)

    # ─── Prefs load/save ──────────────────────────────────────────────────────
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
                for key in self.prefs_widgets:
                    node = setup.find(key)
                    if node is not None and node.text is not None:
                        self._prefs_set(key, node.text)
            logging.info(".prefs loaded")
        except Exception:
            logging.exception("Prefs load failed")

    def save_prefs(self):
        if not self.device_root:
            return
        prefs_file = os.path.join(self.device_root, ".prefs")
        if not os.path.exists(prefs_file):
            QMessageBox.warning(self, "Prefs", ".prefs not found on device.")
            return
        try:
            tree = ET.parse(prefs_file)
            root = tree.getroot()
            for setup in root.iter("setup"):
                for key in self.prefs_widgets:
                    node = setup.find(key)
                    if node is not None:
                        node.text = self._prefs_get(key)
            tree.write(prefs_file, encoding="UTF-8", xml_declaration=True)
            logging.info(".prefs saved")
            QMessageBox.information(self, "Saved", "Preferences saved.")
        except Exception:
            logging.exception("Prefs save failed")
            QMessageBox.critical(self, "Error", "Preferences could not be saved.")

    # ─── RSS ──────────────────────────────────────────────────────────────────
    def _rss_config_path(self) -> str | None:
        if not self.device_root:
            return None
        return os.path.join(self.device_root, ".config", "rss.cfg")

    def load_rss_sources(self):
        self.rss_feeds = []
        cfg = self._rss_config_path()
        if not cfg or not os.path.exists(cfg):
            logging.warning("rss.cfg not found")
            self._render_rss_feed_list()
            return
        try:
            tree = ET.parse(cfg)
            root = tree.getroot()
            for group in root.findall("group"):
                gname = group.attrib.get("name", "Default")
                for link in group.findall("link"):
                    self.rss_feeds.append({
                        "group": gname,
                        "name":  link.findtext("name", "Unnamed"),
                        "url":   link.findtext("url",  ""),
                    })
            logging.info("RSS feeds loaded: %s", len(self.rss_feeds))
        except ET.ParseError as e:
            logging.error("RSS parse error: %s", e)
            QMessageBox.warning(self, "RSS error", f"rss.cfg is not valid XML.\n\nError: {e}")
        except Exception:
            logging.exception("RSS load failed")
        self._render_rss_feed_list()

    def _render_rss_feed_list(self):
        self._clear_layout(self.feed_list_layout)
        if not self.rss_feeds:
            self.feed_list_layout.addWidget(lbl("No valid RSS feeds loaded"))
            self.feed_list_layout.addStretch()
            return
        for idx, feed in enumerate(self.rss_feeds):
            row = QFrame()
            row.setStyleSheet(f"background: {WHITE}; border-radius: 8px;")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 6, 8, 6)
            txt_btn = QPushButton(f"{feed['name']}\n{feed['url']}")
            txt_btn.setStyleSheet(
                "background: transparent; color: #111; text-align: left; "
                "border: none; font-size: 11px; padding: 2px;"
            )
            txt_btn.clicked.connect(lambda _=False, i=idx: self.open_rss_feed(i))
            h.addWidget(txt_btn, 1)
            b_ed  = btn("✎", min_w=30)
            b_del = btn("🗑", RED, min_w=30)
            b_ed.clicked.connect(lambda _=False, i=idx: self.edit_rss_feed(i))
            b_del.clicked.connect(lambda _=False, i=idx: self.remove_rss_feed(i))
            h.addWidget(b_ed)
            h.addWidget(b_del)
            self.feed_list_layout.insertWidget(self.feed_list_layout.count() - 1, row)
        self.feed_list_layout.addStretch()

    def add_rss_feed(self):
        name, ok = QInputDialog.getText(self, "RSS feed", "Name of the new feed:")
        if not ok or not name: return
        url, ok = QInputDialog.getText(self, "RSS feed", "URL of the new feed:")
        if not ok or not url:  return
        group, ok = QInputDialog.getText(self, "RSS feed", "Group name:", text="Default")
        group = group or "Default"
        self.rss_feeds.append({"group": group, "name": name, "url": url})
        logging.info("RSS added: %s -> %s", name, url)
        self._render_rss_feed_list()

    def edit_rss_feed(self, index: int):
        feed = self.rss_feeds[index]
        name, ok = QInputDialog.getText(self, "RSS feed", "Name:", text=feed["name"])
        if not ok or not name: return
        url, ok = QInputDialog.getText(self, "RSS feed", "URL:", text=feed["url"])
        if not ok or not url:  return
        group, ok = QInputDialog.getText(self, "RSS feed", "Group:", text=feed["group"])
        group = group or "Default"
        self.rss_feeds[index] = {"group": group, "name": name, "url": url}
        self._render_rss_feed_list()

    def remove_rss_feed(self, index: int):
        feed = self.rss_feeds[index]
        reply = QMessageBox.question(self, "Delete", f"Delete RSS feed?\n{feed['name']}",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            del self.rss_feeds[index]
            self._render_rss_feed_list()
            self._clear_rss_view()

    def delete_selected_feed(self):
        if self.rss_selected_index is not None:
            self.remove_rss_feed(self.rss_selected_index)
            self.rss_selected_index = None

    def save_rss_feeds(self):
        cfg = self._rss_config_path()
        if not cfg: return
        try:
            os.makedirs(os.path.dirname(cfg), exist_ok=True)
            root   = ET.Element("list")
            groups = {}
            for feed in self.rss_feeds:
                groups.setdefault(feed["group"], []).append(feed)
            for gname, feeds in groups.items():
                g = ET.SubElement(root, "group", {"name": gname})
                for feed in feeds:
                    link = ET.SubElement(g, "link")
                    ET.SubElement(link, "name").text = feed["name"]
                    ET.SubElement(link, "url").text  = feed["url"]
            ET.ElementTree(root).write(cfg, encoding="UTF-8", xml_declaration=True)
            logging.info("rss.cfg saved: %s", cfg)
            QMessageBox.information(self, "Saved", "rss.cfg saved.")
        except Exception:
            logging.exception("RSS save failed")
            QMessageBox.critical(self, "RSS error", "RSS could not be saved.")

    def open_rss_feed(self, index: int):
        if index < 0 or index >= len(self.rss_feeds):
            return
        self.rss_selected_index = index
        feed = self.rss_feeds[index]
        self.current_rss_feed = feed
        self.feed_title_lbl.setText(feed["name"])
        self.feed_meta_lbl.setText(feed["url"])
        self._render_feed_items(feed["url"])

    def _clear_rss_view(self):
        self._clear_grid(self.feed_gallery_layout)
        self.feed_title_lbl.setText("No feed selected")
        self.feed_meta_lbl.setText("")

    def _render_feed_items(self, url: str):
        self._clear_grid(self.feed_gallery_layout)
        self.feed_gallery_layout.addWidget(lbl("Loading feed…"), 0, 0)
        QApplication.processEvents()
        if self._rss_thread and self._rss_thread.isRunning():
            self._rss_thread.quit()
        self._rss_thread = RssFetchThread(url)
        self._rss_thread.done.connect(self._on_rss_data)
        self._rss_thread.error.connect(lambda msg: (
            self._clear_grid(self.feed_gallery_layout),
            self.feed_gallery_layout.addWidget(lbl(msg, color="#C0392B"), 0, 0)
        ))
        self._rss_thread.start()

    def _on_rss_data(self, data: bytes):
        self._clear_grid(self.feed_gallery_layout)
        try:
            root  = ET.fromstring(data)
            items = root.findall("./channel/item")
            if not items:
                self.feed_gallery_layout.addWidget(lbl("No RSS items found"), 0, 0)
                return
            for idx, item in enumerate(items):
                title     = item.findtext("title", f"Item {idx+1}")
                desc      = item.findtext("description", "")
                media_url = None
                mc = item.find(f"{NS_MEDIA}content")
                if mc is not None:
                    media_url = mc.attrib.get("url")
                if not media_url:
                    media_url = parse_image_from_description(desc)
                self._add_rss_card(title, desc, media_url, idx)
        except Exception:
            logging.exception("RSS feed parse failed")
            self.feed_gallery_layout.addWidget(
                lbl("RSS could not be parsed.", color="#C0392B"), 0, 0
            )

    def _add_rss_card(self, title: str, desc: str, media_url: str | None, idx: int):
        card = QFrame()
        card.setStyleSheet(f"background: {CARD_BG}; border-radius: 12px;")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)

        if media_url and re.search(r"\.(jpg|jpeg|png|bmp|gif|webp)(\?|$)", media_url, re.I):
            data = fetch_url_bytes(media_url)
            if data:
                try:
                    img = Image.open(io.BytesIO(data))
                    img = ImageOps.exif_transpose(img)
                    px  = pil_to_qpixmap(img, 200, 160)
                    img_lbl = QLabel()
                    img_lbl.setPixmap(px)
                    img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    v.addWidget(img_lbl)
                except Exception:
                    pass

        v.addWidget(lbl(title, bold=True, size=12))
        v.addWidget(lbl(strip_html(desc), size=11, color="#444"))
        cols = 3
        self.feed_gallery_layout.addWidget(card, idx // cols, idx % cols)

    # ─── Backup / restore ─────────────────────────────────────────────────────
    def create_backup(self):
        if not self.device_root:
            QMessageBox.warning(self, "No device", "No PhotoFrame detected.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save backup ZIP", "philips_backup.zip", "ZIP archive (*.zip)"
        )
        if not dest: return
        try:
            base = os.path.splitext(dest)[0]
            logging.info("Creating backup: root=%s dest=%s", self.device_root, dest)
            shutil.make_archive(base, "zip", self.device_root)
            QMessageBox.information(self, "Backup", f"Backup created:\n{dest}")
        except Exception:
            logging.exception("Backup failed")
            QMessageBox.critical(self, "Backup error", "Backup could not be created.")

    def restore_backup(self):
        if not self.device_root:
            QMessageBox.warning(self, "No device", "No PhotoFrame detected.")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Select backup ZIP", "", "ZIP archive (*.zip)"
        )
        if not src: return
        reply = QMessageBox.question(
            self, "Restore",
            "Restore backup?\nFiles with the same name will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            logging.info("Restore: %s -> %s", src, self.device_root)
            shutil.unpack_archive(src, self.device_root)
            self.refresh_all()
            QMessageBox.information(self, "Restored", "Backup has been restored.")
        except Exception:
            logging.exception("Restore failed")
            QMessageBox.critical(self, "Restore error", "Backup could not be restored.")

    def import_album_folder(self):
        if not self.device_root:
            QMessageBox.warning(self, "No device", "No PhotoFrame detected.")
            return
        src = QFileDialog.getExistingDirectory(self, "Select album folder to import")
        if not src: return
        dest_base = self._album_root()
        if not dest_base: return
        dst = os.path.join(dest_base, os.path.basename(src))
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            logging.info("Album imported: %s -> %s", src, dst)
            self.refresh_all()
        except Exception:
            logging.exception("Import failed")
            QMessageBox.critical(self, "Error", "Album could not be imported.")


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
