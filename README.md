# RoboMaster赛事助手

RoboMaster赛事助手是一个 AstrBot 插件，提供三类能力：

- 检索本地 RoboMaster PDF 规则手册
- 监控 RoboMaster 官网公告新增和正文更新
- 监控 RoboMaster 赛事状态，并主动推送比赛开始、单局结束和比赛结束通知

插件目前支持 QQ/OneBot、QQ 官方接口和飞书。

## 命令

规则手册检索：

```text
规则手册 自定义客户端
规则手册 裁判系统串口协议
规则手册 图传链路
规则手册帮助
```

管理员命令：

```text
重建规则手册索引
RM订阅通知
RM取消订阅
RM监控状态
RM公告检查
RM赛事检查
```

`RM订阅通知` 会把当前群/会话加入主动推送目标。公告和赛事监控只会推送到已订阅会话，或 WebUI 中 `rm_notification.notify_sessions` 配置的会话。

## 配置

插件配置页按 AstrBot `object` 嵌套配置分组：

- `manual_search`：PDF 目录、会话白名单/黑名单、结果数量和最低分数
- `manual_llm`：LLM 候选页、解释、选择全部依据和截图上限
- `reply_and_screenshot`：回复模式、飞书图文拆分、PDF 截图和裁剪
- `rm_notification`：主动推送会话、飞书卡片通知
- `announce_monitor`：RM 官网公告监控
- `match_monitor`：RoboMaster 赛事监控
- `external_webhook`：外部 Webhook 推送

公告监控默认关闭。开启后插件会定时检查 `announce_last_id + 1` 对应公告是否存在，并可监控 `announce_monitored_pages` 中指定公告页面正文 hash 是否变化。

赛事监控默认关闭。开启后插件会定时拉取 DJI 赛事接口，识别：

- `match_start`：比赛开始
- `match_session_end`：同一对阵小局变化
- `match_end`：当前对阵结束或消失

## 飞书卡片

普通飞书通知不需要额外配置 App ID 或 App Secret。

如需卡片通知：

1. 安装 `lark-oapi`，本插件依赖已声明；安装 `astrbot_lark_enhance` 通常也已具备该依赖。
2. 在插件配置中开启 `rm_notification.enable_lark_card_notifications`。
3. 在目标飞书会话中发送 `RM订阅通知`，让插件记录该会话的 `chat_id` 并缓存运行时飞书客户端。

如果 AstrBot 重启后尚未缓存到飞书运行时客户端，或飞书卡片接口权限不足，插件会自动降级为普通文本通知。

## 数据与隐私

以下内容属于本地运行数据，不应提交到公开仓库：

- `rm_monitor_state.json`：包含订阅会话、`unified_msg_origin`、飞书 `chat_id`
- `index.json`：包含 PDF 页面文本索引，可能包含完整手册内容
- `images/`：PDF 页面截图缓存
- `notify_sessions`、`external_webhook_urls`：可能包含群聊标识或私有 Webhook
- 本地 RoboMaster PDF 手册文件

插件日志会尽量避免输出完整会话 ID、飞书 `chat_id` 和 Webhook URL。排查问题时如需分享日志，请仍然先检查并脱敏。

## 测试

在插件目录内运行：

```bash
PYTHONPATH=. python -m pytest -q tests
python -m json.tool _conf_schema.json
python -m py_compile *.py tests/*.py
```

## License

Apache License 2.0
