from __future__ import annotations

PLUGIN_NAME = "astrbot_plugin_robomaster_assistant"
DISPLAY_NAME = "RoboMaster赛事助手"
NO_RESULT_TEXT = "未在规则手册中找到可靠依据，请换个关键词试试。"
DEFAULT_MANUAL_DIR = "data/rm_manuals"

CONFIG_GROUPS = {
    "manual_dir": ("rule_manual", "manual_search"),
    "allowed_sessions": ("rule_manual", "manual_search"),
    "blocked_sessions": ("rule_manual", "manual_search"),
    "max_results": ("rule_manual", "manual_search"),
    "min_score": ("rule_manual", "manual_search"),
    "download_max_mb": ("rule_manual", "manual_download"),
    "download_timeout_seconds": ("rule_manual", "manual_download"),
    "download_free_space_buffer_mb": ("rule_manual", "manual_download"),
    "enable_llm_explain": ("rule_manual", "manual_llm"),
    "llm_candidate_pages": ("rule_manual", "manual_llm"),
    "llm_candidate_chars": ("rule_manual", "manual_llm"),
    "llm_select_all_evidence": ("rule_manual", "manual_llm"),
    "llm_max_results": ("rule_manual", "manual_llm"),
    "reply_mode": ("rule_manual", "reply_and_screenshot"),
    "snippet_chars": ("rule_manual", "reply_and_screenshot"),
    "lark_split_text_and_images": ("rule_manual", "reply_and_screenshot"),
    "image_zoom": ("rule_manual", "reply_and_screenshot"),
    "image_cache_seconds": ("rule_manual", "reply_and_screenshot"),
    "crop_to_focus": ("rule_manual", "reply_and_screenshot"),
    "crop_full_width": ("rule_manual", "reply_and_screenshot"),
    "notify_sessions": ("announcement_notification", "rm_notification"),
    "enable_lark_card_notifications": ("announcement_notification", "rm_notification"),
    "announce_enabled": ("announcement_notification", "announce_monitor"),
    "announce_interval_seconds": ("announcement_notification", "announce_monitor"),
    "announce_last_id": ("announcement_notification", "announce_monitor"),
    "announce_monitored_pages": ("announcement_notification", "announce_monitor"),
    "match_monitor_enabled": ("match_notification", "match_monitor"),
    "match_scan_interval_seconds": ("match_notification", "match_monitor"),
    "dji_current_api_url": ("match_notification", "match_monitor"),
    "dji_schedule_api_url": ("match_notification", "match_monitor"),
    "match_zone_allowlist": ("match_notification", "match_monitor"),
    "external_webhook_enabled": ("match_notification", "external_webhook"),
    "external_webhook_urls": ("match_notification", "external_webhook"),
}
