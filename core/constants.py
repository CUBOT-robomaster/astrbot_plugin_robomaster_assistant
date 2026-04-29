from __future__ import annotations

from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_robomaster_assistant"
DISPLAY_NAME = "RoboMaster赛事助手"
NO_RESULT_TEXT = "未在规则手册中找到可靠依据，请换个关键词试试。"
DEFAULT_MANUAL_DIR = f"data/plugin_data/{PLUGIN_NAME}/manuals"


def _metadata_version() -> str:
    # 步骤1: 找到 metadata.yaml 文件的路径
    # Path(__file__) 是当前文件路径
    # .parents[1] 向上一级目录(到插件根目录)
    metadata_path = Path(__file__).resolve().parents[1] / "metadata.yaml"

    try:
        # 步骤2: 读取文件内容,逐行查找 "version:" 这一行
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition(":")  # 按 ":" 分割
            if separator and key.strip() == "version":
                return value.strip().strip("\"'")  # 去掉空格和引号
    except OSError:
        pass

    # 步骤3: 如果找不到或读取出错,返回默认值 "0.0.0"
    return "0.0.0"


# 在模块加载时就执行这个函数,把结果存为常量
PLUGIN_VERSION = _metadata_version()

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
    "retrieval_mode": ("rule_manual", "manual_llm"),
    "full_manual_provider_id": ("rule_manual", "manual_llm"),
    "query_rewrite_provider_id": ("rule_manual", "manual_llm"),
    "evidence_provider_id": ("rule_manual", "manual_llm"),
    "enable_query_rewrite": ("rule_manual", "manual_llm"),
    "query_rewrite_count": ("rule_manual", "manual_llm"),
    "query_rewrite_result_limit": ("rule_manual", "manual_llm"),
    "enable_vector_search": ("rule_manual", "manual_llm"),
    "vector_result_limit": ("rule_manual", "manual_llm"),
    "vector_min_score": ("rule_manual", "manual_llm"),
    "enable_embedding_search": ("rule_manual", "manual_llm"),
    "embedding_provider_id": ("rule_manual", "manual_llm"),
    "embedding_result_limit": ("rule_manual", "manual_llm"),
    "embedding_min_score": ("rule_manual", "manual_llm"),
    "embedding_page_chars": ("rule_manual", "manual_llm"),
    "embedding_batch_size": ("rule_manual", "manual_llm"),
    "full_manual_max_chars": ("rule_manual", "manual_llm"),
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
    "forum_monitor_enabled": ("forum_monitor", "forum_crawler"),
    "forum_scan_interval_seconds": ("forum_monitor", "forum_crawler"),
    "forum_article_url": ("forum_monitor", "forum_crawler"),
    "forum_username": ("forum_monitor", "forum_crawler"),
    "forum_password": ("forum_monitor", "forum_crawler"),
    "forum_cookies_path": ("forum_monitor", "forum_crawler"),
    "forum_chromium_executable_path": ("forum_monitor", "forum_crawler"),
    "forum_headless": ("forum_monitor", "forum_crawler"),
    "forum_user_agent": ("forum_monitor", "forum_crawler"),
    "forum_list_limit": ("forum_monitor", "forum_crawler"),
    "forum_summary_provider_id": ("forum_monitor", "forum_summary"),
    "forum_summary_max_chars": ("forum_monitor", "forum_summary"),
    "forum_query_provider_id": ("forum_monitor", "forum_query"),
    "forum_query_max_results": ("forum_monitor", "forum_query"),
}
