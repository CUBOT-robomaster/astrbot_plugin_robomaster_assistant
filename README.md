<div align="center">

<img src="logo.png" width="256" alt="icon">

# RoboMaster赛事助手

[![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FCUBOT-robomaster%2Fastrbot_plugin_robomaster_assistant%2Fmain%2Fmetadata.yaml&query=%24.version&label=version&color=blue&style=for-the-badge)](https://github.com/CUBOT-robomaster/astrbot_plugin_robomaster_assistant)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.16%2C%3C5-orange?style=for-the-badge)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue?style=for-the-badge)](LICENSE)
[![Platforms](https://img.shields.io/badge/Platforms-QQ%20%7C%20QQ%E5%AE%98%E6%96%B9%20%7C%20%E9%A3%9E%E4%B9%A6-green?style=for-the-badge)](https://github.com/CUBOT-robomaster/astrbot_plugin_robomaster_assistant)

</div>

RoboMaster赛事助手可以在群聊里检索规则手册、监控 RoboMaster 官网公告、监控比赛状态、沉淀论坛开源资料并主动推送通知。

目前支持 QQ/OneBot、QQ 官方接口和飞书。

## 快速开始

### 规则手册查询

1. 准备 RoboMaster 规则手册 PDF 的 HTTPS 下载链接。
2. 用具备 AstrBot 管理员权限的账号发送，示例地址请换成真实 PDF 地址：

   ```text
   更新规则手册 https://example.com/manual.pdf
   ```

   插件只处理第一个 HTTPS 链接。要更新多本手册，就分多次发送。

3. 看到 `规则手册更新完成` 后，在群里发送：

   ```text
   规则手册 自定义客户端
   规则手册 裁判系统串口协议
   规则手册 图传链路
   ```

`更新规则手册` 会下载 PDF、保存到手册目录、替换同名或可识别的旧版本，并自动重建索引。更新失败时会保留旧手册和旧索引。

### 论坛开源查询

先让插件收录论坛文章，再查询：

1. 在配置页面进入 **论坛开源监控** -> **论坛抓取** -> **监控与推送**，打开 **开启论坛开源监控**，或由管理员手动发送：

   ```text
   RM开源检查
   ```

   首次启用论坛监控时只建库不推送，避免把历史文章刷屏。

2. 有资料入库后，在群里发送：

   ```text
   开源查询 自瞄
   开源查询 电控代码
   开源查询 视觉定位
   ```

### 赛事查询

普通用户可以直接查赛程、比分、战队、回放、投票和历史交手；其中回放、投票和历史交手需要 `schedule` 或 `auto` 数据源。`赛事查询` 后面可以直接接自然语言问题，插件会先把问题解析成结构化查询，再用真实赛程数据回答：

```text
赛事查询 今天有哪些比赛
赛事查询 华南理工下一场什么时候
赛事查询 南部赛区第12场是谁打谁
赛事查询 华南理工和电子科技大学历史交手
赛事查询 今日
赛事查询 明日
赛事查询 南部赛区
赛事查询 华南理工大学
赛事查询 南部赛区 第12场
赛事查询 历史 华南理工大学 电子科技大学
```

默认数据源为 `auto`：优先调用 `https://schedule.scutbot.cn` 的公开 API，失败后回退 RoboMaster 官方 `live_json`。单场详情会尽量补充小程序投票比例和 B 站回放。选择 `official` 时只使用官方 `live_json`，不会访问 schedule API；投票、回放和历史交手会明确提示不支持。

默认情况下，赛事查询会以文字或 QQ/OneBot 合并转发返回，部署成本最低。想让查询结果显示为 RM Schedule 风格图片时，再到配置页开启 **赛事信息图片（实验功能）**，并按下方教程安装 Playwright 和 Chromium。

### 公告推送

1. 用管理员账号在想接收推送的群/会话里发送：

   ```text
   RM订阅公告
   ```

2. 在配置页面打开 **公告通知** -> **RM 公告监控** -> **监控状态** -> **开启 RM 公告监控**。

3. 改完配置后建议重载或重启插件。需要立即验证时，管理员可以发送：

   ```text
   RM公告检查
   ```

### 赛事推送

1. 用管理员账号在想接收赛事推送的群/会话里发送：

   ```text
   RM订阅赛事
   ```

2. 在配置页面打开 **赛事通知** -> **RM 赛事监控** -> **监控与推送** -> **开启 RM 赛事监控**。

3. 改完配置后建议重载或重启插件。需要立即验证时，管理员可以发送：

   ```text
   RM赛事检查
   ```

公告、赛事和论坛开源使用独立订阅列表。旧的 `RM订阅通知` / `RM取消订阅` 已移除，请改用 `RM订阅公告`、`RM订阅赛事`、`RM订阅开源` 及对应取消订阅命令。管理员可发送 `RM监控状态` 检查后台任务和各类订阅数量。

## 常用命令

普通用户可用：

- `规则手册 关键词/问题`
- `规则手册帮助`
- `开源查询 关键词/问题`
- `开源查询帮助`
- `赛事查询 关键词/日期/场次`
- `赛事查询帮助`

管理员可用：

- `更新规则手册 HTTPS下载链接`
- `重建规则手册索引`
- `RM开源检查`
- `RM开源重建索引`
- `RM开源导入`
- `RM订阅公告`
- `RM取消公告订阅`
- `RM订阅赛事`
- `RM取消赛事订阅`
- `RM订阅开源`
- `RM取消开源订阅`
- `RM监控状态`
- `RM公告检查`
- `RM赛事检查`

## LLM Tools

插件会向 AstrBot 注册 LLM Tools，模型可以在对话中自动调用规则手册、论坛开源查询、赛事查询和监控状态等能力。Tool 会复用本插件的会话白名单、黑名单和管理员权限校验。

## 功能配置

### 规则手册

规则手册功能用于把 PDF 手册变成群聊可查询的资料库，适合回答规则、接口、协议、链路等问题。

#### 手册文件和索引

推荐用管理员命令更新手册，把示例地址换成真实 PDF 地址：

```text
更新规则手册 https://example.com/manual.pdf
```

插件只接受 HTTPS 链接，不接受 HTTP 链接。这样做是为了避免机器人从不安全来源下载文件。下载到的新 PDF 会保存在 **规则手册** -> **规则手册文件与检索** -> **文件与会话权限** -> **规则手册 PDF 保存与扫描目录**，默认是 `data/plugin_data/astrbot_plugin_robomaster_assistant/manuals`。

如果要手动维护 PDF，把文件放进这个目录或它的子目录，然后发送：

```text
重建规则手册索引
```

`重建规则手册索引` 用于手动放入 PDF 后重新扫描，或在索引异常时修复。普通的 `更新规则手册` 已经会自动重建索引，不需要再额外发送。

索引只读取 PDF 中可复制的文字。纯图片扫描版 PDF 没有 OCR，可能无法检索；遇到这种情况，需要换成带文本层的 PDF。

#### 下载限制

在 **规则手册** -> **规则手册下载** -> **下载限制** 中可以调整单个手册大小、下载超时和磁盘空间预留。只有遇到大文件、慢网络或磁盘空间紧张时才需要改；下载失败会清理临时文件，解析失败会保留旧手册和旧索引。

#### 可用会话

在 **规则手册** -> **规则手册文件与检索** -> **文件与会话权限** 中可以限制插件在哪些群/会话里响应：

- **会话白名单**：留空表示所有会话都能用；填写后，只有名单内会话能用。
- **会话黑名单**：名单内会话不能用，优先级高于白名单。

不知道会话 ID 时，在目标群里发送 `/sid` 获取；也可以直接填写群号或用户号。多个 ID 用逗号、空格或换行分隔。

这些名单会限制本插件的所有命令，不只限制规则手册查询。想让机器人只服务指定队伍群，就填白名单；想屏蔽个别群，就填黑名单。

#### 检索效果

在 **规则手册** -> **规则手册文件与检索** -> **基础检索效果** 中可以调整返回数量和最低可靠分数。结果太多就减少返回数量；经常搜不到相关内容就适当降低分数；误命中过多就调高分数。

在 **规则手册** -> **规则手册 LLM 定位** 中可以按 **LLM 模式与提供商**、**查询改写**、**本地向量检索**、**嵌入模型检索**、**LLM 上下文与输出** 分别调整：

- 保持 `auto` 适合大多数群聊；模型不可用时会退回本地检索。
- 想完全按关键词检索时，选择 `keyword` 并关闭 **启用 LLM 简短解释**。
- 口语化问题、同义词问题较多时，可以开启嵌入模型检索；首次生成缓存会更慢，也会产生模型调用成本。

#### 回复和截图

在 **规则手册** -> **回复与截图** 中可以按 **回复格式** 和 **截图渲染与裁剪** 调整群聊回复：

- **回复模式**：`chain` 适合大多数平台；图片发送不稳定时用 `text`；QQ/OneBot 截图较多时用 `forward` 减少刷屏。
- **PDF 截图清晰度**：越高越清晰，图片也越大；图片发送慢或失败时调低。
- **按原文定位裁剪截图**：开启后会尽量只截相关位置；裁不到时自动发送整页。
- **飞书文字图片分开发送**：建议保持开启，避免飞书混合图文消息丢文字。

### 论坛开源资料

论坛开源资料用于监控 RoboMaster 论坛非置顶文章，保存标题、作者、分类、发布时间、详情正文和链接，再生成本地检索索引。首次启用监控时只建库不推送，避免把历史文章刷屏；后续发现新文章时会推送到 `RM订阅开源` 的会话或配置中的开源推送会话。

#### 抓取和入库

1. 在配置页面进入 **论坛开源监控** -> **论坛抓取** -> **监控与推送**，打开 **开启论坛开源监控**。

   默认 **论坛抓取模式** 是 `http`，只使用 `httpx` 和 HTML 解析，不需要安装 Chromium。HTTP 模式会读取 cookies、User-Agent 和 Referer，适合基础监控和轻量部署。

2. 可选：在本地浏览器登录 RoboMaster 论坛，确认能访问文章内容。若论坛内容需要登录态，建议按 **论坛 cookies 路径** 上传本地登录态。默认路径是：

   ```text
   data/plugin_data/astrbot_plugin_robomaster_assistant/forum/cookies.json
   ```

3. 如果 HTTP 模式遇到风控、登录态或页面渲染问题，再把 **论坛抓取模式** 切换为 `browser`，并安装 Playwright 浏览器依赖：

   ```bash
   pip install playwright
   ```

   ```bash
   python -m playwright install chromium
   ```

   如果云服务器已经安装了 Chromium，也可以在配置里填写 **Chromium 可执行文件路径**，或设置环境变量 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`。

4. 建议检查间隔保持默认 300 秒或更长。论坛访问不稳定时，优先补 cookies，再考虑切换 `browser` 模式。

#### 摘要和查询

在配置页面进入 **论坛开源监控** -> **开源 LLM 归纳**。

- **开源摘要 LLM**：留空时不会调用模型，只保存文章原文和基础信息。
- **单篇摘要最大字符数**：默认 6000 字符。粗略估计单篇约 2k 到 5k tokens；默认每次最多处理 10 篇文章，首次建库可能消耗约 20k 到 50k tokens。

在配置页面进入 **论坛开源监控** -> **开源查询**。

- **开源查询 LLM**：留空时使用当前会话模型；没有模型时直接返回本地检索结果。
- **开源查询结果数**：默认 5。想减少刷屏就调小，想多看候选文章就调大。

详情页正文默认按 `article.library-detail-content-detail,.library-detail-content-detail,.article-detail-content,.article-content` 提取。论坛页面可能由前端异步接口加载正文；如果 HTTP 模式无法从 HTML 提取列表或正文，可先上传有效 cookies、调整 **详情正文 CSS selector**，或切换为 `browser` 模式。

#### 外部导入

外部侧车程序可以把文章写成 JSONL 后放到：

```text
data/plugin_data/astrbot_plugin_robomaster_assistant/forum/imports/*.jsonl
```

然后发送 `RM开源导入`。每行至少包含 `title` 和 `url`，可选 `author`、`category`、`posted_at`、`raw_text`、`repo_links`。

### 公告通知

公告通知用于监控 RoboMaster 官网公告新增，以及指定公告页面正文变化。

#### 开启和接收

公告推送需要两件事：接收会话已经通过 `RM订阅公告` 加入公告通知接收列表，或填写在 **公告通知** -> **RM 公告监控** -> **推送目标** -> **公告推送会话**；并且 **监控状态** 里的 **开启 RM 公告监控** 已打开。推送会话可填群号、用户号、`/sid` 输出或完整会话 ID。改完配置后建议重载或重启插件，让后台监控任务按新配置启动。

#### 常用设置

- **公告检查间隔秒数**：默认 60，建议不要低于 15。
- **公告最后 ID**：首次监控的起点。建议填当前已知最新公告 ID，避免误报很早以前的历史公告。
- **监控公告页面 ID**：想监控某个公告正文是否变化，就填公告链接末尾的数字 ID。多个 ID 可以用逗号、空格或换行分隔。

管理员可以发送 `RM公告检查` 立即检查一次，用来验证配置是否生效。

### 赛事通知

赛事查询会按配置从 `schedule.scutbot.cn` 或官方 `live_json` 拉取赛程数据；赛事通知复用同一套数据层，识别比赛开始、比分变化和比赛结束。

#### 赛事查询

赛事查询命令见快速开始。它支持日期、赛区、战队、单场详情和历史交手；其中投票、回放和历史交手需要 `schedule` 或 `auto` 数据源。

#### 数据源

在 **赛事通知** -> **RM 赛事监控** -> **赛事数据源** 中可以调整：

- **赛事数据源**：`auto` 优先使用 schedule API，失败后回退官方接口；`schedule` 只使用 `schedule.scutbot.cn`；`official` 只使用官方 `live_json` 下的 `schedule.json` 和 `current_and_next_matches.json`，不访问 schedule API，且不支持投票、回放和历史交手。
- **Schedule API 地址**：默认 `https://schedule.scutbot.cn`。
- **官方 live_json 地址**：默认 `https://pro-robomasters-hz-n5i3.oss-cn-hangzhou.aliyuncs.com/live_json`。

在 **赛事通知** -> **RM 赛事查询** 中可以按 **缓存与赛季**、**结果内容** 调整查询缓存、默认赛季、列表返回数量，以及单场详情是否附带投票和回放。默认赛季、投票和回放开关只对 schedule API 生效，`official` 模式会忽略或提示不支持。

**LLM 查询理解** 默认开启，用于把“今天有哪些比赛”“南部赛区第12场是谁打谁”这类自然语言问题解析成日期、赛区、场次或历史交手参数。LLM 不直接生成赛事答案；模型不可用或解析失败时会自动回退到本地规则解析。

查询明确日期赛程时，文字会返回当天全部比赛，不再只显示前 8 场。QQ/OneBot 中结果较长时会自动尝试合并转发，减少刷屏；其他平台保持普通文本或图文回复。

#### 赛事信息图片

赛事信息图片是可选增强功能，默认关闭。不开启时，赛事查询仍然会稳定返回文字；在 QQ/OneBot 中结果较长时会自动尝试合并转发。开启后，插件会先用真实赛事数据生成答案，再把这些事实交给赛事查询 LLM 规划表格或流程图 JSON，最后用本地 HTML/CSS 渲染成 RM Schedule 风格图片。LLM 只负责排版，不负责编造赛程事实。

在配置页面进入 **赛事通知** -> **RM 赛事查询** -> **赛事信息图片（实验功能）**：

- **启用赛事信息图片**：打开后，`赛事查询` 会优先尝试发送图文结果。图片渲染依赖 Playwright 和 Chromium；未安装时会自动退回文字。
- **图片展示模式**：`auto` 会按用户问题自动选择；`table` 固定生成表格；`flowchart` 固定生成流程图。用户提到“流程图”“对阵图”“晋级图”时，`auto` 会优先走流程图。
- **备用网页赛程截图**：只在本地赛事信息图片渲染失败、且查询的是明确日期赛程时生效。它会尝试截图 RM Schedule 网页，同样需要 Playwright 和 Chromium。

推荐使用顺序：

1. 先保持默认文字回复，确认 `赛事查询 今日`、`赛事查询 南部赛区` 等基础能力正常。
2. 需要群聊展示效果时，再开启 **启用赛事信息图片**。
3. 如果希望明确日期赛程在本地图片失败后仍有网页截图兜底，再开启 **备用网页赛程截图**。

如果赛事查询 LLM 不可用，插件会使用基础表格数据作为图片输入；如果 Playwright 或 Chromium 不可用，插件会只发送文字，不会影响赛事查询本身。赛事图片缓存保存在插件数据目录的 `images/match`，规则手册截图缓存在同级的 `images/manual`。

#### Playwright 安装教程

Playwright 不在默认依赖里，只有开启赛事信息图片、备用网页赛程截图，或把论坛抓取模式切到 `browser` 时才需要安装。关键原则是：必须安装到 AstrBot 实际运行的同一个 Python 环境里。

Linux/云服务器原生 Python 部署：

```bash
cd /path/to/AstrBot
source .venv/bin/activate
pip install playwright
python -m playwright install chromium
```

如果你没有使用虚拟环境，就在启动 AstrBot 的同一个用户和 Python 下执行后两条命令。部分精简 Linux 发行版还需要系统依赖；遇到 Chromium 启动失败时，可以再执行：

```bash
python -m playwright install --with-deps chromium
```

Docker 或面板部署：

```bash
docker exec -it <容器名或容器ID> bash
pip install playwright
python -m playwright install chromium
```

如果容器里没有 `bash`，把第一行改成 `sh`。注意：直接进运行中的容器安装，容器重建后可能丢失；长期使用建议把这两条安装命令写进镜像构建流程，或确认你的面板会持久化 Python 环境。安装完成后重启 AstrBot 或重载插件。

Windows 桌面或本地运行：

```powershell
cd D:\path\to\AstrBot
.\.venv\Scripts\Activate.ps1
pip install playwright
python -m playwright install chromium
```

如果 AstrBot 不是用 `.venv` 启动的，就打开启动 AstrBot 的同一个终端环境执行 `pip install playwright` 和 `python -m playwright install chromium`。电脑上另一个 Python 装好了也没用，日志仍会出现 `No module named 'playwright'`。

已有系统 Chromium 时需要注意：当前赛事信息图片和备用网页赛程截图默认使用 Playwright 托管的 Chromium，不读取自定义 Chromium 路径。配置里的 **Chromium 可执行文件路径** 只用于论坛开源抓取的 `browser` 模式，不用于赛事图片渲染。

#### 验证与排障

安装和配置完成后，在目标群里发送：

```text
赛事查询 今日
```

正常情况下，开启赛事信息图片后会收到文字加图片；当天赛程很多时，QQ/OneBot 也可能以合并转发节点发送。

- 日志出现 `No module named 'playwright'`：Playwright 没装到 AstrBot 正在使用的 Python 环境。回到 AstrBot 的虚拟环境、容器或启动终端重新安装。
- 日志出现 Chromium launch 相关失败：通常是 Chromium 没安装完整，或 Linux 服务器缺少浏览器系统依赖。优先执行 `python -m playwright install chromium`，Linux 可尝试 `python -m playwright install --with-deps chromium`。
- 已开启配置但仍只发文字：确认 **启用赛事信息图片** 已打开并重载/重启插件；确认消息平台支持发送本地图片；QQ/OneBot 长结果可能优先显示为合并转发。
- 日志出现 `Prepare to send ... [ComponentType.Node]`：这是 QQ/OneBot 合并转发节点，不代表 Playwright 报错。真正的图片依赖问题会同时出现 `No module named 'playwright'` 或 Chromium 启动失败日志。
- 不想安装浏览器依赖：保持 **启用赛事信息图片** 和 **备用网页赛程截图** 关闭即可，赛事查询会继续使用文字或合并转发。

#### 开启和接收

赛事推送使用独立接收列表。接收会话需要通过 `RM订阅赛事` 加入赛事通知接收列表，或填写在 **赛事通知** -> **RM 赛事监控** -> **监控与推送** -> **赛事推送会话**；推送会话可填群号、用户号、`/sid` 输出或完整会话 ID。然后打开同组里的 **开启 RM 赛事监控**，再重载或重启插件即可。

#### 常用设置

- **赛事检查间隔秒数**：默认 30。想更及时可以调到 10 到 15。
- **赛事监控赛区白名单**：留空表示监控全部赛区。只想看部分赛区时，填写赛区名称，多个值用逗号、空格或换行分隔。
- **赛事启用飞书卡片**：需要先在对应飞书会话里发送 `RM订阅赛事`；不可用时会自动降级为文本。

管理员可以发送 `RM赛事检查` 立即检查一次，用来验证配置是否生效。

### 推送出口

推送出口负责把监控结果发到固定会话、飞书卡片或外部 Webhook。

#### 通知会话和飞书卡片

- **飞书卡片通知**：公告、赛事、开源分别在各自监控分组中启用；不可用时会自动降级为普通文本。
- **推送会话**：配置页填写的目标和订阅命令记录的目标会合并去重。取消订阅只删除命令订阅记录；如果同一个群号仍写在配置页里，它还会继续接收。
- **群号解析**：可直接填群号或用户号，但机器人需要先在该会话见过消息，或先执行过对应订阅命令。解析失败的目标会被跳过并写入日志。

旧的 **公告通知** -> **RM 通知订阅** 共用配置已删除。

#### 外部 Webhook

- **开启外部 Webhook**：开启后，公告和赛事事件会额外 POST 到你填写的地址。
- **外部 Webhook 地址**：可以填一个或多个 HTTP/HTTPS 地址，多个地址用逗号、空格或换行分隔。

外部 Webhook 在 **赛事通知** -> **外部 Webhook** -> **Webhook 推送** 中配置。它适合把公告和赛事事件接到自建面板、自动化脚本或其他通知系统。

## 致谢

本插件的部分实现参考了以下开源项目，在此表示感谢：

- [scutrobotlab/RMAnnounce](https://github.com/scutrobotlab/RMAnnounce)
- [scutrobotlab/rm-monitor](https://github.com/scutrobotlab/rm-monitor)
- [Aurora-UJS/robomaster-monitor](https://github.com/Aurora-UJS/robomaster-monitor)

## TODO

- [x] 实现让用户在使用 AstrBot 进行对话时自动调用 Tool
- [ ] 参考飞书官方larkcli，增强插件的飞书交互功能

## Contributing

欢迎提交 Issue 或 Pull Request 来改进这个插件！无论是修复 bug、优化性能，还是添加新功能，我们都非常欢迎社区的贡献。

## License

Apache License 2.0
