# Philips PhotoFrame Manager Pro for 8FF3WMI

A cross-platform desktop utility for managing *Philips Digital PhotoFrames* on Linux and Windows for the Pphilips PhotoFrame 8FF3WMI. It provides an album browser, image editor, RSS feed manager, and full-device backup/restore, all wrapped in a modern **Qt (PySide6)** GUI.

## Features

- **Automatic device detection** (via disk partitions) and optional manual device selection
- **Album management**
  - Browse `ALBUM/Album` folders on the device
  - Drag & drop local folders to import as albums
  - Rename/delete albums and individual images
  - Adjustable **thumbnail size** and **images-per-page** (12/24/48/96)
  - "Album is loading…" indicator for large collections
- **Image editor**
  - Rotate left/right or by custom angle
  - Crop using two mouse clicks
  - Save back to device or export a copy
- **Preferences editor (`.prefs`)**
  - Brightness slider (0–255)
  - 24h clock, language, format (Original/RadiantColor/Scale to fit)
  - Slideshow timing, sequence (ordered/shuffle), transition effect, calendar mode
  - Auto on/off with **three modes**:
    - Off (disabled)
    - Time (schedule)
    - Light + time (light sensor + schedule)
  - Light sensor thresholds with validation:
    - `Light sensor ON (max)` and `Light sensor OFF (min)` sliders (0–10)
    - The app prevents saving when `ON (max)` is lower than or equal to `OFF (min)`
  - Time-based power schedule:
    - `Power on time` and `Power off time` (HH:MM)
    - These fields are automatically enabled/disabled based on the selected Auto on/off mode
  - Auto tilt/orientation, background color, delete protection, beep sound, demo mode
- **RSS feed manager**
  - Load existing `.config/rss.cfg`
  - Add/edit/delete RSS feeds and groups
  - Show image previews and descriptions
  - Robust handling of invalid/unreachable feeds
- **Backup & restore**
  - Create a ZIP backup of the complete device content
  - Restore from existing ZIP archive

## GUI overview

> **Screenshot 1 placeholder** – Main window showing sidebar, album browser and thumbnails.
>
> Replace this line with something like:
> `![Main window](docs/screenshot-main.png)`

> **Screenshot 2 placeholder** – Prefs tab showing Auto on/off, light sensor sliders and power on/off time fields.
>
> Replace this line with something like:
> `![Prefs tab](docs/screenshot-prefs.png)`

## Requirements

- Python 3.8+
- The script auto-installs these dependencies if missing:
  - `psutil`
  - `Pillow`
  - `PySide6`

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/basecore/philips-photoframe-manager-pro.git
cd philips-photoframe-manager-pro
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

On Windows, replace `python3` with `python` if needed.

## Running

```bash
python3 philips_manager_pro.py
```

On Linux you may need elevated permissions depending on how the device is mounted:

```bash
sudo python3 philips_manager_pro.py
```

## Usage notes

- The app tries to auto-detect the PhotoFrame by scanning mounted partitions for:
  - `.prefs`
  - `.config/rss.cfg`
  - `ALBUM` or `Album` directory
- If auto-detection fails, use **"Scan device"** or **"Select device manually"** and choose the mount point (e.g. `/media/USER/PHILIPS` or `E:\` on Windows).
- All operations (copy, delete, rename, backup, restore) are logged to the terminal for debugging.

## Debugging `.prefs` and `rss.cfg`

- Tools tab contains two helpers:
  - **"Debug: .prefs anzeigen"** – shows you the raw `.prefs` file from the device. If no device is connected, a synthetic in-memory `.prefs` snapshot is shown that matches the real file structure, so you can compare and debug.
  - **"Debug: rss.cfg anzeigen"** – shows the current RSS configuration file.

## Disclaimer

This is an independent open-source tool and is **not** affiliated with or endorsed by Philips. Use at your own risk. Always create a backup of your device content before making bulk changes.
