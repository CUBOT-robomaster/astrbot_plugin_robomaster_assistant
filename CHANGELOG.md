main.py:222-258 — rm_forum_check 处理器：

立即 yield "正在检查 RM 论坛开源内容..." 让用户知道已开始
创建 on_progress 回调，通过 context.send_message 实时推送进度
传入 force_notify=True 确保即使是首次检查也返回结果
用 try/except 捕获异常并报告具体错误
有新文章时列出标题和链接；无新文章时明确告知"列表页访问正常"
monitors/service.py:185-204 — run_forum_check / run_forum_check_unlocked：

新增 force_notify 参数，为 True 时忽略 initialized 标志直接返回文章
新增 on_progress 回调参数，透传给 forum.check()
forum/service.py:59-99 — check()：

新增 on_progress 回调，在关键步骤（访问列表页、获取详情、LLM 摘要、重建索引）发送进度消息
列表页访问失败时通过回调报告错误再抛出
