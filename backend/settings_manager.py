"""
settings_manager.py - Persistent application settings manager.
Stores and retrieves user settings such as API keys securely.
"""

import os
import json
import time
import shutil
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
_settings_lock = threading.RLock()


def _read_settings_text() -> str:
    """
    The file's text. Windows lets a virus scanner, a backup tool or another process hold the file for a moment:
    that is waited out, and an unreadable file raises - it is not an empty one.
    """
    for attempt in range(8):
        try:
            return SETTINGS_FILE.read_text(encoding="utf-8")
        except (PermissionError, BlockingIOError) as e:
            if attempt == 7:
                raise OSError(f"The settings file cannot be read right now: {e}") from e
            time.sleep(0.05 * (attempt + 1))
    return ""


def load_settings() -> Dict[str, Any]:
    """
    Loads settings from config/settings.json, backing up corrupt files instead of silently losing them.
    Raises OSError while the file cannot be read, so that a save never replaces it with a nearly empty one.
    """
    with _settings_lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not SETTINGS_FILE.exists():
            return {}
        raw = _read_settings_text()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"Failed to read settings file (backing up corrupt copy): {e}")
            try:
                corrupt_backup = CONFIG_DIR / "settings.json.corrupt"
                shutil.copy2(SETTINGS_FILE, corrupt_backup)
            except Exception:
                pass
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """Atomically saves settings to config/settings.json using lock and atomic rename with Windows retry."""
    with _settings_lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONFIG_DIR / f"settings_{os.getpid()}_{threading.get_ident()}.tmp"
        try:
            tmp_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
            last_err = None
            for attempt in range(4):
                try:
                    os.replace(tmp_file, SETTINGS_FILE)
                    last_err = None
                    break
                except PermissionError as pe:
                    last_err = pe
                    time.sleep(0.05 * (attempt + 1))
            if last_err is not None:
                raise last_err
        except Exception as e:
            logger.error(f"Failed to write settings file: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink(missing_ok=True)
                except Exception:
                    pass
            raise


def get_setting(key: str, default: Optional[Any] = None) -> Optional[Any]:
    """Gets a specific setting from settings.json or environment."""
    env_val = os.environ.get(key.upper())
    if env_val:
        return env_val
    with _settings_lock:
        try:
            settings = load_settings()
        except OSError as e:
            logger.warning(f"{e}: using the default for '{key}'.")
            return default
        return settings.get(key, default)


def save_setting(key: str, value: Any) -> None:
    """Saves a single setting and updates os.environ if applicable."""
    with _settings_lock:
        settings = load_settings()
        settings[key] = value
        save_settings(settings)
        if isinstance(value, str):
            if value:
                os.environ[key.upper()] = value
            else:
                os.environ.pop(key.upper(), None)


def delete_setting(key: str) -> None:
    """Removes a setting from settings.json and os.environ."""
    with _settings_lock:
        settings = load_settings()
        if key in settings:
            del settings[key]
            save_settings(settings)
        os.environ.pop(key.upper(), None)


