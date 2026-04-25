# RoboMaster赛事助手

RoboMaster赛事助手是一个 AstrBot 插件，提供三类能力：

- 检索本地 RoboMaster PDF 规则手册
- 监控 RoboMaster 官网公告新增和正文更新
- 监控 RoboMaster 赛事状态，并主动推送比赛开始、单局结束和比赛结束通知

插件目前支持 QQ/OneBot、QQ 官方接口和飞书。

## 命令

规则手册检索：

`规则手册 xxx`
`规则手册帮助`

管理员命令：

`重建规则手册索引`
`RM订阅通知`
`RM取消订阅`
`RM监控状态`
`RM公告检查`
`RM赛事检查`

其中 `RM订阅通知` 会把当前群/会话加入主动推送目标。公告和赛事监控只会推送到已订阅会话，或 WebUI 中 `rm_notification.notify_sessions` 配置的会话。

## 配置

一般只需要先配置 `manual_search.manual_dir`，把 PDF 放进去后发送 `重建规则手册索引`；需要主动推送时，再开启公告或赛事监控，并配置通知会话。

多个 ID、会话或 URL 都可以用逗号、空格或换行分隔，例如：

```text
123456789
aiocqhttp:GroupMessage:123456789
```

布尔项在 WebUI 里直接开关即可；如果手动写配置，`true`、`1`、`yes`、`on`、`启用`、`是` 都会被识别为开启。

### `manual_search`：规则手册检索

- `manual_dir`：规则手册 PDF 目录，默认 `data/rm_manuals`。插件会递归扫描这个目录下所有 PDF；可以填相对 AstrBot 运行目录的路径，也可以填绝对路径。新增、删除或替换 PDF 后，发送 `重建规则手册索引` 重新扫描。
- `allowed_sessions`：会话白名单，默认留空，表示所有会话都可以使用 `规则手册 ...` 和 `规则手册帮助`。要限制使用范围时，填写群号、用户号或 `/sid` 得到的会话 ID。
- `blocked_sessions`：会话黑名单，默认留空。命中黑名单的会话不能使用检索；黑名单优先级高于白名单。
- `max_results`：最多返回结果数，默认 `3`。没有可用 LLM 或 LLM 失败时，会按这个数量返回检索依据。
- `min_score`：最低可靠分数，默认 `0.6`。搜不到但你确定 PDF 里有内容时，可以适当降到 `0.4` 到 `0.5`；误命中太多时，可以调到 `0.7` 以上。

### `manual_llm`：规则手册 LLM 定位

- `enable_llm_explain`：启用 LLM 简短解释，默认开启。需要当前会话在 AstrBot 中有可用的 LLM 提供商；没有模型时插件会自动退回纯关键词检索。
- `llm_candidate_pages`：交给 LLM 判断的候选页数，默认 `10`。想让模型看得更全可以调大，但响应会更慢、消耗更多。
- `llm_candidate_chars`：每个候选页截取给 LLM 的原文长度，默认 `260`。问题经常涉及长表格或长段落时可以调到 `400` 左右。
- `llm_select_all_evidence`：让 LLM 选择所有必要依据，默认开启。关闭后最多按 `max_results` 的数量返回。
- `llm_max_results`：LLM 截图上限，默认 `0`，表示不额外限制，只受候选页数限制。群里不想刷太多图时可填 `3` 或 `5`。

### `reply_and_screenshot`：回复与截图

- `reply_mode`：回复模式，默认 `chain`。
  - `text`：只发文字依据，不生成截图。
  - `chain`：发送一条图文消息，适合大多数 QQ/OneBot 场景。
  - `forward`：发送 QQ 合并转发消息，主要建议 OneBot v11/QQ 使用；飞书会自动退回 `chain`。
  - `both`：发送较完整的文字依据和截图，信息最全但消息更长。
- `snippet_chars`：每条原文片段长度，默认 `120`。文字太长就调小；需要更多上下文就调大。
- `lark_split_text_and_images`：飞书文字和图片分开发送，默认开启。飞书混合图文可能丢文字，建议保持开启。
- `image_zoom`：PDF 截图清晰度，默认 `1.8`。建议 `1.5` 到 `2.2`；越大越清晰，图片也越大。
- `image_cache_seconds`：截图缓存保留秒数，默认 `86400`，也就是 1 天。旧截图会在生成新截图时清理。
- `crop_to_focus`：按原文定位裁剪截图，默认开启。有 LLM 时会优先按 LLM 给出的短句裁剪局部截图；裁不到会退回整页。
- `crop_full_width`：裁剪时保留整页宽度，默认开启。建议保持开启，避免表格或段落左右被切掉。

### `rm_notification`：RM 通知订阅

- `notify_sessions`：固定主动推送会话，默认留空。可以填 `/sid` 得到的 `unified_msg_origin`，也可以填通过 `RM订阅通知` 记录到的会话 ID。多个会话用逗号、空格或换行分隔。
- `enable_lark_card_notifications`：启用飞书卡片通知，默认关闭。开启后，需要在飞书会话里执行一次 `RM订阅通知`，让插件记录飞书运行时信息；不可用时会自动降级为普通文本。

`RM订阅通知` 会把当前会话写入插件运行状态文件，不需要手动复制 ID；`RM取消订阅` 会移除当前会话。WebUI 里的 `notify_sessions` 更适合填写固定通知目标，重启后仍按配置加载。

### `announce_monitor`：RM 官网公告监控

- `announce_enabled`：开启 RM 公告监控，默认关闭。开启或关闭后建议重载/重启插件，让后台任务按新配置启动或停止。
- `announce_interval_seconds`：公告检查间隔秒数，默认 `60`。插件内部最低按 5 秒执行，实际建议不低于 `15`。
- `announce_last_id`：公告最后 ID，默认 `0`。插件会检查 `announce_last_id + 1` 对应公告是否存在；首次使用建议填当前已知最新公告 ID，避免从很早的 ID 开始或误报历史公告。
- `announce_monitored_pages`：监控公告页面 ID，默认留空。填写公告 URL 末尾的数字 ID 后，插件会记录正文 hash，后续正文变化时推送更新通知。

公告监控会把运行中的 `announce_last_id` 和页面 hash 保存到插件数据目录。配置里的 `announce_last_id` 主要是首次启动时的起点；运行后以状态文件中的值为准。

### `match_monitor`：RoboMaster 赛事监控

- `match_monitor_enabled`：开启 RM 赛事监控，默认关闭。开启或关闭后建议重载/重启插件。
- `match_scan_interval_seconds`：赛事检查间隔秒数，默认 `30`，内部最低按 5 秒执行。想更及时可以调到 `10` 到 `15`。
- `dji_current_api_url`：DJI 当前比赛接口，默认已填官方公开 JSON 地址。接口地址变更时才需要改。
- `dji_schedule_api_url`：DJI 赛程接口，默认已填官方公开 JSON 地址。用于比赛结束后尝试补充最终比分，通常不用改。
- `match_zone_allowlist`：赛事监控赛区白名单，默认留空表示监控全部赛区。只想看某些赛区时，填写接口里的赛区名称，多个值用逗号、空格或换行分隔。

赛事监控会识别：

- `match_start`：比赛开始
- `match_session_end`：同一对阵小局变化
- `match_end`：当前对阵结束或消失

### `external_webhook`：外部 Webhook

- `external_webhook_enabled`：开启外部 Webhook，默认关闭。开启后，公告和赛事事件除了发到订阅会话，也会 POST 到配置的 URL。
- `external_webhook_urls`：Webhook 地址，默认留空。可填写一个或多个 HTTP/HTTPS URL，多个 URL 用逗号、空格或换行分隔。请求体为 JSON，格式大致为 `{"type": "事件类型", "data": {...}}`。

### 推荐配置流程

1. 把 RoboMaster 规则手册 PDF 放到 `manual_search.manual_dir`，例如 `data/rm_manuals`。
2. 在管理员会话发送 `重建规则手册索引`，看到 PDF 数量和可检索页数后再开始查询。
3. 如果只想指定群使用，先用 `/sid` 获取会话 ID，再填到 `allowed_sessions`；如果只想屏蔽个别群，填 `blocked_sessions`。
4. 需要公告或赛事推送时，先在目标群/会话发送 `RM订阅通知`，再开启 `announce_enabled` 或 `match_monitor_enabled` 并重载/重启插件。
5. 用 `RM监控状态` 查看开关、订阅会话数量、公告 last_id 和后台任务是否正常。

## License

Apache License 2.0
