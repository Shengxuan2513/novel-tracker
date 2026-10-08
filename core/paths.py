"""Consistent data paths for source checkouts and installed packages."""
import os
from pathlib import Path


def data_dir():
    configured = os.environ.get("NOVEL_TRACKER_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(__file__).resolve().parent.parent
    if (root / "setup.py").is_file():
        return root
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "NovelTracker"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "novel-tracker"


def downloads_dir():
    return str(data_dir() / "downloads")
