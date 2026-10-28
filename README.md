# 言灵（DialoguesSoul）

[![version](https://img.shields.io/badge/version-v1.3.0-blue.svg?style=flat-square)](https://github.com/SunflowerYuuka/astrbot_plugin_dialoguesoul)
[![license](https://img.shields.io/badge/license-AGPL--3.0-blue.svg?style=flat-square)](LICENSE)

言灵（DialoguesSoul）是让大模型真正参与群聊的 AstrBot 插件。它负责触发判断、上下文组装、决策解析与唤醒会话；生成、知识库、第三方长期记忆和发送都交给 AstrBot 管线。

> **AI 制作声明**：本项目由 AI 制作，代码与文档可能存在错误，请自行审查后使用。
>
> **图标说明**：插件图标由即梦AI生成。

## 功能特性

- **自主参与**：模型根据最近的聊天上下文决定是否接话，而不是只等待被 @。
- **多种触发方式**：直接 @ / 回复机器人、关键词、问句、概率回复以及可选的时间窗口采样。
- **四种触发策略**：`every_message`、`rules`、`window`、`interest`，默认使用 30 秒窗口的 `window`。
- **两种决策格式**：自然文本的 `marker`（默认）与结构化的 `json`，可按场景切换。
- **唤醒会话**：一次成功接话后可在一段时间内持续参与，支持总时长、空闲超时与最多成功回复次数 `max_replies`。
- **SQLite 最近历史**：按聊天隔离保存上下文，支持保留天数、保留条数与旧 SpectreCore JSON 历史的一次性导入。
- **可选上下文增强**：图片转述、合并转发解析与模型摘要，默认关闭，按需开启。
- **AstrBot 原生兼容**：使用 AstrBot 内置知识库，并与通用的 `on_llm_request` / `on_llm_response` 插件协同，包括 LivingMemory。
- **管理指令**：通过 `/ds` 查看历史、重置、临时静音和查看状态。

## 工作原理

```text
消息事件
  → 硬门控（聊天开关、静音、自身消息、重复消息、黑名单、冷却等）
  → 触发策略（every_message / rules / window / interest）
  → 主动回复等待并组装最近历史、人格、环境、图片/转发/摘要
  → 开启附加提示词时，先判断是否介入
  → 发送普通请求、决策请求或主动回复请求到 AstrBot
  → AstrBot：内置知识库 + on_llm_request 等通用钩子 + 模型生成
  → 解析决策或主动回复格式，必要时清空结果
  → 发送后写入最近历史并更新唤醒会话
```

直接 @ 或回复机器人通常会绕过冷却与每分钟上限，使用普通请求；自主回复与唤醒接话默认使用决策请求。开启 `extra_prompt.enabled` 后，主动触发和唤醒会先根据附加提示词判断是否介入，通过后用普通对话生成；直接 @ 和 AstrBot/其他系统自带的对话调用不经过该判断。唤醒会话活跃时，通过硬门控的消息（包括 @）优先进入唤醒流程。插件不保存长期记忆，只保存组装上下文所需的最近聊天历史。

## 安装与启用

1. 确保 AstrBot 版本满足 `>=4.29,<5`。
2. 将插件目录放入 AstrBot 的插件目录，或在 WebUI 中安装。
3. 安装依赖：`jsonpickle>=3.0.0`（仅用于导入旧历史；AstrBot 通常会按 `requirements.txt` 自动安装）。
4. 在 WebUI 中启用 DialoguesSoul，并配置需要回复的群聊或私聊。
5. 重启 AstrBot，使用 `/ds help` 检查指令是否可用。

首次启动时，如果 SQLite 历史为空，插件会尝试从 `data/chat_history/<platform>/<group|private>/<chat_id>.json` 导入旧 SpectreCore 历史；导入只执行一次，失败的文件会记录日志并跳过，不影响正常启动。

## 配置概览

| 配置段 | 主要作用 |
|---|---|
| `enabled` / `enable_all_groups` / `enabled_groups` / `blocked_groups` / `enabled_private` | 总开关与聊天范围。 |
| `trigger` | 触发策略、主动回复等待、窗口、概率、关键词、黑名单、忽略前缀与刷屏保护。 |
| `decision` | 决策格式、最大回复条数、最低置信度、决策上下文条数、冷却与每分钟上限。 |
| `wake` | 唤醒会话开关与限制，以及私聊、管理员和指定群覆盖。 |
| `context` | 最近历史、图片转述、合并转发与上下文摘要。 |
| `persona` / `extra_prompt` | 人格注入与附加提示词。 |
| `storage` | SQLite 路径与历史保留策略。 |

## 触发策略

在 `trigger.strategy` 中选择：

| 策略 | 行为 |
|---|---|
| `every_message` | 通过硬门控后，每条消息都进入决策。 |
| `rules` | 关键词、问句或概率命中后进入决策。 |
| `window` | 距上次判断超过 `trigger.window_seconds` 才进入决策，默认 30 秒；窗口内消息只入库、不判断。 |
| `interest` | 先用轻量判断模型输出 `YES` / `NO`，只有 `YES` 才进入决策。关闭 `trigger.interest.enabled` 时退化为 `window`；开启附加提示词时，判断依据改用附加提示词。 |

补充行为：

- 直接 @ / 回复机器人以及私聊消息优先级高于触发策略，走普通请求；唤醒会话活跃时则进入唤醒流程。
- 私聊不套用主动回复等待和“默认忽略”的决策协议，立即以普通请求回复。
- `trigger.proactive_delay_seconds` 控制主动回复的等待时间，默认 5 秒。群聊中非直接 @ 的触发命中后固定等待该时间再调用模型，等待期间的新消息只入库，结束后连同上下文、触发消息图片和等待窗口内图片一起送入模型；直接 @ 不等待，并会打断正在等待的主动回复，`0` 表示关闭等待。
- 开启附加提示词后，主动触发和唤醒在等待结束后先判断是否介入；判断为 `NO` 时跳过主模型，不消耗唤醒次数。
- 唤醒会话活跃时，通过硬门控的消息进入唤醒流程，不受窗口或兴趣策略限制；非直接 @ 的消息同样先经过附加提示词判断，刷屏保护期间暂停。
- `trigger.burst` 可对指定群启用刷屏保护：30 秒内消息达到阈值后暂停自主采样与唤醒采样，安静 `cooldown_seconds` 后恢复；直接 @ 仍可触发。`threshold` 与 `cooldown_seconds` 是全局配置，对所有启用了刷屏保护的群生效。
- `trigger.ignored_prefixes` 默认忽略 `/`，避免 `/ds help` 等指令消息额外触发一次模型回复；判断时使用去掉 At/回复段后的文本，所以 `@机器人 /ds help` 也会被忽略。自定义 AstrBot 唤醒前缀时请同步加入。
- `trigger.probability` 与 `trigger.keywords` 仅在 `rules` 策略下参与触发判定；`trigger.blacklist_keywords`、`trigger.ignored_prefixes` 对所有策略生效。

## 决策格式

在 `decision.format` 中选择。

### marker（默认）

模型正常输出自然语言；不想接话时输出 `<NO_RESPONSE>`。空文本或包含该标记时视为忽略，否则将文本作为一条消息发送。

```text
<NO_RESPONSE>
```

### json

要求模型只输出严格 JSON（允许被 Markdown 代码围栏包裹）：

```json
{
  "action": "reply",
  "reason": "补充信息",
  "quote": 3,
  "messages": ["这条消息", "还有这条"],
  "confidence": 0.8
}
```

- `action` 只能是 `ignore` 或 `reply`。
- `messages` 为字符串列表，空串会被过滤，并按 `decision.max_reply_messages` 截断。
- `confidence` 必须在 0 到 1 之间；`reply` 但置信度低于 `decision.min_confidence` 时视为忽略。
- `quote` 可选，为本次上下文中历史消息的编号；无效编号会被忽略。
- 任何解析失败都按忽略处理，不发送消息。

普通请求（通常是直接 @ / 回复机器人）不使用决策协议。开启附加提示词后，主动触发和唤醒通过判断后使用普通回复格式；`decision.format=json` 时主模型只输出 `{"messages":[...],"quote":可选编号}`，保留多消息与引用能力。唤醒会话活跃时的 @ 消息仍按决策请求处理。

## 唤醒会话

开启 `wake.enabled` 后，一次进入发送阶段的决策回复（私聊中普通回复也可以）会启动唤醒会话。会话期间通过硬门控的消息会先等待，再按附加提示词判断是否介入；开启附加提示词时判断为 `NO` 不生成回复，直到达到限制：

- `wake.duration_seconds`：总时长，`0` 表示不限。
- `wake.idle_timeout_seconds`：空闲超时，`0` 表示不限。
- `wake.max_replies`：最多回复次数，默认 `5`，`0` 表示不限。模型忽略、决策失败不消耗次数。aiocqhttp 下按 `_has_send_oper` 判断实际发送成功后才计数；其他适配器没有可靠失败标志时保持 best-effort。
- `wake.final_reply_prompt`：可选收尾提示词。`max_replies > 0` 且本次是唤醒会话最后一条回复时，以 `[唤醒收尾提示]` 注入 system prompt，让模型自然收尾；留空则不注入。
- 达到任意限制后会话结束；旧的延迟发送不会重新开启已结束的会话。
- `wake.private`、`wake.admin`、`wake.groups` 可分别覆盖私聊、管理员和指定群的限制，管理员优先级最高。私聊默认值与全局一致；群覆盖中留空表示继承全局，通过 `template_list` 配置。

唤醒会话状态保存在进程内存中，重启后清零。

## 上下文与存储

- `context.history_limit`：普通请求读取的最近历史条数，默认 20。
- `decision.max_context_messages`：决策请求读取的最近历史条数，默认 20。当前触发消息本身会作为 prompt 发送，因此会从历史中排除，避免重复。
- `context.image_caption`：可选的图片转述。开启后，决策请求会先调用指定或当前 provider 生成图片描述，并把描述与原始图片一起交给模型；支持并发限制与进程内 LRU 缓存。
- `context.forward.parse`：可选的合并转发解析。开启后通过 OneBot `get_forward_msg` 读取当前消息中的合并转发，兼容 `data.text` 结构与嵌套节点，按 `max_depth`、`max_nodes`、`max_chars`、`timeout` 限制展开；失败或空内容时使用占位文本并写入警告日志。
- `context.summary`：可选的上下文摘要。历史条数达到 `threshold`（默认 20）时调用指定或当前 provider 生成摘要，失败时回退到原始历史。`threshold` 需不大于实际读取的历史条数（`decision.max_context_messages` 或 `context.history_limit`），否则摘要不会触发。
- `decision.aux_timeout_seconds`：兴趣判断、介入判断、图片转述与摘要等辅助模型调用的超时，默认 15 秒；超时按未通过或回退处理，避免长时间占住该聊天，`0` 表示不限。
- `persona`：从 AstrBot 读取并注入人格；`persona.name` 指定人格名称，留空或找不到时使用默认人格。
- `extra_prompt`：开启后既作为主动触发/唤醒的介入判断依据，也注入主模型；`extra_prompt.provider_id` 指定判断模型，留空使用当前 provider。关闭时保持原有决策流程。
- `storage.db_path`：SQLite 路径，留空时使用插件数据目录下的 `dialoguesoul.sqlite3`。
- `storage.retention_days` / `storage.retention_count`：按时间或每个聊天的条数清理最近历史，`0` 表示不限。

SQLite 单库按 `platform:self_id:chat_type:chat_id` 隔离会话，保存消息组件（文本、图片、转发、引用等）的 JSON 表示，并使用 WAL 与串行写避免并发冲突。

## 兼容性

- **AstrBot 内置知识库**：请求通过 `event.request_llm(...)` 进入 AstrBot 管线，知识库检索与注入仍由 AstrBot 完成。
- **通用第三方钩子**：插件不识别具体第三方插件，也不调用其内部 API；只依赖 `on_llm_request` / `on_llm_response` 等通用钩子。LivingMemory 是兼容性验证目标之一。
- **长期记忆**：插件自身不建立长期记忆库，长期记忆由 AstrBot 或第三方插件负责。
- **发送能力**：流式、分段、引用和发送后处理由 AstrBot 负责。

## 指令

| 指令 | 说明 | 权限 |
|---|---|---|
| `/ds help` | 查看指令列表。 | 所有人 |
| `/ds history [n]` | 查看当前聊天最近 `n` 条历史，范围 1–20。 | 管理员 |
| `/ds reset [群号]` | 清空当前聊天历史，并结束该聊天的唤醒会话与等待中的回复；在群聊中可指定群号。 | 管理员 |
| `/ds mute [分钟]` | 临时静音当前聊天，默认 5 分钟，范围 1–10080；静音只保存在内存中，重启后失效。 | 管理员 |
| `/ds unmute` | 取消当前聊天的临时静音。 | 管理员 |
| `/ds status` | 查看启用状态、触发策略、唤醒会话与当前聊天的静音/唤醒状态。 | 所有人 |

## 许可

本项目采用 **AGPL-3.0**，与 AstrBot 的许可证保持一致。完整条款见 [LICENSE](LICENSE)。

本项目是独立重写：不复制 SpectreCore 或其他第三方插件的源码、测试或文档，只参考其公开行为、配置语义和使用体验。第三方依赖按各自许可证使用。

## 鸣谢

- **SpectreCore（影芯）**：本项目的功能与使用体验参考。感谢原作者 23q3 及社区贡献者在自主回复、上下文增强、图片/转发解析、唤醒会话等方面的探索。SpectreCore 的版权与许可归原作者。
- **AstrBot**：插件框架、消息管线、内置知识库、人格与钩子机制的基础。感谢 AstrBotDevs 及所有贡献者。
- **LivingMemory**：长期记忆插件，本项目将其作为通用钩子兼容性的验证对象之一；不包含其代码，也不与其内部实现耦合。感谢作者 lxfight。
- **AstrBot 内置知识库**：检索与注入能力由 AstrBot 提供。
- **开源依赖**：`jsonpickle`（仅用于旧历史导入），以及 Python 标准库 `sqlite3`、`asyncio`、`unittest`。
- **社区用户与测试者**：感谢在 SpectreCore 使用与反馈中提出问题、复现问题和验证修复的用户，这些问题直接推动了本项目的重写方向。
