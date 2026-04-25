from __future__ import annotations

from pathlib import Path

try:
    from .constants import LEGACY_PLUGIN_NAME, PLUGIN_NAME
except ImportError:  # pragma: no cover - direct module loading
    from constants import LEGACY_PLUGIN_NAME, PLUGIN_NAME


def astrbot_data_path() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path())
    except Exception:
        return Path.cwd() / "data"


def plugin_data_dir() -> Path:
    return astrbot_data_path() / "plugin_data" / PLUGIN_NAME


def legacy_plugin_data_dir() -> Path:
    return astrbot_data_path() / "plugin_data" / LEGACY_PLUGIN_NAME


def plugin_index_path() -> Path:
    return plugin_data_dir() / "index.json"


def legacy_index_path() -> Path:
    return legacy_plugin_data_dir() / "index.json"


def plugin_state_path() -> Path:
    return plugin_data_dir() / "rm_monitor_state.json"


def legacy_state_path() -> Path:
    return legacy_plugin_data_dir() / "rm_monitor_state.json"
