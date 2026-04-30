# Changelog

## 0.7.3 - 2026-04-30

### Fixed

- 修复 `Main.__init__` 签名与框架不一致的潜在问题：`config` 参数改为可选，避免框架未注入时实例化报错。
- 修复 `search_manual` 中"规则手册帮助"分支未调用 `_stop_event`，可能导致与 `manual_help_command` 重复响应。

### Changed

- 将 `_send_forum_progress` 中的 f-string 日志改为延迟格式化，减少无效字符串拼接。
- 提取 `normalize_text` / `tokenize` 到共享模块 `core/text_utils.py`，消除 `forum/search_index.py` 与 `manual/search_engine.py` 间的重复代码。

## 0.7.2 - 2026-04-30

### Fixed
- 修复论坛列表解析器遇到头像、封面等 `<img>` 标签后无法结束文章卡片解析，导致 browser 模式抓到页面却显示列表 0 篇的问题。
