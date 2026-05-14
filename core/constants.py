from __future__ import annotations

from pathlib import Path

PLUGIN_NAME = "astrbot_plugin_robomaster_assistant"
DISPLAY_NAME = "RoboMaster赛事助手"
NO_RESULT_TEXT = "未在规则手册中找到可靠依据，请换个关键词试试。"
LAZY_REBUILD_NOTICE = "规则手册索引为空，正在自动构建索引，首次查询可能需要一段时间..."
DEFAULT_MANUAL_DIR = ""


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
    "manual_dir": ("rule_manual", "manual_search", "manual_storage_access"),
    "allowed_sessions": ("rule_manual", "manual_search", "manual_storage_access"),
    "blocked_sessions": ("rule_manual", "manual_search", "manual_storage_access"),
    "max_results": ("rule_manual", "manual_search", "manual_search_quality"),
    "min_score": ("rule_manual", "manual_search", "manual_search_quality"),
    "download_max_mb": ("rule_manual", "manual_download", "manual_download_limits"),
    "download_timeout_seconds": ("rule_manual", "manual_download", "manual_download_limits"),
    "download_free_space_buffer_mb": ("rule_manual", "manual_download", "manual_download_limits"),
    "enable_llm_explain": ("rule_manual", "manual_llm", "manual_llm_mode_provider"),
    "retrieval_mode": ("rule_manual", "manual_llm", "manual_llm_mode_provider"),
    "full_manual_provider_id": ("rule_manual", "manual_llm", "manual_llm_mode_provider"),
    "query_rewrite_provider_id": ("rule_manual", "manual_llm", "manual_llm_mode_provider"),
    "evidence_provider_id": ("rule_manual", "manual_llm", "manual_llm_mode_provider"),
    "enable_query_rewrite": ("rule_manual", "manual_llm", "manual_query_rewrite"),
    "query_rewrite_count": ("rule_manual", "manual_llm", "manual_query_rewrite"),
    "query_rewrite_result_limit": ("rule_manual", "manual_llm", "manual_query_rewrite"),
    "enable_vector_search": ("rule_manual", "manual_llm", "manual_local_vector_search"),
    "vector_result_limit": ("rule_manual", "manual_llm", "manual_local_vector_search"),
    "vector_min_score": ("rule_manual", "manual_llm", "manual_local_vector_search"),
    "enable_embedding_search": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "embedding_provider_id": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "embedding_result_limit": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "embedding_min_score": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "embedding_page_chars": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "embedding_batch_size": ("rule_manual", "manual_llm", "manual_embedding_search"),
    "full_manual_max_chars": ("rule_manual", "manual_llm", "manual_llm_scope_output"),
    "llm_candidate_pages": ("rule_manual", "manual_llm", "manual_llm_scope_output"),
    "llm_candidate_chars": ("rule_manual", "manual_llm", "manual_llm_scope_output"),
    "llm_select_all_evidence": ("rule_manual", "manual_llm", "manual_llm_scope_output"),
    "llm_max_results": ("rule_manual", "manual_llm", "manual_llm_scope_output"),
    "reply_mode": ("rule_manual", "reply_and_screenshot", "manual_reply_format"),
    "snippet_chars": ("rule_manual", "reply_and_screenshot", "manual_reply_format"),
    "lark_split_text_and_images": ("rule_manual", "reply_and_screenshot", "manual_reply_format"),
    "image_zoom": ("rule_manual", "reply_and_screenshot", "manual_screenshot_rendering"),
    "image_cache_seconds": ("rule_manual", "reply_and_screenshot", "manual_screenshot_rendering"),
    "crop_to_focus": ("rule_manual", "reply_and_screenshot", "manual_screenshot_rendering"),
    "crop_full_width": ("rule_manual", "reply_and_screenshot", "manual_screenshot_rendering"),
    "announce_enabled": ("announcement_notification", "announce_monitor", "announce_monitoring_state"),
    "announce_interval_seconds": ("announcement_notification", "announce_monitor", "announce_monitoring_state"),
    "announce_last_id": ("announcement_notification", "announce_monitor", "announce_monitoring_state"),
    "announce_monitored_pages": ("announcement_notification", "announce_monitor", "announce_monitoring_state"),
    "announce_notify_sessions": ("announcement_notification", "announce_monitor", "announce_delivery"),
    "announce_enable_lark_card_notifications": ("announcement_notification", "announce_monitor", "announce_delivery"),
    "forum_monitor_enabled": ("forum_monitor", "forum_crawler", "forum_monitoring_delivery"),
    "forum_scan_interval_seconds": ("forum_monitor", "forum_crawler", "forum_monitoring_delivery"),
    "forum_notify_sessions": ("forum_monitor", "forum_crawler", "forum_monitoring_delivery"),
    "forum_enable_lark_card_notifications": ("forum_monitor", "forum_crawler", "forum_monitoring_delivery"),
    "forum_article_url": ("forum_monitor", "forum_crawler", "forum_source_auth"),
    "forum_fetch_mode": ("forum_monitor", "forum_crawler", "forum_source_auth"),
    "forum_username": ("forum_monitor", "forum_crawler", "forum_source_auth"),
    "forum_password": ("forum_monitor", "forum_crawler", "forum_source_auth"),
    "forum_cookies_path": ("forum_monitor", "forum_crawler", "forum_source_auth"),
    "forum_chromium_executable_path": ("forum_monitor", "forum_crawler", "forum_browser_runtime"),
    "forum_headless": ("forum_monitor", "forum_crawler", "forum_browser_runtime"),
    "forum_user_agent": ("forum_monitor", "forum_crawler", "forum_browser_runtime"),
    "forum_list_limit": ("forum_monitor", "forum_crawler", "forum_fetch_limits"),
    "forum_http_timeout_seconds": ("forum_monitor", "forum_crawler", "forum_fetch_limits"),
    "forum_detail_css_selector": ("forum_monitor", "forum_crawler", "forum_fetch_limits"),
    "forum_summary_provider_id": ("forum_monitor", "forum_summary", "forum_summary_llm"),
    "forum_summary_max_chars": ("forum_monitor", "forum_summary", "forum_summary_llm"),
    "forum_query_provider_id": ("forum_monitor", "forum_query", "forum_query_settings"),
    "forum_query_max_results": ("forum_monitor", "forum_query", "forum_query_settings"),
    "match_monitor_enabled": ("match_notification", "match_monitor", "match_monitoring_delivery"),
    "match_scan_interval_seconds": ("match_notification", "match_monitor", "match_monitoring_delivery"),
    "match_notify_sessions": ("match_notification", "match_monitor", "match_monitoring_delivery"),
    "match_enable_lark_card_notifications": ("match_notification", "match_monitor", "match_monitoring_delivery"),
    "match_zone_allowlist": ("match_notification", "match_monitor", "match_monitoring_delivery"),
    "match_api_source": ("match_notification", "match_monitor", "match_data_source"),
    "schedule_api_base_url": ("match_notification", "match_monitor", "match_data_source"),
    "official_live_json_base_url": ("match_notification", "match_monitor", "match_data_source"),
    "match_query_cache_seconds": ("match_notification", "match_query", "match_query_cache_season"),
    "match_query_default_season": ("match_notification", "match_query", "match_query_cache_season"),
    "match_query_max_results": ("match_notification", "match_query", "match_query_output"),
    "match_query_include_vote": ("match_notification", "match_query", "match_query_output"),
    "match_query_include_replay": ("match_notification", "match_query", "match_query_output"),
    "match_query_enable_llm_parse": ("match_notification", "match_query", "match_query_llm_parse"),
    "match_query_llm_provider_id": ("match_notification", "match_query", "match_query_llm_parse"),
    "match_query_llm_timeout_seconds": ("match_notification", "match_query", "match_query_llm_parse"),
    "match_query_enable_info_image": ("match_notification", "match_query", "match_query_info_image"),
    "match_query_info_image_mode": ("match_notification", "match_query", "match_query_info_image"),
    "match_query_enable_schedule_screenshot": ("match_notification", "match_query", "match_query_info_image"),
    "match_query_forward_threshold_matches": ("match_notification", "match_query", "match_query_forward"),
    "match_query_forward_chunk_size": ("match_notification", "match_query", "match_query_forward"),
    "external_webhook_enabled": ("match_notification", "external_webhook", "external_webhook_delivery"),
    "external_webhook_urls": ("match_notification", "external_webhook", "external_webhook_delivery"),
}
