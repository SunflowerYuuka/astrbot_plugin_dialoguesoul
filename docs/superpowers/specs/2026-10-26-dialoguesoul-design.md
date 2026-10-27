# DialoguesSoul 设计

日期：2026-10-26
状态：待评审
目标版本：v1.0.0

## 1. 背景与目标

DialoguesSoul 是以 SpectreCore 的行为与使用体验为参考、独立重写的群聊社交引擎。它保留自主回复、概率/关键词触发、唤醒会话、上下文增强和管理指令，但把生成、知识库、长期记忆、工具和发送交给 AstrBot 管线。

核心目标：

- 自主回复和概率回复能够使用 AstrBot 内置知识库，以及任何通过 `on_llm_request` / `on_llm_response` 工作的第三方插件（包括 LivingMemory）。
- 插件自身不保存长期记忆，只保存用于组装上下文的最近聊天历史。
- 状态与存储可支持多账号、多平台。
- 用 SQLite 替代原 JSON 历史文件。
- 从 SpectreCore 自动导入一次历史。

## 2. 非目标

v1 不做：

- 自定义发送队列、账号级/群级发送节奏
- 自建长期记忆或摘要
- 针对某个第三方插件的专用适配代码
- 图片持久化、后台批量图片转述
- 自定义 provider 选择与直接调用 provider
- 插件级工具管理

## 3. 关键决策

1. **完全走 AstrBot 管线**：插件只构造 `ProviderRequest` 并 `yield`，由 AstrBot 完成知识库、钩子、生成和发送。
2. **发送使用 AstrBot 原生能力**：流式、分段、引用、发送后钩子由 AstrBot 负责；发送队列后续作为可选模块。
3. **规则触发 + LLM 决策**：规则门控决定是否请求模型；模型决定是否回复以及回复内容。
4. **通用兼容**：不识别具体插件，不调用第三方插件内部 API；只依赖 `on_llm_request` / `on_llm_response` 这类通用钩子。
5. **不绑定 AstrBot 会话**：请求中不设置 `req.conversation`，避免 AstrBot 覆盖人格和自动挂载工具，保证 JSON 决策协议稳定。
6. **最近历史用 SQLite**：通过 `HistoryRepository` 隔离，支持索引、事务、保留清理和多账号查询。
7. **自动导入一次**：首次启动且数据库为空时，尝试导入 SpectreCore 的 JSON 历史，成功后写入标记，避免重复导入。
8. **指令前缀 `/ds`**。
9. **MIT 许可 + 独立重写**：不复制 SpectreCore 源码，只参考其公开行为、配置语义和使用体验；所有模块、测试与文档按本 spec 重新实现，项目采用 MIT 许可。

## 4. AstrBot 集成事实

基于 AstrBot 4.29.1 源码核对：

- 插件处理器 `yield event.request_llm(...)` 后，`ProcessStage` 把请求放入 `provider_request`，随后进入 `build_main_agent`。
- `build_main_agent` 即使收到插件提供的请求，也会执行 `_apply_kb`，因此内置知识库仍然生效。
- `on_llm_request` 钩子在 provider 调用前执行，第三方插件可修改 `req`。
- `on_llm_response` 钩子在响应返回后执行，用于改写响应或记录记忆。
- `on_decorating_result` 在发送前执行，可改写或清空结果。
- `after_message_sent` 在消息发送后执行。
- `_ensure_persona_and_skills` 只在 `req.conversation` 存在时注入人格和工具集，因此不设置 `req.conversation` 可避免覆盖与工具注入。
- 钩子 `priority` 数值越大越先执行。

## 5. 总体架构

```
消息事件
  → Router（@ / 概率 / 关键词 / 唤醒 / 忽略）
  → Gate（硬门控、限流、候选评分）
  → ContextBuilder（SQLite 历史、图片、转发、引用、人格、提示词）
  → RequestBuilder（普通请求 / JSON 决策请求）
  → yield ProviderRequest
  → AstrBot：知识库 + on_llm_request（第三方记忆等）+ 生成
  → on_llm_response：解析并改写 JSON 决策
  → on_decorating_result：发送真实回复或清空结果
  → after_message_sent：写入最近历史、更新唤醒会话
```

模块：

| 模块 | 职责 |
|---|---|
| `main.py` | 插件注册、事件入口、钩子、`/ds` 指令 |
| `router.py` | 消息路由与优先级 |
| `gate.py` | 硬门控、限流、候选评分（实例状态） |
| `context/` | SQLite 历史、图片、转发、引用、人格、提示词 |
| `decision.py` | JSON 协议、解析、响应改写 |
| `wake.py` | 唤醒会话状态与限制 |
| `config.py` | 配置模型、默认值、迁移 |
| `storage/` | SQLite 仓储、schema、旧数据导入 |

## 6. 消息流程

### 6.1 直接 @ / 回复机器人

1. Gate 识别直接地址，绕过冷却与每分钟上限。
2. ContextBuilder 组装增强上下文。
3. 设置 `event.call_llm = True`，标记本插件接管本次 LLM。
4. 发送普通请求，不要求 JSON。
5. AstrBot 生成并发送。
6. `after_message_sent` 保存机器人消息。

### 6.2 概率 / 关键词 / 唤醒触发

1. Gate 判定候选。
2. ContextBuilder 组装增强上下文，并追加 JSON 决策协议。
3. 设置 `event.call_llm = True` 与 `ds_request_kind=decision`，禁止流式，设置 `req.func_tool` 为空 `ToolSet()`。
4. 发送决策请求。
5. AstrBot 注入知识库与第三方记忆后生成。
6. `on_llm_response` 解析 JSON：
   - `reply`：把 `resp.completion_text` 改写为真实回复文本，供其他插件记录
   - `ignore` / 解析失败 / 置信度不足：置空
7. `on_decorating_result`：
   - `reply`：用解析出的消息重建消息链
   - `ignore`：清空结果，不发送
8. `after_message_sent`：保存机器人消息；若发送成功，更新唤醒会话。

### 6.3 不触发

不构造请求，不设置 `call_llm`，由 AstrBot 保持默认行为。

### 6.4 事件标记

为避免误处理其他插件或默认管线的结果，使用事件附加标记：

- `ds_request_kind`：`normal` 或 `decision`
- `ds_decision`：解析后的决策对象（仅 decision）
- `ds_wake`：本次请求对应的唤醒会话元数据（会话 ID、限制、是否启动）

`on_llm_response` 和 `on_decorating_result` 只处理 `ds_request_kind == "decision"` 的事件；`after_message_sent` 读取 `ds_request_kind` 与 `ds_wake` 更新历史与唤醒状态。

## 7. 决策协议

请求提示词要求模型只输出：

```json
{"action":"ignore|reply","reason":"最多30字","messages":["..."],"confidence":0.0}
```

解析规则：

- `action` 仅允许 `ignore` / `reply`
- `messages` 必须是字符串列表，过滤空串，截断到配置上限
- `confidence` 必须在 0–1
- `reply` 但消息为空或置信度低于阈值 → 视为 `ignore`
- 任何解析异常 → `ignore`

直接 @ 不使用该协议。

## 8. 触发与门控

硬门控顺序：

1. 聊天已启用（群白名单/黑名单、私聊开关）
2. 临时静音
3. 空消息（仅有 @ 的消息除外）
4. 忽略的指令前缀
5. 自身消息
6. 重复 message_id
7. 同聊天 in-progress
8. 黑名单关键词
9. 冷却与每分钟上限（直接 @ 绕过）

候选触发：

- 直接 @ / 回复机器人：优先级 2
- 关键词：优先级 1
- 机器人参与后的提问：优先级 1
- 概率：优先级 0
- 唤醒会话活跃：跳过普通触发，直接进入决策

## 9. 唤醒会话

- 激活条件：决策请求发送成功且历史保存成功
- 状态键：`platform:self_id:chat_type:chat_id`
- 限制：总时长、最大消息数、空闲超时；`0` 表示不限
- 配置作用域：机器人管理员 > 群/私聊 > 全局
- 每次成功发送刷新 `last_activity_at`，不重置已消费消息数
- 达到限制后结束；旧会话的延迟发送不得重开新会话
- 状态为实例内存，重启清零

## 10. 上下文构建

- 最近历史：按配置条数从 SQLite 读取
- 图片：筛选相关上下文图片，先转述，再连同原图传给模型
- 合并转发：按需展开，限制层数、条数、字符数、超时
- 引用：默认引用与模型自主引用
- 人格：插件自行读取 AstrBot 人格并注入 system prompt
- 附加提示词：仅本次请求生效
- 环境描述：bot id、昵称、群名、私聊对象

## 11. 存储设计

SQLite 单库，建议位于插件数据目录。

表：

```sql
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  self_id TEXT NOT NULL,
  chat_type TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  message_id TEXT,
  sender_id TEXT,
  sender_name TEXT,
  timestamp REAL NOT NULL,
  components TEXT NOT NULL
);
CREATE INDEX idx_messages_chat_time
  ON messages(platform, self_id, chat_type, chat_id, timestamp);

CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

- `components` 存消息组件的 JSON 序列化，保留图片、转发、引用信息
- WAL 模式、`busy_timeout`
- 单连接 + `asyncio.Lock` + `asyncio.to_thread`，避免阻塞事件循环
- 保留策略：按天数或条数清理
- 仓储接口：追加、读取最近 N 条、清空、计数、批量导入

依赖：

- `sqlite3` 使用标准库
- `jsonpickle` 仅用于导入旧 SpectreCore 历史，导入失败不影响运行

旧数据导入：

- 源路径：`<cwd>/data/chat_history/<platform>/<group|private>/<chat_id>.json`
- 仅在数据库为空且 `meta.legacy_imported` 不存在时执行
- 使用 `jsonpickle` 解码；失败时记录并跳过该文件
- 成功后写入 `legacy_imported=1`

## 12. 配置

顶层配置：

- `enabled`、`enable_all_groups`、`enabled_groups`、`blocked_groups`、`enabled_private`
- `trigger.probability`、`trigger.keywords`、`trigger.blacklist_keywords`、`trigger.ignored_prefixes`
- `decision.max_reply_messages`、`decision.min_confidence`、`decision.timeout_ms`、`decision.max_context_messages`、`decision.cooldown_ms`、`decision.max_replies_per_minute`
- `wake.enabled`、`wake.duration_seconds`、`wake.max_messages`、`wake.idle_timeout_seconds`、`wake.private`、`wake.admin`、`wake.groups`
- `context.history_limit`、`context.image_caption.*`、`context.forward.*`
- `persona`、`extra_prompt`
- `storage.retention_days`、`storage.retention_count`

群聊唤醒覆盖使用 `template_list`，避免动态对象导致 WebUI 无法编辑。

## 13. 指令

统一前缀 `/ds`：

- `help`
- `history [n]`
- `reset [群号]`
- `mute [分钟]` / `unmute`
- `status`

## 14. 错误处理

- JSON 解析失败、超时、置信度不足 → ignore
- 知识库或第三方钩子异常 → 记录日志，继续生成
- 数据库异常 → 记录日志，降级为只用当前消息
- 图片转述失败 → 使用原图，不阻断回复
- 转发解析失败 → 使用占位符
- 钩子异常 → 捕获，不中断 AstrBot 管线

## 15. 测试

单元测试：

- 门控顺序、@ 优先、冷却绕过
- 决策解析、置信度、消息截断、异常输入
- 响应改写：reply 保留文本、ignore 置空
- 唤醒状态：激活、刷新、过期、消息上限、旧会话不重开
- SQLite 仓储：追加、读取、清空、保留清理、并发
- 旧 JSON 导入：成功、重复导入跳过、损坏文件跳过
- 配置默认值与迁移

集成测试：

- 假 event/resp 驱动 `on_llm_response` 与 `on_decorating_result`
- 验证第三方钩子看到的是真实回复而不是 JSON
- 验证直接 @ 走普通请求、概率/唤醒走决策请求

不依赖真实模型和真实 AstrBot 运行时。

## 16. 兼容与迁移

- `astrbot_version: ">=4.29,<5"`
- 自动导入旧 SpectreCore 历史一次
- 旧配置字段提供映射，减少重新配置
- 不修改 AstrBot 全局配置

### 独立重写原则

- 不复制、不搬运 SpectreCore 的源码、测试或文档。
- 只参考其公开行为、配置项语义、命令用法和用户可见效果。
- 数据层面兼容旧历史文件格式，但导入代码独立实现。
- 不复制 LivingMemory 或其他第三方插件的代码；只通过 AstrBot 通用钩子互操作。
- 所有实现与测试按本 spec 重新编写，确保 MIT 许可可用。

## 17. 文件结构

```
astrbot_plugin_dialoguesoul/
  main.py
  metadata.yaml
  _conf_schema.json
  requirements.txt
  README.md
  CHANGELOG.md
  router.py
  gate.py
  decision.py
  wake.py
  config.py
  context/
  storage/
  tests/
  docs/
```

## 18. 风险与缓解

| 风险 | 缓解 |
|---|---|
| AstrBot 内部行为变化导致请求被覆盖 | 固定最低版本；启动自检 `req.conversation` 未被设置；集成测试覆盖 |
| 插件请求未产生发送时触发默认 LLM 重复生成 | 发送请求前设置 `event.call_llm = True`，由插件独占本次 LLM |
| 核心配置仍自动添加工具 | 决策请求禁用流式并提示只输出 JSON；解析失败按 ignore |
| 第三方钩子把 JSON 当回复记录 | 高优先级 `on_llm_response` 先改写为真实文本 |
| 知识库检索增加延迟 | 设置决策超时；可用较低成本模型 |
| SQLite 并发写锁 | WAL、busy_timeout、单连接串行写 |
| 旧 JSON 导入损坏 | 单文件失败跳过并记录，不阻断启动 |
| MIT 与 AstrBot AGPL-3.0 的许可解释风险 | 本项目不复制 AstrBot 代码，仅通过公开插件 API 交互；保留 AstrBot 许可说明。若需完全规避解释风险，改用 AGPL-3.0 或进程隔离方案 |

## 19. 验收标准

1. 概率/关键词/唤醒回复能检索到 AstrBot 知识库内容。
2. 第三方 `on_llm_request` 插件注入的记忆出现在自主回复中。
3. 第三方 `on_llm_response` 插件记录的是真实回复，不是 JSON。
4. 直接 @ 走普通请求，能正常回复。
5. 决策为 ignore 时不发送任何消息。
6. 唤醒会话按配置过期，旧会话不会因延迟发送重开。
7. SQLite 历史读写、清理、旧 JSON 自动导入可用。
8. 全量测试通过，不依赖真实模型。

## 20. 鸣谢

- **SpectreCore（影芯）**：本项目的功能与使用体验参考。感谢原作者 23q3 及社区贡献者在自主回复、上下文增强、图片/转发解析、唤醒会话等方面的探索。本项目不复制其源码，按其公开行为独立重写；SpectreCore 的版权与许可归原作者。
- **AstrBot**：插件框架、消息管线、内置知识库、人格与钩子机制的基础。感谢 AstrBotDevs 及所有贡献者。
- **LivingMemory**：长期记忆插件，本项目将其作为通用钩子兼容性的验证对象之一；不包含其代码，也不与其内部实现耦合。感谢作者 lxfight。
- **AstrBot 内置知识库**：检索与注入能力由 AstrBot 提供。
- **开源依赖**：`jsonpickle`（仅用于旧历史导入）、Python 标准库 `sqlite3`、`asyncio`、`unittest`。
- **社区用户与测试者**：感谢在 SpectreCore 使用与反馈中提出问题、复现问题和验证修复的用户，这些问题直接推动了本项目的重写方向。

### 许可与署名

- 本项目采用 **MIT** 许可，仅覆盖本项目自身代码。
- 不复制 SpectreCore 或其他第三方代码；第三方依赖按其自身许可使用。
- AstrBot 自身采用 AGPL-3.0；本项目仅通过公开插件 API 与其交互，并保留其许可与来源说明。
- 若后续引入第三方代码，必须在其文件或许可声明中注明来源与许可。
- SpectreCore、AstrBot、LivingMemory 的名称与版权归各自作者所有。

