from __future__ import annotations

from pathlib import Path

from astrbot.api.star import StarTools

from .constants import PLUGIN_NAME


def plugin_data_dir() -> Path:
    return Path(StarTools.get_data_dir(PLUGIN_NAME))


def plugin_index_path() -> Path:
    return plugin_data_dir() / "index.json"


def plugin_manual_dir() -> Path:
    return plugin_data_dir() / "manuals"


def plugin_download_dir() -> Path:
    return plugin_data_dir() / "manual_downloads"


def plugin_backup_dir() -> Path:
    return plugin_data_dir() / "manual_update_backups"


def plugin_state_path() -> Path:
    return plugin_data_dir() / "rm_monitor_state.json"


def plugin_forum_dir() -> Path:
    return plugin_data_dir() / "forum"


def plugin_forum_db_path() -> Path:
    return plugin_forum_dir() / "articles.db"


def plugin_forum_index_path() -> Path:
    return plugin_forum_dir() / "index.json"


def plugin_forum_import_dir() -> Path:
    return plugin_forum_dir() / "imports"


def plugin_forum_cookies_path() -> Path:
    return plugin_forum_dir() / "cookies.json"
