# 更新日志

## v1.0.0

首个正式版本。

### 新增

- 自主回复、关键词/问句/概率触发、直接 @ 与可选唤醒会话。
- 四种触发策略：`every_message`、`rules`、`window`、`interest`，默认 `window`（30 秒窗口）。
- 两种决策格式：`marker`（默认，使用 `<NO_RESPONSE>`）与 `json`（支持多消息、置信度与历史引用）。
- 唤醒会话限制：总时长、空闲超时与成功回复次数 `max_replies`，支持私聊、管理员和指定群覆盖；模型忽略或发送失败不消耗次数。
- SQLite 最近历史：按聊天隔离、可配置保留天数与条数，并支持旧 SpectreCore JSON 历史的一次性导入。
- 可选上下文增强：图片转述、合并转发解析与模型摘要，默认关闭。
- 内置知识库与通用 `on_llm_request` / `on_llm_response` 钩子兼容，包括 LivingMemory。
- `/ds help`、`/ds history`、`/ds reset`、`/ds mute`、`/ds unmute`、`/ds status` 指令。
- 可选刷屏保护：按群配置阈值与静默时长。

### 许可

- 本项目采用 AGPL-3.0，按公开行为独立重写，不复制 SpectreCore 或其他第三方插件代码。
