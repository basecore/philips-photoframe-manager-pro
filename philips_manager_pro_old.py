#!/usr/bin/env python3
__version__ = "2.4.0"
__build_date__ = "2026-06-13"

import os
import sys
import re
import io
import html
import shutil
import logging
import subprocess
import importlib.util
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED = [
    ("customtkinter", "customtkinter"),
    ("psutil", "psutil"),
    ("PIL", "Pillow"),
    ("tkinterdnd2", "tkinterdnd2-universal"),
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
NS_MEDIA = "{http://search.yahoo.com/mrss/}"

def is_debian_like():
    try:
        return os.path.exists("/etc/debian_version") or os.path.exists("/etc/linuxmint-info")
    except Exception:
        return False

def pip_install(package):
    cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", package]
    logging.info("pip install: %s", package)
    subprocess.check_call(cmd)

def apt_install(packages):
    if not shutil.which("apt-get"):
        logging.warning("apt-get not available, skipping apt install: %s", packages)
        return
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "apt-get", "install", "-y"] + packages
    else:
        cmd = ["apt-get", "install", "-y"] + packages
    logging.info("apt install: %s", " ".join(packages))
    subprocess.check_call(cmd)

def ensure_modules():
    for module_name, package_name in REQUIRED:
        if importlib.util.find_spec(module_name) is None:
            print(f"Installing missing module: {package_name}...")
            pip_install(package_name)

    try:
        from PIL import ImageTk  # noqa: F401
    except Exception:
        logging.warning("ImageTk missing, trying system package")
        if is_debian_like():
            try:
                apt_install(["python3-pil.imagetk"])
            except Exception:
                logging.exception("apt install python3-pil.imagetk failed")
        try:
            from PIL import ImageTk  # noqa: F401
        except Exception:
            pip_install("Pillow")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

ensure_modules()

import customtkinter as ctk
import psutil
from PIL import Image, ImageTk, ImageOps
from tkinter import messagebox, simpledialog, filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

def strip_html(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_image_from_description(desc):
    if not desc:
        return None
    m = re.search(r'src=["\']([^"\']+)["\']', desc)
    return m.group(1) if m else None

def fetch_url_bytes(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        logging.error("Failed to load URL: %s (%s)", url, e)
        return None

def human_size(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def dir_stats(path):
    files = 0
    dirs = 0
    size = 0
    for root, subdirs, filenames in os.walk(path):
        dirs += len(subdirs)
        for fn in filenames:
            files += 1
            fp = os.path.join(root, fn)
            try:
                size += os.path.getsize(fp)
            except OSError:
                pass
    return files, dirs, size


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title(f"Philips PhotoFrame Manager Pro v{__version__}")
        self.geometry("1440x900")
        self.minsize(1240, 800)

        self.device_root = None
        self.current_album_path = None
        self.current_album_name = None
        self.current_rss_feed = None
        self.thumbnail_size = 140
        self.album_page = 0
        self.album_page_size = 24
        self.album_items_current = []
        self._tk_refs = []
        self.rss_feeds = []
        self.rss_selected_index = None

        self.editor_original = None
        self.editor_work = None
        self.editor_photo = None
        self.editor_image_id = None
        self.current_edit_path = None
        self.crop_mode = False
        self.crop_points = []

        self.album_loading_label = None
        self.page_size_var = None

        self._build_ui()
        logging.info("Starting Philips PhotoFrame Manager Pro v%s (%s)", __version__, __build_date__)
        self.after(1200, self.auto_detect_loop)

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=0, fg_color="#FFFFFF", width=290)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(16, weight=1)

        ctk.CTkLabel(self.sidebar, text="PHILIPS", text_color="#0B5ED7",
                     font=ctk.CTkFont(size=34, weight="bold")).grid(row=0, column=0, padx=20, pady=(22, 2), sticky="w")
        ctk.CTkLabel(self.sidebar, text="PhotoFrame Manager Pro", text_color="#3C3C3C",
                     font=ctk.CTkFont(size=14)).grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")
        ctk.CTkLabel(self.sidebar, text=f"Version {__version__} · Build {__build_date__}",
                     text_color="#777777").grid(row=2, column=0, padx=20, pady=(0, 10), sticky="w")

        self.status = ctk.CTkLabel(self.sidebar, text="No device connected", text_color="#777777")
        self.status.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="w")

        self.path_label = ctk.CTkLabel(self.sidebar, text="Path: -", wraplength=250,
                                       justify="left", text_color="#555555")
        self.path_label.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="w")

        self.storage_label = ctk.CTkLabel(self.sidebar, text="Storage: -", wraplength=250,
                                          justify="left", text_color="#555555")
        self.storage_label.grid(row=5, column=0, padx=20, pady=(0, 10), sticky="w")

        self.album_info_label = ctk.CTkLabel(self.sidebar, text="Albums: -", wraplength=250,
                                             justify="left", text_color="#555555")
        self.album_info_label.grid(row=6, column=0, padx=20, pady=(0, 10), sticky="w")

        ctk.CTkButton(self.sidebar, text="Scan device", command=self.scan_device)\
            .grid(row=7, column=0, padx=20, pady=4, sticky="ew")
        ctk.CTkButton(self.sidebar, text="Select device manually", command=self.manual_select_device)\
            .grid(row=8, column=0, padx=20, pady=4, sticky="ew")
        ctk.CTkButton(self.sidebar, text="Refresh", command=self.refresh_all)\
            .grid(row=9, column=0, padx=20, pady=4, sticky="ew")
        ctk.CTkButton(self.sidebar, text="Reload RSS", command=self.load_rss_sources)\
            .grid(row=10, column=0, padx=20, pady=4, sticky="ew")

        ctk.CTkLabel(self.sidebar, text=f"Thumbnail: {self.thumbnail_size}px")\
            .grid(row=11, column=0, padx=20, pady=(8, 0), sticky="w")
        self.thumb_slider = ctk.CTkSlider(self.sidebar, from_=80, to=240, number_of_steps=16,
                                          command=self._thumb_changed)
        self.thumb_slider.set(self.thumbnail_size)
        self.thumb_slider.grid(row=12, column=0, padx=20, pady=(0, 6), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="Images per page:").grid(row=13, column=0, padx=20, pady=(4, 0), sticky="w")
        self.page_size_var = ctk.StringVar(value=str(self.album_page_size))
        self.page_size_menu = ctk.CTkOptionMenu(
            self.sidebar,
            variable=self.page_size_var,
            values=["12", "24", "48", "96"],
            command=self._page_size_changed
        )
        self.page_size_menu.grid(row=14, column=0, padx=20, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="All actions are logged to the terminal.",
                     wraplength=250, text_color="#666666").grid(row=15, column=0, padx=20, pady=(6, 0), sticky="w")

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=1, padx=18, pady=18, sticky="nsew")
        self.tabs.add("Albums")
        self.tabs.add("Editor")
        self.tabs.add("Prefs")
        self.tabs.add("RSS")
        self.tabs.add("Tools")

        self._build_albums_tab()
        self._build_editor_tab()
        self._build_prefs_tab()
        self._build_rss_tab()
        self._build_tools_tab()

    def _thumb_changed(self, value):
        self.thumbnail_size = int(float(value))
        if self.album_loading_label:
            self.album_loading_label.configure(text="Rebuilding thumbnails...")
        self.update_idletasks()
        self.refresh_album_view()
        if self.album_loading_label:
            self.album_loading_label.configure(text="")
        self.refresh_editor_preview()

    def _page_size_changed(self, value):
        try:
            self.album_page_size = int(value)
        except ValueError:
            self.album_page_size = 24
        self.album_page = 0
        self.refresh_album_view()

    # --- Albums tab ---

    def _build_albums_tab(self):
        tab = self.tabs.tab("Albums")
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(tab, fg_color="#F6F7FB", corner_radius=12)
        left.grid(row=0, column=0, padx=(0, 12), pady=0, sticky="ns")
        left.grid_rowconfigure(2, weight=1)

        right = ctk.CTkFrame(tab, fg_color="#FFFFFF", corner_radius=12)
        right.grid(row=0, column=1, padx=0, pady=0, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.drop_label = ctk.CTkLabel(left, text="Drop album folders here",
                                       fg_color="#E9EEF8", text_color="#0B5ED7",
                                       corner_radius=12, width=230, height=70)
        self.drop_label.grid(row=0, column=0, padx=14, pady=14, sticky="ew")
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self.on_drop_album)

        ctk.CTkLabel(left, text="Detected albums",
                     font=ctk.CTkFont(size=14, weight="bold"))\
                     .grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")
        self.album_list = ctk.CTkScrollableFrame(left, width=270, height=680, fg_color="#F6F7FB")
        self.album_list.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="nsew")

        topbar = ctk.CTkFrame(right, fg_color="#FFFFFF")
        topbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        topbar.grid_columnconfigure(0, weight=1)

        self.album_title = ctk.CTkLabel(topbar, text="No album selected",
                                        font=ctk.CTkFont(size=16, weight="bold"))
        self.album_title.grid(row=0, column=0, padx=6, pady=6, sticky="w")

        nav = ctk.CTkFrame(topbar, fg_color="transparent")
        nav.grid(row=0, column=1, padx=6, pady=6, sticky="e")
        self.page_info = ctk.CTkLabel(nav, text="Page 0/0")
        self.page_info.pack(side="left", padx=8)
        ctk.CTkButton(nav, text="◀", width=36, command=self.prev_page).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="▶", width=36, command=self.next_page).pack(side="left", padx=2)

        self.album_loading_label = ctk.CTkLabel(right, text="", text_color="#888888")
        self.album_loading_label.grid(row=1, column=0, padx=12, pady=(0, 2), sticky="w")

        self.image_area = ctk.CTkScrollableFrame(right, fg_color="#FFFFFF")
        self.image_area.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")

    # --- Editor tab ---

    def _build_editor_tab(self):
        tab = self.tabs.tab("Editor")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        info = ctk.CTkFrame(tab, fg_color="#FFFFFF")
        info.grid(row=0, column=0, padx=12, pady=12, sticky="ew")
        info.grid_columnconfigure(0, weight=1)

        self.editor_title = ctk.CTkLabel(info, text="No image loaded",
                                         font=ctk.CTkFont(size=16, weight="bold"))
        self.editor_title.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        btnbar = ctk.CTkFrame(info, fg_color="transparent")
        btnbar.grid(row=0, column=1, padx=8, pady=8, sticky="e")
        ctk.CTkButton(btnbar, text="Rotate 90° left", command=self.rotate_left).pack(side="left", padx=4)
        ctk.CTkButton(btnbar, text="Rotate 90° right", command=self.rotate_right).pack(side="left", padx=4)
        ctk.CTkButton(btnbar, text="Custom angle", command=self.rotate_custom).pack(side="left", padx=4)
        ctk.CTkButton(btnbar, text="Crop mode", command=self.toggle_crop_mode).pack(side="left", padx=4)
        ctk.CTkButton(btnbar, text="Reset", command=self.reset_editor).pack(side="left", padx=4)
        ctk.CTkButton(btnbar, text="Save", command=self.save_editor_image, fg_color="#0B5ED7")\
            .pack(side="left", padx=4)

        self.editor_canvas = ctk.CTkCanvas(tab, bg="#F7F8FB", highlightthickness=0)
        self.editor_canvas.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.editor_canvas.bind("<Button-1>", self.on_editor_click)

        bottom = ctk.CTkFrame(tab, fg_color="#FFFFFF")
        bottom.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        bottom.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(bottom, text="Open image", command=self.open_image_file)\
            .grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(bottom, text="Rename image", command=self.rename_current_image)\
            .grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(bottom, text="Delete image", command=self.delete_current_image)\
            .grid(row=0, column=2, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(bottom, text="Save as copy", command=self.save_as_copy)\
            .grid(row=0, column=3, padx=6, pady=6, sticky="ew")

    # --- Prefs tab ---

    def _build_prefs_tab(self):
        tab = self.tabs.tab("Prefs")
        tab.grid_columnconfigure(1, weight=1)

        self.prefs_vars = {
            "twentyfour": ctk.StringVar(value="false"),
            "language_code": ctk.StringVar(value="EN"),
            "brightness": ctk.StringVar(value="255"),
            "open_at_startup": ctk.StringVar(value="1"),
            "auto_on_off": ctk.StringVar(value="2"),
            "sensor_on": ctk.StringVar(value="10"),
            "sensor_off": ctk.StringVar(value="4"),
            "time_on": ctk.StringVar(value="420"),
            "time_off": ctk.StringVar(value="1020"),
            "auto_tilt": ctk.StringVar(value="true"),
            "sequence": ctk.StringVar(value="1"),
            "effect": ctk.StringVar(value="0"),
            "calendar": ctk.StringVar(value="0"),
            "timing": ctk.StringVar(value="300"),
            "collage": ctk.StringVar(value="0"),
            "background_color": ctk.StringVar(value="3"),
            "delete_enabled": ctk.StringVar(value="true"),
            "beep": ctk.StringVar(value="false"),
            "format": ctk.StringVar(value="0"),
            "demo_mode": ctk.StringVar(value="false"),
        }

        form = ctk.CTkScrollableFrame(tab, fg_color="#FFFFFF")
        form.pack(fill="both", expand=True, padx=12, pady=12)

        row = 0
        fields = [
            ("language_code", "Language (EN/DE/FR/ES)", "dropdown", ["EN", "DE", "FR", "ES"]),
            ("brightness", "Brightness (0-255)", "slider", None),
            ("twentyfour", "24h clock (true/false)", "bool", None),

            ("format", "Format (0=Original,1=RadiantColor,2=Scale to fit)", "entry", None),
            ("timing", "Slideshow interval (seconds)", "entry", None),
            ("sequence", "Sequence (0=Ordered,1=Shuffle)", "entry", None),
            ("effect", "Transition effect (0-16)", "entry", None),
            ("collage", "Collage (0=Off,1=On)", "entry", None),
            ("calendar", "Calendar/Clock (0=Week,1=Month,2=Clock,3=None)", "entry", None),

            ("open_at_startup", "Open at startup (1=On,0=Off)", "entry", None),
            ("auto_on_off", "Auto on/off (2=Light+Time,1=Time,0=Off)", "entry", None),
            ("sensor_on", "Sensor on (0-10, max)", "entry", None),
            ("sensor_off", "Sensor off (0-10,< on)", "entry", None),
            ("time_on", "Time on (minutes from 0:00)", "entry", None),
            ("time_off", "Time off (minutes from 0:00)", "entry", None),

            ("auto_tilt", "Auto tilt (true/false)", "bool", None),
            ("background_color", "Background color (0-3)", "entry", None),
            ("delete_enabled", "Deleting enabled (true/false)", "bool", None),
            ("beep", "Beep (true/false)", "bool", None),
            ("demo_mode", "Demo mode (true/false)", "bool", None),
        ]

        self.brightness_scale = None
        self.brightness_value_label = None

        used = set()
        for key, label, kind, values in fields:
            if key in used:
                continue
            used.add(key)
            ctk.CTkLabel(form, text=label).grid(row=row, column=0, padx=8, pady=6, sticky="w")
            if kind == "dropdown":
                w = ctk.CTkOptionMenu(form, variable=self.prefs_vars[key], values=values)
                w.grid(row=row, column=1, padx=8, pady=6, sticky="w")
            elif kind == "bool":
                w = ctk.CTkOptionMenu(form, variable=self.prefs_vars[key], values=["true", "false"])
                w.grid(row=row, column=1, padx=8, pady=6, sticky="w")
            elif kind == "slider" and key == "brightness":
                frame = ctk.CTkFrame(form, fg_color="transparent")
                frame.grid(row=row, column=1, padx=8, pady=6, sticky="w")
                self.brightness_scale = ctk.CTkSlider(
                    frame, from_=0, to=255, number_of_steps=255,
                    command=lambda v: self._brightness_slider_changed(v)
                )
                try:
                    self.brightness_scale.set(int(self.prefs_vars["brightness"].get()))
                except ValueError:
                    self.brightness_scale.set(255)
                    self.prefs_vars["brightness"].set("255")
                self.brightness_scale.pack(side="left", padx=(0, 10))
                self.brightness_value_label = ctk.CTkLabel(
                    frame, text=self.prefs_vars["brightness"].get()
                )
                self.brightness_value_label.pack(side="left")
                w = self.brightness_scale
            else:
                w = ctk.CTkEntry(form, textvariable=self.prefs_vars[key], width=220)
                w.grid(row=row, column=1, padx=8, pady=6, sticky="w")
            row += 1

        ctk.CTkButton(form, text="Load prefs", command=self.load_prefs)\
            .grid(row=row, column=0, padx=8, pady=14, sticky="ew")
        ctk.CTkButton(form, text="Save prefs", command=self.save_prefs)\
            .grid(row=row, column=1, padx=8, pady=14, sticky="ew")

    def _brightness_slider_changed(self, value):
        v = int(float(value))
        self.prefs_vars["brightness"].set(str(v))
        if self.brightness_value_label:
            self.brightness_value_label.configure(text=str(v))

    # --- RSS tab ---

    def _build_rss_tab(self):
        tab = self.tabs.tab("RSS")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=0)

        upper = ctk.CTkFrame(tab, fg_color="#FFFFFF")
        upper.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        upper.grid_columnconfigure(1, weight=1)
        upper.grid_rowconfigure(2, weight=1)

        left = ctk.CTkFrame(upper, fg_color="#F6F7FB")
        left.grid(row=0, column=0, rowspan=3, padx=(0, 12), pady=0, sticky="ns")
        left.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(left, text="RSS feeds", font=ctk.CTkFont(size=14, weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")
        ctk.CTkButton(left, text="Add feed", command=self.add_rss_feed)\
            .grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkButton(left, text="Save feeds", command=self.save_rss_feeds)\
            .grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        self.feed_list = ctk.CTkScrollableFrame(left, width=250, height=560, fg_color="#F6F7FB")
        self.feed_list.grid(row=3, column=0, padx=12, pady=12, sticky="nsew")

        self.feed_title = ctk.CTkLabel(upper, text="No feed selected",
                                       font=ctk.CTkFont(size=16, weight="bold"))
        self.feed_title.grid(row=0, column=1, padx=6, pady=(12, 4), sticky="w")
        self.feed_meta = ctk.CTkLabel(upper, text="", text_color="#666666")
        self.feed_meta.grid(row=1, column=1, padx=6, pady=(0, 8), sticky="w")

        self.feed_gallery = ctk.CTkScrollableFrame(upper, fg_color="#FFFFFF")
        self.feed_gallery.grid(row=2, column=1, padx=12, pady=(0, 12), sticky="nsew")

        lower = ctk.CTkFrame(tab, fg_color="#FFFFFF")
        lower.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        lower.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(lower, text="Reload feeds", command=self.load_rss_sources)\
            .grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(lower, text="Delete feed", command=self.delete_selected_feed)\
            .grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ctk.CTkButton(lower, text="Save rss.cfg", command=self.save_rss_feeds)\
            .grid(row=0, column=2, padx=6, pady=6, sticky="ew")

    # --- Tools tab ---

    def _build_tools_tab(self):
        tab = self.tabs.tab("Tools")
        tab.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(tab, text="Device and folder statistics",
                     font=ctk.CTkFont(size=18, weight="bold"))\
                     .grid(row=0, column=0, padx=16, pady=(16, 10), sticky="w")
        ctk.CTkButton(tab, text="Reload everything", command=self.refresh_all)\
            .grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        ctk.CTkButton(tab, text="Scan device", command=self.scan_device)\
            .grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        ctk.CTkButton(tab, text="Import album/folder", command=self.import_album_folder)\
            .grid(row=3, column=0, padx=16, pady=8, sticky="ew")

        ctk.CTkButton(tab, text="Create backup (ZIP)", command=self.create_backup)\
            .grid(row=4, column=0, padx=16, pady=8, sticky="ew")
        ctk.CTkButton(tab, text="Restore backup", command=self.restore_backup)\
            .grid(row=5, column=0, padx=16, pady=8, sticky="ew")

        ctk.CTkButton(tab, text="Exit", command=self.destroy,
                      fg_color="#C0392B")\
            .grid(row=6, column=0, padx=16, pady=8, sticky="ew")

        self.stats_box = ctk.CTkTextbox(tab, height=360, fg_color="#FFFFFF")
        self.stats_box.grid(row=7, column=0, padx=16, pady=16, sticky="nsew")

    # --- Auto-detect / device ---

    def auto_detect_loop(self):
        try:
            self.scan_device(silent=True)
        except Exception:
            logging.exception("Auto-detect error")
        self.after(3000, self.auto_detect_loop)

    def manual_select_device(self):
        path = filedialog.askdirectory(title="Select PhotoFrame device folder")
        if not path:
            return
        self.device_root = path
        self.status.configure(text="Device (manual) connected", text_color="#118C4F")
        self.path_label.configure(text=f"Path: {self.device_root}")
        self.refresh_all()

    def scan_device(self, silent=False):
        try:
            found = self.find_device_root()
            changed = found != self.device_root
            self.device_root = found
            if self.device_root:
                self.status.configure(text="Device connected", text_color="#118C4F")
                self.path_label.configure(text=f"Path: {self.device_root}")
                self.update_storage_info()
                self.update_album_info()
                if changed:
                    logging.info("Device detected: %s", self.device_root)
                    self.refresh_all()
            else:
                self.status.configure(text="No device connected", text_color="#8A8A8A")
                self.path_label.configure(text="Path: -")
                self.storage_label.configure(text="Storage: -")
                self.album_info_label.configure(text="Albums: -")
                if changed:
                    logging.info("Device disconnected")
                    self.clear_album_view()
            if not silent and not self.device_root:
                messagebox.showwarning("Device not found", "No Philips PhotoFrame mountpoint detected.")
        except Exception:
            logging.exception("Scan error")

    def find_device_root(self):
        candidates = []
        try:
            for part in psutil.disk_partitions(all=False):
                mp = part.mountpoint
                if not mp or not os.path.isdir(mp):
                    continue
                score = 0
                if os.path.exists(os.path.join(mp, ".prefs")):
                    score += 3
                if os.path.exists(os.path.join(mp, ".config", "rss.cfg")):
                    score += 2
                if os.path.isdir(os.path.join(mp, "ALBUM")):
                    score += 4
                if os.path.isdir(os.path.join(mp, "Album")):
                    score += 4
                if score > 0:
                    candidates.append((score, mp))
        except Exception:
            logging.exception("disk_partitions failed")
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        logging.info("Device candidates: %s", candidates)
        return candidates[0][1]

    # --- Refresh / stats ---

    def refresh_all(self):
        self.refresh_album_list()
        self.load_prefs()
        self.load_rss_sources()
        self.update_storage_info()
        self.update_album_info()
        self.refresh_album_view()
        self.refresh_stats()
        self.refresh_editor_preview()

    def update_storage_info(self):
        if not self.device_root:
            return
        try:
            usage = shutil.disk_usage(self.device_root)
            self.storage_label.configure(
                text=f"Storage: free {human_size(usage.free)} / total {human_size(usage.total)}"
            )
        except Exception:
            logging.exception("Storage info failed")

    def _album_root(self):
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

    def update_album_info(self):
        if not self.device_root:
            self.album_info_label.configure(text="Albums: -")
            return
        root = self._album_root()
        if not root:
            self.album_info_label.configure(text="Albums: -")
            return
        try:
            albums = [os.path.join(root, d) for d in sorted(os.listdir(root))
                      if os.path.isdir(os.path.join(root, d))]
            total_images = 0
            for p in albums:
                total_images += len([
                    x for x in os.listdir(p)
                    if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                    and os.path.isfile(os.path.join(p, x))
                ])
            self.album_info_label.configure(
                text=f"Albums: {len(albums)} folders · {total_images} images"
            )
        except Exception:
            logging.exception("Album info failed")

    def refresh_stats(self):
        if not self.device_root:
            return
        try:
            root = self._album_root()
            if not root:
                return
            lines = [f"Device: {self.device_root}",
                     f"Build: {__version__} / {__build_date__}",
                     ""]
            if os.path.isdir(root):
                for d in sorted(os.listdir(root)):
                    p = os.path.join(root, d)
                    if os.path.isdir(p):
                        files, subdirs, size = dir_stats(p)
                        img_count = len([
                            x for x in os.listdir(p)
                            if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                            and os.path.isfile(os.path.join(p, x))
                        ])
                        lines.append(f"{d}: {img_count} images, {files} files, "
                                     f"{subdirs} subfolders, {human_size(size)}")
            self.stats_box.delete("1.0", "end")
            self.stats_box.insert("1.0", "\n".join(lines))
        except Exception:
            logging.exception("Stats failed")

    # --- Albums ---

    def clear_album_view(self):
        for w in self.album_list.winfo_children():
            w.destroy()
        for w in self.image_area.winfo_children():
            w.destroy()
        self.album_title.configure(text="No album selected")
        self.page_info.configure(text="Page 0/0")
        self.album_items_current = []
        self.current_album_path = None
        self.current_album_name = None
        self.album_page = 0
        if self.album_loading_label:
            self.album_loading_label.configure(text="")

    def refresh_album_list(self):
        for w in self.album_list.winfo_children():
            w.destroy()
        if not self.device_root:
            ctk.CTkLabel(self.album_list, text="No device detected").pack(padx=10, pady=10)
            return
        root_dir = self._album_root()
        if not root_dir:
            ctk.CTkLabel(self.album_list, text="No ALBUM/Album folder found").pack(padx=10, pady=10)
            return
        albums = []
        try:
            for name in sorted(os.listdir(root_dir)):
                full = os.path.join(root_dir, name)
                if os.path.isdir(full):
                    files, _, size = dir_stats(full)
                    img_count = len([
                        x for x in os.listdir(full)
                        if os.path.splitext(x)[1].lower() in IMAGE_EXTS
                        and os.path.isfile(os.path.join(full, x))
                    ])
                    albums.append((name, full, img_count, human_size(size)))
        except Exception:
            logging.exception("Failed to read album list")
        if not albums:
            ctk.CTkLabel(self.album_list, text="No albums found").pack(padx=10, pady=10)
            return
        for name, full, img_count, size in albums:
            self._album_row(name, full, img_count, size)

    def _album_row(self, name, path, img_count, size):
        row = ctk.CTkFrame(self.album_list, fg_color="#FFFFFF")
        row.pack(fill="x", padx=4, pady=4)
        txt = f"{name}\n{img_count} images · {size}"
        ctk.CTkButton(row, text=txt, anchor="w", fg_color="transparent", text_color="#111111",
                      hover_color="#EAF1FF",
                      command=lambda p=path, n=name: self.open_album(p, n))\
            .pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)
        ctk.CTkButton(row, text="✎", width=34,
                      command=lambda p=path: self.rename_path(p),
                      fg_color="#0B5ED7").pack(side="left", padx=2)
        ctk.CTkButton(row, text="🗑", width=34,
                      command=lambda p=path: self.delete_path(p),
                      fg_color="#C0392B").pack(side="left", padx=(2, 8))

    def open_album(self, path, name):
        self.current_album_path = path
        self.current_album_name = name
        self.album_page = 0
        logging.info("Album opened: %s", path)
        self.album_title.configure(text=name)
        if self.album_loading_label:
            self.album_loading_label.configure(text="Loading album...")
        self.update_idletasks()
        self.refresh_album_view()
        if self.album_loading_label:
            self.album_loading_label.configure(text="")

    def refresh_album_view(self):
        for w in self.image_area.winfo_children():
            w.destroy()
        self._tk_refs = []
        if not self.current_album_path or not os.path.isdir(self.current_album_path):
            return
        try:
            files = [f for f in sorted(os.listdir(self.current_album_path))
                     if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
            total = len(files)
            self.album_items_current = files
            pages = max(1, (total + self.album_page_size - 1) // self.album_page_size)
            if self.album_page >= pages:
                self.album_page = max(0, pages - 1)
            start = self.album_page * self.album_page_size
            end = start + self.album_page_size
            view = files[start:end]
            self.page_info.configure(
                text=f"Page {self.album_page + 1}/{pages} · {total} images"
            )
            logging.info("Rendering album %s: total=%s page=%s view=%s",
                         self.current_album_path, total, self.album_page + 1, len(view))
            if not view:
                ctk.CTkLabel(self.image_area, text="No images found").pack(padx=16, pady=16)
                return
            grid = ctk.CTkFrame(self.image_area, fg_color="#FFFFFF")
            grid.pack(fill="both", expand=True)
            cols = 4
            for idx, file in enumerate(view):
                path = os.path.join(self.current_album_path, file)
                r = idx // cols
                c = idx % cols
                self._image_card(grid, path, file, r, c)
        except Exception:
            logging.exception("Album view failed")
            messagebox.showerror("Error", "Album could not be loaded. See terminal for details.")

    def _image_card(self, parent, path, filename, row, col):
        card = ctk.CTkFrame(parent, fg_color="#F9FAFC", corner_radius=12)
        card.grid(row=row, column=col, padx=10, pady=10, sticky="n")
        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)
            img.thumbnail((self.thumbnail_size, self.thumbnail_size))
            photo = ImageTk.PhotoImage(img)
            lbl = ctk.CTkLabel(card, image=photo, text="")
            lbl.pack(padx=10, pady=(10, 6))
            card._img_ref = photo
            self._tk_refs.append(photo)
        except Exception:
            logging.exception("Failed to load image: %s", path)
            ctk.CTkLabel(card, text="Image error", text_color="#AA0000").pack(padx=10, pady=20)

        ctk.CTkLabel(card, text=filename,
                     wraplength=self.thumbnail_size + 20,
                     justify="center").pack(padx=8, pady=(0, 8))
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(pady=(0, 10))
        ctk.CTkButton(btns, text="Edit", width=84,
                      command=lambda p=path: self.open_image_path(p))\
            .pack(side="left", padx=4)
        ctk.CTkButton(btns, text="✎", width=32,
                      command=lambda p=path: self.rename_path(p),
                      fg_color="#0B5ED7").pack(side="left", padx=4)
        ctk.CTkButton(btns, text="🗑", width=32,
                      command=lambda p=path: self.delete_path(p),
                      fg_color="#C0392B").pack(side="left", padx=4)

    def prev_page(self):
        if self.current_album_path and self.album_page > 0:
            self.album_page -= 1
            self.refresh_album_view()

    def next_page(self):
        if not self.current_album_path:
            return
        total = len(getattr(self, "album_items_current", []))
        pages = max(1, (total + self.album_page_size - 1) // self.album_page_size)
        if self.album_page + 1 < pages:
            self.album_page += 1
            self.refresh_album_view()

    # --- Rename / delete ---

    def rename_path(self, path):
        base = os.path.basename(path)
        new_name = simpledialog.askstring("Rename",
                                          f"New name for:\n{base}",
                                          initialvalue=base)
        if not new_name or new_name == base:
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        try:
            logging.info("Rename: %s -> %s", path, new_path)
            os.rename(path, new_path)
            self.refresh_all()
        except Exception:
            logging.exception("Rename failed")
            messagebox.showerror("Error", "Rename failed. See terminal for details.")

    def delete_path(self, path):
        name = os.path.basename(path)
        if not messagebox.askyesno("Delete", f"Really delete?\n{name}"):
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
            messagebox.showerror("Error", "Delete failed. See terminal for details.")

    # --- Drag & drop ---

    def on_drop_album(self, event):
        if not self.device_root:
            messagebox.showwarning("No device", "No PhotoFrame detected.")
            return
        dest_base = self._album_root()
        if not dest_base:
            messagebox.showerror("Error", "No ALBUM/Album folder found.")
            return
        paths = self._parse_dnd_paths(event.data)
        copied = 0
        for src in paths:
            src = src.strip("{}")
            if os.path.isdir(src):
                dst = os.path.join(dest_base, os.path.basename(src))
                try:
                    logging.info("Copy: %s -> %s", src, dst)
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    copied += 1
                except Exception:
                    logging.exception("Copy failed: %s", src)
        self.refresh_all()
        messagebox.showinfo("Done", f"Copied {copied} album folder(s).")

    def _parse_dnd_paths(self, data):
        return re.findall(r"\{.*?\}|[^\s]+", data)

    # --- Prefs load/save ---

    def load_prefs(self):
        if not self.device_root:
            return
        prefs = os.path.join(self.device_root, ".prefs")
        if not os.path.exists(prefs):
            logging.warning(".prefs not found: %s", prefs)
            return
        try:
            tree = ET.parse(prefs)
            root = tree.getroot()
            for setup in root.iter("setup"):
                for key, var in self.prefs_vars.items():
                    node = setup.find(key)
                    if node is not None and node.text is not None:
                        var.set(node.text)
            if self.brightness_scale:
                try:
                    self.brightness_scale.set(int(self.prefs_vars["brightness"].get()))
                except ValueError:
                    self.brightness_scale.set(255)
                    self.prefs_vars["brightness"].set("255")
            logging.info(".prefs loaded")
        except Exception:
            logging.exception("Prefs load failed")

    def save_prefs(self):
        if not self.device_root:
            return
        prefs = os.path.join(self.device_root, ".prefs")
        if not os.path.exists(prefs):
            messagebox.showwarning("Prefs", ".prefs not found on device.")
            return
        try:
            tree = ET.parse(prefs)
            root = tree.getroot()
            for setup in root.iter("setup"):
                for key, var in self.prefs_vars.items():
                    node = setup.find(key)
                    if node is not None:
                        node.text = var.get()
            tree.write(prefs, encoding="UTF-8", xml_declaration=True)
            logging.info(".prefs saved")
            messagebox.showinfo("Saved", "Preferences saved.")
        except Exception:
            logging.exception("Prefs save failed")
            messagebox.showerror("Error", "Preferences could not be saved. See terminal for details.")

    # --- RSS ---

    def rss_config_path(self):
        if not self.device_root:
            return None
        return os.path.join(self.device_root, ".config", "rss.cfg")

    def load_rss_sources(self):
        self.rss_feeds = []
        cfg = self.rss_config_path()
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
                    name = link.findtext("name", default="Unnamed")
                    url = link.findtext("url", default="")
                    self.rss_feeds.append({"group": gname, "name": name, "url": url})
            logging.info("RSS feeds loaded: %s", len(self.rss_feeds))
        except ET.ParseError as e:
            logging.error("RSS load failed: %s in file %s", e, cfg)
            messagebox.showwarning("RSS error",
                                   f"rss.cfg is not valid XML.\nPlease fix the file.\n\nError: {e}")
            self.rss_feeds = []
        except Exception:
            logging.exception("RSS load failed")
        self._render_rss_feed_list()

    def _render_rss_feed_list(self):
        for w in self.feed_list.winfo_children():
            w.destroy()
        if not self.rss_feeds:
            ctk.CTkLabel(self.feed_list, text="No valid RSS feeds loaded")\
                .pack(padx=10, pady=10)
            return
        for idx, feed in enumerate(self.rss_feeds):
            row = ctk.CTkFrame(self.feed_list, fg_color="#FFFFFF")
            row.pack(fill="x", padx=4, pady=4)
            txt = f"{feed['name']}\n{feed['url']}"
            ctk.CTkButton(row, text=txt, anchor="w", fg_color="transparent",
                          text_color="#111111", hover_color="#EAF1FF",
                          command=lambda i=idx: self.open_rss_feed(i))\
                .pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)
            ctk.CTkButton(row, text="✎", width=34,
                          command=lambda i=idx: self.edit_rss_feed(i),
                          fg_color="#0B5ED7").pack(side="left", padx=2)
            ctk.CTkButton(row, text="🗑", width=34,
                          command=lambda i=idx: self.remove_rss_feed(i),
                          fg_color="#C0392B").pack(side="left", padx=(2, 8))

    def add_rss_feed(self):
        name = simpledialog.askstring("RSS feed", "Name of the new feed:")
        if not name:
            return
        url = simpledialog.askstring("RSS feed", "URL of the new feed:")
        if not url:
            return
        group = simpledialog.askstring("RSS feed", "Group name:", initialvalue="Default") or "Default"
        self.rss_feeds.append({"group": group, "name": name, "url": url})
        logging.info("RSS added: %s -> %s", name, url)
        self._render_rss_feed_list()

    def edit_rss_feed(self, index):
        feed = self.rss_feeds[index]
        name = simpledialog.askstring("RSS feed", "Name:", initialvalue=feed["name"])
        if not name:
            return
        url = simpledialog.askstring("RSS feed", "URL:", initialvalue=feed["url"])
        if not url:
            return
        group = simpledialog.askstring("RSS feed", "Group name:", initialvalue=feed["group"]) or "Default"
        self.rss_feeds[index] = {"group": group, "name": name, "url": url}
        logging.info("RSS edited: %s", name)
        self._render_rss_feed_list()

    def remove_rss_feed(self, index):
        feed = self.rss_feeds[index]
        if messagebox.askyesno("Delete", f"Delete RSS feed?\n{feed['name']}"):
            logging.info("RSS deleted: %s", feed["name"])
            del self.rss_feeds[index]
            self._render_rss_feed_list()
            self.clear_rss_view()

    def delete_selected_feed(self):
        if self.rss_selected_index is None:
            return
        self.remove_rss_feed(self.rss_selected_index)
        self.rss_selected_index = None

    def save_rss_feeds(self):
        cfg = self.rss_config_path()
        if not cfg:
            return
        try:
            os.makedirs(os.path.dirname(cfg), exist_ok=True)
            root = ET.Element("list")
            groups = {}
            for feed in self.rss_feeds:
                groups.setdefault(feed["group"], []).append(feed)
            for group_name, feeds in groups.items():
                g = ET.SubElement(root, "group", {"name": group_name})
                for feed in feeds:
                    link = ET.SubElement(g, "link")
                    ET.SubElement(link, "name").text = feed["name"]
                    ET.SubElement(link, "url").text = feed["url"]
            ET.ElementTree(root).write(cfg, encoding="UTF-8", xml_declaration=True)
            logging.info("rss.cfg saved: %s", cfg)
            messagebox.showinfo("Saved", "rss.cfg saved.")
        except Exception:
            logging.exception("RSS save failed")
            messagebox.showerror("RSS error", "RSS could not be saved. See terminal for details.")

    def open_rss_feed(self, index):
        if index < 0 or index >= len(self.rss_feeds):
            return
        self.rss_selected_index = index
        feed = self.rss_feeds[index]
        self.current_rss_feed = feed
        self.feed_title.configure(text=feed["name"])
        self.feed_meta.configure(text=feed["url"])
        self._render_feed_items(feed["url"])

    def clear_rss_view(self):
        for w in self.feed_gallery.winfo_children():
            w.destroy()
        self.feed_title.configure(text="No feed selected")
        self.feed_meta.configure(text="")

    def _render_feed_items(self, url):
        for w in self.feed_gallery.winfo_children():
            w.destroy()
        self._tk_refs = []
        data = fetch_url_bytes(url)
        if not data:
            ctk.CTkLabel(self.feed_gallery,
                         text="Feed could not be loaded (URL error).")\
                .pack(padx=16, pady=16)
            return
        try:
            root = ET.fromstring(data)
            items = root.findall("./channel/item")
            logging.info("RSS items found: %s", len(items))
            if not items:
                ctk.CTkLabel(self.feed_gallery, text="No RSS items found")\
                    .pack(padx=16, pady=16)
                return
            grid = ctk.CTkFrame(self.feed_gallery, fg_color="#FFFFFF")
            grid.pack(fill="both", expand=True)
            for idx, item in enumerate(items):
                title = item.findtext("title", default=f"Item {idx+1}")
                desc = item.findtext("description", default="")
                media_url = None
                mc = item.find(f"{NS_MEDIA}content")
                if mc is not None:
                    media_url = mc.attrib.get("url")
                if not media_url:
                    media_url = parse_image_from_description(desc)
                self._rss_card(grid, title, desc, media_url, idx)
        except Exception:
            logging.exception("RSS feed parse failed")
            ctk.CTkLabel(self.feed_gallery,
                         text="RSS could not be parsed. See terminal for details.")\
                .pack(padx=16, pady=16)

    def _rss_card(self, parent, title, desc, media_url, idx):
        card = ctk.CTkFrame(parent, fg_color="#F9FAFC", corner_radius=12)
        card.grid(row=idx // 3, column=idx % 3, padx=10, pady=10, sticky="n")

        shown = False
        if media_url and re.search(r"\.(jpg|jpeg|png|bmp|gif|webp)(\?|$)", media_url, re.I):
            data = fetch_url_bytes(media_url)
            if data:
                try:
                    img = Image.open(io.BytesIO(data))
                    img = ImageOps.exif_transpose(img)
                    img.thumbnail((self.thumbnail_size, self.thumbnail_size))
                    photo = ImageTk.PhotoImage(img)
                    lbl = ctk.CTkLabel(card, image=photo, text="")
                    lbl.pack(padx=10, pady=(10, 6))
                    card._img_ref = photo
                    self._tk_refs.append(photo)
                    shown = True
                except Exception:
                    logging.exception("RSS image load failed: %s", media_url)

        if not shown:
            ctk.CTkLabel(card, text="No preview image", text_color="#AA0000")\
                .pack(padx=10, pady=(16, 8))

        ctk.CTkLabel(card, text=title, wraplength=250,
                     justify="center", font=ctk.CTkFont(size=12, weight="bold"))\
            .pack(padx=8, pady=(0, 6))
        ctk.CTkLabel(card, text=strip_html(desc), wraplength=250,
                     justify="left", text_color="#444444")\
            .pack(padx=10, pady=(0, 10))

    # --- Editor ---

    def open_image_path(self, path):
        try:
            self.current_edit_path = path
            self.editor_original = Image.open(path)
            self.editor_original = ImageOps.exif_transpose(self.editor_original)
            self.editor_work = self.editor_original.copy()
            self.editor_title.configure(text=os.path.basename(path))
            self.tabs.set("Editor")
            self.refresh_editor_preview()
            logging.info("Editor opened: %s", path)
        except Exception:
            logging.exception("Image open failed")
            messagebox.showerror("Image error",
                                 "Image could not be opened. See terminal for details.")

    def open_image_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.gif *.webp")]
        )
        if path:
            self.open_image_path(path)

    def refresh_editor_preview(self):
        if self.editor_work is None:
            self.editor_canvas.delete("all")
            return
        self.editor_canvas.delete("all")
        preview = self.editor_work.copy()
        preview.thumbnail((1100, 700))
        self.editor_photo = ImageTk.PhotoImage(preview)
        self.editor_image_id = self.editor_canvas.create_image(
            10, 10, anchor="nw", image=self.editor_photo
        )
        self.editor_canvas.config(scrollregion=self.editor_canvas.bbox("all"))

    def rotate_left(self):
        if self.editor_work is None:
            return
        self.editor_work = self.editor_work.rotate(90, expand=True)
        self.refresh_editor_preview()

    def rotate_right(self):
        if self.editor_work is None:
            return
        self.editor_work = self.editor_work.rotate(-90, expand=True)
        self.refresh_editor_preview()

    def rotate_custom(self):
        if self.editor_work is None:
            return
        angle = simpledialog.askfloat("Rotate", "Angle in degrees:", initialvalue=15.0)
        if angle is not None:
            self.editor_work = self.editor_work.rotate(-angle, expand=True)
            self.refresh_editor_preview()

    def toggle_crop_mode(self):
        self.crop_mode = not self.crop_mode
        self.crop_points = []
        messagebox.showinfo("Crop",
                            "Crop mode active: click two points."
                            if self.crop_mode else "Crop mode disabled.")

    def on_editor_click(self, event):
        if not self.crop_mode or self.editor_work is None or self.editor_image_id is None:
            return
        bbox = self.editor_canvas.bbox(self.editor_image_id)
        if not bbox:
            return
        x0, y0, x1, y1 = bbox
        img = self.editor_work.copy()
        img.thumbnail((1100, 700))
        w, h = img.size
        if event.x < x0 or event.y < y0 or event.x > x0 + w or event.y > y0 + h:
            return
        rx = int((event.x - x0) * self.editor_work.width / w)
        ry = int((event.y - y0) * self.editor_work.height / h)
        self.crop_points.append((rx, ry))
        if len(self.crop_points) == 2:
            (x1p, y1p), (x2p, y2p) = self.crop_points
            left = min(x1p, x2p)
            upper = min(y1p, y2p)
            right = max(x1p, x2p)
            lower = max(y1p, y2p)
            if right > left and lower > upper:
                self.editor_work = self.editor_work.crop((left, upper, right, lower))
                logging.info("Crop applied: %s", (left, upper, right, lower))
            self.crop_mode = False
            self.crop_points = []
            self.refresh_editor_preview()

    def reset_editor(self):
        if self.editor_original is None:
            return
        self.editor_work = self.editor_original.copy()
        self.crop_mode = False
        self.crop_points = []
        self.refresh_editor_preview()

    def save_editor_image(self):
        if self.editor_work is None or not self.current_edit_path:
            return
        try:
            self.editor_work.save(self.current_edit_path)
            logging.info("Image saved: %s", self.current_edit_path)
            self.refresh_all()
            messagebox.showinfo("Saved", "Image saved.")
        except Exception:
            logging.exception("Save failed")
            messagebox.showerror("Error",
                                 "Image could not be saved. See terminal for details.")

    def save_as_copy(self):
        if self.editor_work is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("WEBP", "*.webp")]
        )
        if path:
            try:
                self.editor_work.save(path)
                logging.info("Copy saved: %s", path)
                messagebox.showinfo("Saved", "Copy saved.")
            except Exception:
                logging.exception("Copy save failed")
                messagebox.showerror("Error", "Copy could not be saved.")

    def rename_current_image(self):
        if self.current_edit_path:
            self.rename_path(self.current_edit_path)

    def delete_current_image(self):
        if self.current_edit_path:
            self.delete_path(self.current_edit_path)

    # --- Backup / restore ---

    def create_backup(self):
        if not self.device_root:
            messagebox.showwarning("No device", "No PhotoFrame detected.")
            return
        dest = filedialog.asksaveasfilename(
            title="Save backup ZIP",
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip")],
            initialfile="philips_backup.zip",
        )
        if not dest:
            return
        try:
            base_name = os.path.splitext(dest)[0]
            logging.info("Creating backup: root=%s dest=%s", self.device_root, dest)
            shutil.make_archive(base_name, "zip", self.device_root)
            messagebox.showinfo("Backup", f"Backup created:\n{dest}")
        except Exception:
            logging.exception("Backup failed")
            messagebox.showerror("Backup error",
                                 "Backup could not be created. See terminal for details.")

    def restore_backup(self):
        if not self.device_root:
            messagebox.showwarning("No device", "No PhotoFrame detected.")
            return
        src = filedialog.askopenfilename(
            title="Select backup ZIP",
            filetypes=[("ZIP archive", "*.zip")],
        )
        if not src:
            return
        if not messagebox.askyesno("Restore",
                                   "Restore backup?\n"
                                   "Files with the same name will be overwritten."):
            return
        try:
            logging.info("Restore: %s -> %s", src, self.device_root)
            shutil.unpack_archive(src, self.device_root)
            self.refresh_all()
            messagebox.showinfo("Restored", "Backup has been restored.")
        except Exception:
            logging.exception("Restore failed")
            messagebox.showerror("Restore error",
                                 "Backup could not be restored. See terminal for details.")

    # --- Album import ---

    def import_album_folder(self):
        if not self.device_root:
            messagebox.showwarning("No device", "No PhotoFrame detected.")
            return
        src = filedialog.askdirectory(title="Select album folder to import")
        if not src:
            return
        dest_base = self._album_root()
        if not dest_base:
            return
        dst = os.path.join(dest_base, os.path.basename(src))
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            logging.info("Album imported: %s -> %s", src, dst)
            self.refresh_all()
        except Exception:
            logging.exception("Import failed")
            messagebox.showerror("Error", "Album could not be imported.")


if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception:
        logging.exception("Unexpected error")
        raise
