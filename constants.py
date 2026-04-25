from __future__ import annotations

PLUGIN_NAME = "astrbot_plugin_robomaster_assistant"
LEGACY_PLUGIN_NAME = "astrbot_plugin_rm_manual_search"
DISPLAY_NAME = "RoboMaster赛事助手"
NO_RESULT_TEXT = "未在规则手册中找到可靠依据，请换个关键词试试。"
DEFAULT_MANUAL_DIR = "data/rm_manuals"

CONFIG_GROUPS = {
    "manual_dir": "manual_search",
    "allowed_sessions": "manual_search",
    "blocked_sessions": "manual_search",
    "max_results": "manual_search",
    "min_score": "manual_search",
    "enable_llm_explain": "manual_llm",
    "llm_candidate_pages": "manual_llm",
    "llm_candidate_chars": "manual_llm",
    "llm_select_all_evidence": "manual_llm",
    "llm_max_results": "manual_llm",
    "reply_mode": "reply_and_screenshot",
    "snippet_chars": "reply_and_screenshot",
    "lark_split_text_and_images": "reply_and_screenshot",
    "image_zoom": "reply_and_screenshot",
    "image_cache_seconds": "reply_and_screenshot",
    "crop_to_focus": "reply_and_screenshot",
    "crop_full_width": "reply_and_screenshot",
    "notify_sessions": "rm_notification",
    "enable_lark_card_notifications": "rm_notification",
    "announce_enabled": "announce_monitor",
    "announce_interval_seconds": "announce_monitor",
    "announce_last_id": "announce_monitor",
    "announce_monitored_pages": "announce_monitor",
    "match_monitor_enabled": "match_monitor",
    "match_scan_interval_seconds": "match_monitor",
    "dji_current_api_url": "match_monitor",
    "dji_schedule_api_url": "match_monitor",
    "match_zone_allowlist": "match_monitor",
    "external_webhook_enabled": "external_webhook",
    "external_webhook_urls": "external_webhook",
}
