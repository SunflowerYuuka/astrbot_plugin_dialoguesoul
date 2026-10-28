# 更新日志

## v1.2.0

### 新增

- `trigger.proactive_delay_seconds`：主动回复等待时间，默认 5 秒；非直接 @ 的触发命中后固定等待再调用模型，期间新消息、上下文和等待窗口内图片会一并带上，直接 @ 会打断等待，`0` 表示关闭。

## v1.1.0

### 新增

- `trigger.interest.enabled`：兴趣判断开关，默认开启；关闭时 `interest` 策略退化为时间窗口。
- `wake.final_reply_prompt`：唤醒会话最后一条回复的收尾提示词，可自定义，留空不注入。

### 修复

- 唤醒次数在 aiocqhttp 下按实际发送成功计数，发送失败不再消耗次数。
- 合并转发拉取兼容 `bot.call_action` / `event.call_api`，并支持 OneBot 的 `data.text` 与嵌套节点结构。
- 合并转发获取失败或为空时输出占位文本并记录警告日志。

## v1.0.0

首个正式版本。

### 新增

- 自主回复、关键词/问句/概率触发、直接 @ 与可选唤醒会话。
- 四种触发策略：`every_message`、`rules`、`window`、`interest`，默认 `window`（30 秒窗口）。
- 两种决策格式：`marker`（默认，使用 `<NO_RESPONSE>`）与 `json`（支持多消息、置信度与历史引用）。
- 唤醒会话限制：总时长、空闲超时与回复次数 `max_replies`，支持私聊、管理员和指定群覆盖；模型忽略不消耗次数，发送计数为 best-effort（AstrBot 4.29.1 无可靠发送失败标志）。
- SQLite 最近历史：按聊天隔离、可配置保留天数与条数，并支持旧 SpectreCore JSON 历史的一次性导入。
- 可选上下文增强：图片转述、合并转发解析与模型摘要，默认关闭。
- 内置知识库与通用 `on_llm_request` / `on_llm_response` 钩子兼容，包括 LivingMemory。
- `/ds help`、`/ds history`、`/ds reset`、`/ds mute`、`/ds unmute`、`/ds status` 指令。
- 可选刷屏保护：按群配置阈值与静默时长。

### 许可

- 本项目采用 AGPL-3.0，按公开行为独立重写，不复制 SpectreCore 或其他第三方插件代码。
