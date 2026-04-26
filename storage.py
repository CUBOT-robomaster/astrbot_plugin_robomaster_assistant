from __future__ import annotations

from pathlib import Path

from astrbot.api.star import StarTools

from .constants import LEGACY_PLUGIN_NAME, PLUGIN_NAME


def plugin_data_dir() -> Path:
    return Path(StarTools.get_data_dir(PLUGIN_NAME))


def legacy_plugin_data_dir() -> Path:
    return plugin_data_dir().parent / LEGACY_PLUGIN_NAME


def plugin_index_path() -> Path:
    return plugin_data_dir() / "index.json"


def legacy_index_path() -> Path:
    return legacy_plugin_data_dir() / "index.json"


def plugin_state_path() -> Path:
    return plugin_data_dir() / "rm_monitor_state.json"


def legacy_state_path() -> Path:
    return legacy_plugin_data_dir() / "rm_monitor_state.json"
