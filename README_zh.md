**zcode-mcp** — 通往 ZCode 桌面端对话的 MCP 网关。

[English](README.md) | 中文

---

**让任何 MCP 客户端**（Codex CLI、Claude Code、Cursor、你自己的 agent）
**像人一样操作 [ZCode](https://zcode.z.ai)**——智谱 Z.AI 的 agentic coding
应用：新建对话、带文件/图片附件续聊、**实时查看模型流式输出**、收割最终
回复。基于 ZCode 官方 **app-server 协议**（桌面 App 同款通路），桥创建的
会话是正式对话，桌面端可见、可续聊。

纯 Python 标准库，零运行时依赖。

```
MCP 客户端 (Codex / Claude / 你的 agent)         ZCode 桌面端
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ 共享会话存储
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server（桥拉起）
```

## 特色

- **多轮对话** — 持有 session id 持续续聊，随时纠正方向。
- **中途可观测** — turn 运行中轮询 `zcode_session_status` / `zcode_session_output`，看模型
  文本边写边流出；指挥方 agent 不必盲等，可以基于中间输出做判断。
- **可中断** — `zcode_session_stop` 随时叫停运行中的 turn。
- **原生附件** — 文件/图片走 ZCode 自己的附件管线，与桌面端拖拽同款。
- **生命周期管理** — 临时（一次性）对话、归档/恢复、彻底删除。
- **桌面互通** — 会话存于共享存储，桌面端可列出、可续聊。
- **异步发射** — `wait: false` 立即返回，之后用 `zcode_session_wait` 收割，
  避开 MCP 客户端的单工具超时。
- **交互式权限** — 非 yolo 模式可用：turn 因待审批暂停时，编排方 agent
  通过 `zcode_session_permissions` 查看待决请求、`zcode_session_decide` 做决策，turn 恢复。
- **模型选择与额度** — 对话级指定任意模型（内置 / Coding Plan / Start
  Plan 供应商），可中途切换并带 reasoning 档位（未指定时优先 `high`）；
  `zcode_quota` 随时查看套餐额度窗口，长任务前先看余量。

## 环境要求与安装

**环境要求**

- Python ≥ 3.9（纯标准库）
- Node.js（用 ZCode 桌面端自带的即可）
- [ZCode](https://zcode.z.ai) 桌面端 / CLI 0.16.x，已登录
- 可选：`cryptography`——仅 `zcode_quota` 需要（用本地 ZCode OAuth 凭据读套餐额度）

**获取代码并注册到 Codex CLI**

```bash
git clone https://github.com/Six6stRINgs/zcode-mcp.git

# 直接从克隆目录运行（uv 自动构建隔离环境）
codex mcp add zcode-mcp -- uvx --from "<路径>/zcode-mcp" zcode-mcp

# 发布到 PyPI 之后：
codex mcp add zcode-mcp -- uvx zcode-mcp

# 或者不克隆，直接从 git 仓库运行：
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

无需手动安装任何依赖——`uvx` 会根据 `pyproject.toml` 自动构建隔离环境。
（`pip install -e .` + `zcode-mcp` 命令入口同样可用。）

无头 `codex exec` 的审批策略是 never，会直接拒绝 MCP 工具调用；自动化
场景加 `--dangerously-bypass-approvals-and-sandbox`（先想清楚你的 agent
能碰到什么）或 `--approve-for-me`。交互式 Codex 首次调用弹一次审批框即可。

**其他 MCP 客户端**（Claude Code、Cursor 等）：把同一条命令注册为 stdio
MCP server。

可选 `pip install -e .` 提供 `zcode-mcp` 命令入口。

## 工具列表

| 工具 | 作用 |
|---|---|
| `zcode_session_new` | 新建对话并发送首条消息，默认阻塞到回复完成（`wait: false` 异步发射）。默认使用内置 `GLM-5.3-Flash` 模型；`project: <目录>` 挂到真实项目（项目级对话）；`temporary: true` 创建一次性对话 |
| `zcode_session_send` | 向既有对话（含桌面端创建的）发后续消息，支持 `files` 文件/图片附件 |
| `zcode_session_status` | 当前状态：desktop 状态、turn 生命周期、带时间戳的事件流水 |
| `zcode_session_output` | 模型**当前正在流式输出的文本**，或最近一次完成的回复 |
| `zcode_session_read` | 读取最近消息历史（角色 + 文本） |
| `zcode_session_wait` | 阻塞等待运行中的 turn 结束，返回回复 |
| `zcode_session_stop` | 中断运行中的 turn |
| `zcode_models` | **所有** provider 的**所有**模型（内置 + Coding Plan / Start Plan + 自定义）含 reasoning 档位，及会话当前选择——不受 set_model 收窄影响 |
| `zcode_session_set_model` | 切换对话模型（对下一条消息生效） |
| `zcode_quota` | GLM Coding Plan / Start Plan 额度：分窗口用量、余量、下次重置 |
| `zcode_session_list` | 列出所有工作区的对话；归档的默认隐藏，`include_archived: true` 可见 |
| `zcode_session_archive` | 归档对话（列表隐藏，不删除任何内容）；`unarchive: true` 恢复 |
| `zcode_session_discard` | **永久删除**对话（会话 + 全部历史）；不带 `confirm: true` 时仅预演并报告行数 |
| `zcode_session_permissions` | 列出暂停中对话的待决权限/用户输入请求（非 yolo 模式） |
| `zcode_session_decide` | 应答待决请求（allow/deny）——turn 立即恢复 |

### 参数

#### `zcode_session_new`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text` | string | **必填** | 要发送的消息文本。 |
| `project` | string | — | **已存在**的项目目录绝对路径；创建项目级对话（桌面端归到该项目下）。优先于 `cwd`。 |
| `cwd` | string | `$ZCODE_MCP_WORKSPACE` | 对话的工作区目录（给了 `project` 时被忽略）。 |
| `mode` | enum | `yolo` | `plan` / `build` / `edit` / `yolo` / `auto`——权限模式。非 yolo 模式会因审批暂停（见 `zcode_session_permissions`）。 |
| `temporary` | boolean | `false` | 一次性对话（deferred 持久化）；用完配 `zcode_session_discard`。 |
| `files` | string[] | — | 附件绝对路径；类型（image/pdf/audio/video/file）按扩展名推断。 |
| `attachments` | object[] | — | 原生 ZCode 附件对象（高级透传）。 |
| `title_generation` | boolean | `false` | 让 ZCode 自动生成对话标题。 |
| `wait` | boolean | `true` | 阻塞到 turn 结束；`false` 立即返回 `session_id`。 |
| `timeout_sec` | integer | `600` | 阻塞时的最长等待秒数（受 `ZCODE_MCP_TOOL_BUDGET` 上限约束，默认 240——超时后 turn 继续运行，再次 `zcode_session_wait` 续等）。 |

#### `zcode_session_send`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话（桥或桌面端创建的均可）。 |
| `text` | string | **必填** | 后续消息文本。 |
| `files` / `attachments` | — | — | 同 `zcode_session_new`。 |
| `mode` | enum | — | 不可在此设置；沿用会话自身的模式。 |
| `wait` | boolean | `true` | 阻塞到 turn 结束。 |
| `timeout_sec` | integer | `600` | 阻塞时的最长等待秒数（同样受预算上限约束）。 |

#### `zcode_session_list`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `include_archived` | boolean | `false` | 同时列出已归档对话（带 `[archived]` 标记）。 |

#### `zcode_session_status` / `zcode_session_permissions`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |

#### `zcode_session_output`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |
| `max_chars` | integer | `4000` | 返回文本的尾部长度上限。 |

#### `zcode_session_result`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |

返回适合 orchestrator 使用的紧凑 JSON：turn 状态、最终回复、错误、待处理交互、工作区、模式和当前模型。

#### `zcode_session_diff`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 要检查工作区的目标对话。 |
| `include_diff` | boolean | `false` | 是否包含有界 unified diff。 |
| `max_chars` | integer | `20000` | `include_diff=true` 时的最大 diff 字符数。 |

返回 session 工作区的 Git 状态、改动文件和 diff 摘要。

#### `zcode_health`

无参数。无需创建对话，即可检查 bridge、Node.js、ZCode CLI、app-server 和模型目录状态。

#### `zcode_session_decide`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `request_id` | string | **必填** | 待决请求 id（来自 `zcode_session_permissions`）。 |
| `session_id` | string | — | 提供时会与待决请求校验一致性。 |
| `approve` | boolean | — | 简写：`true`→`allow`，`false`→`deny`。 |
| `decision` | enum | — | `allow` / `deny` / `escalate` / `modify`（优先于 `approve`）。 |
| `reason` | string | — | 附带给决策的说明。 |

#### `zcode_session_read`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话（不能有正在运行的 turn）。 |
| `message_limit` | integer | `50` | 读取最近多少条消息。 |

#### `zcode_session_wait`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |
| `timeout_sec` | integer | `600` | 等待运行中 turn 的最长秒数（同样受预算上限；再次调用 `zcode_session_wait` 续等）。 |

#### `zcode_session_archive`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |
| `unarchive` | boolean | `false` | `true` 为恢复而非归档。 |

#### `zcode_session_discard`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |
| `confirm` | boolean | `false` | `false`=预演（报告行数）；`true`=不可恢复地删除。 |

#### `zcode_session_stop`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 要中断其运行中 turn 的目标对话。 |

#### `zcode_models`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | — | 读取该会话的列表；省略时用最近一次 `zcode_session_new` 缓存的目录。 |

#### `zcode_session_set_model`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session_id` | string | **必填** | 目标对话。 |
| `model` | string | **必填** | `modelId` / `providerId/modelId` / `providerId/modelId$reasoningLevel`。未给档位时优先套 `high`（模型不支持时用其自带默认档）。 |

#### `zcode_quota`

无参数。用本地 ZCode OAuth 凭据（进程内解密，绝不落日志）读取 GLM
Coding Plan / Start Plan 的限额端点。需要可选依赖：
`pip install "zcode-mcp[quota]"`。

### 观测模式（A2A 编排的核心用法）

```
1. zcode_session_new {text, wait: false}   → 立刻拿到 session_id（异步发射）
2. zcode_session_status {session_id}       → turn 是否在跑、事件流水
3. zcode_session_output {session_id}       → 模型当前已流出的文本（边写边看）
4. zcode_session_wait  {session_id}        → 收割最终回复
```

指挥方 agent 中途发现方向不对可以 `zcode_session_stop` 及时止损，或者提前基于
部分输出做判断。

### 模型选择与额度

```
zcode_models {}                                        → 全量模型目录（所有 provider）
zcode_session_new    {text, model: "GLM-5.3-Flash"}             → 指定模型开对话
zcode_session_set_model {session_id, model: "…$reasoningLevel"} → 中途切换模型
zcode_quota {}                                          → 套餐窗口、余量、重置时间
```

选择器规范格式：`providerId/modelId`，可追加 `$reasoningLevel`；裸
`modelId` 在全目录唯一时也可用。未指定档位时优先 `high`（模型支持的话）。
不显式指定 `model` 时，`zcode_session_new` 默认使用内置的
`bigmodel-api/GLM-5.3-Flash`（可用 `ZCODE_MCP_DEFAULT_MODEL` 覆盖）。某个供应商凭据冷却时，切个模型
继续干活。

### 技能（Skills）

开箱即用的技能文档在 [`skills/`](skills/)，按需拷进客户端的 skills 目录
（例如 Codex 放 `~/.codex/skills/`）：

- **[`zcode-mcp`](skills/zcode-mcp/SKILL.md)** — 总纲：工具全集、核心概念
  （会话生命周期、项目/临时对话、可观测性）、选型指南。
- **[`zcode-subagent`](skills/zcode-subagent/SKILL.md)** — 分册：把 ZCode
  当 subagent 工人编排——派发模式、验收闭环、按项目分配工人、生命周期卫生。

### 生命周期：临时 / 归档 / 丢弃

```
# 一次性问答，用完即走，不留痕迹
sid = zcode_session_new {text, temporary: true}    → 临时对话
… 正常 zcode_session_send / zcode_session_wait …
zcode_session_discard {session_id: sid}            → 预演：列出将删除的行数
zcode_session_discard {session_id: sid, confirm: true} → 永久删除（不可恢复）

# 保留历史但从列表隐藏
zcode_session_archive {session_id}                 → 归档（zcode_session_list 与桌面侧栏均隐藏）
zcode_session_list {include_archived: true}        → 带 [archived] 标记列出
zcode_session_archive {session_id, unarchive: true}→ 恢复
```

实现说明：ZCode 协议本身没有归档/删除方法，zcode-mcp 直接维护两个共享
存储——会话库（`~/.zcode/cli/db/db.sqlite` 的 `session.time_archived`，
运行时下次启动起从 `session/list` 隐藏）和桌面任务索引
（`~/.zcode/v2/tasks-index.sqlite` 的 `tasks.archived` / `tasks.deleted`）。
`discard` 在单事务内按精确 session id 删行，删除前会尽力 stop/close；
不要 discard 桌面端当前正打开的对话。归档对 `zcode_session_list` 立即生效
（桥自己过滤）。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ZCODE_CJS` | 自动探测 | 显式指定 ZCode CLI 入口（`<安装目录>/resources/glm/zcode.cjs`）；未设置时自动扫描常见安装位置，找不到会报错并列出已搜索的路径 |
| `ZCODE_MCP_WORKSPACE` | `<仓库>/sandbox` | `zcode_session_new` 的默认工作区 |
| `ZCODE_MCP_DEBUG` | 关 | 详细协议日志（`bridge.log`、`child_dump.log`） |
| `ZCODE_MCP_NO_WARMUP` | 关 | 跳过 initialize 时的 app-server 预热 |
| `ZCODE_MCP_DEFAULT_MODEL` | `GLM-5.3-Flash` | `zcode_session_new` 未指定 `model` 时使用的模型（ZCode 内置 Coding Plan 模型） |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | 单次阻塞工具调用的时间上限（秒）。Codex 等 MCP 客户端会在 ~300s 掐断 tools/call；桥在此之前返回可续等的 `timeout` 状态，turn 继续运行——再次调用 `zcode_session_wait` 即可继续收割 |
| `ZCODE_HOME` | `~/.zcode` | ZCode 共享存储根目录（归档/删除用） |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | 覆盖会话库路径 |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | 覆盖任务索引路径 |

## 工作原理

桥拉起一个 `zcode app-server` 子进程，说 ZCode Protocol（stdio 上的换行
分隔 JSON，无握手）：

- `session/create` → `session/subscribe` → `session/send`，然后等待
  `turn.completed` 事件——它的载荷直接带完整回复文本。
- 每条 `session/event` 通知喂进每会话的环形缓冲（`SessionMonitor`），
  持续累积 `model.streaming` 的文本增量——这就是 `zcode_session_output` 的数据源，
  其他工具调用并发时也能查。
- 服务端的反向请求会被应答：运行时偏好（三个布尔）和官方 MCP 身份头
  （空身份，让预置 image-search 插件在无桌面凭据时也能物化）。

我们替你处理的协议地雷（0.16.9 实测，详见
`src/zcode_mcp/appserver.py` 模块文档）：

- turn 运行中绝不调 `session/read`（会静默杀死运行中的 turn）；
- 先 `subscribe` 再 `send`（订阅只捕获其后开始的 turn）；
- `session/list.status` 会提前变 `idle`——完成判定只能靠事件。

`ref/ZCode` 存有开源仓库（[zai-org/ZCode](https://github.com/zai-org/ZCode)）
的浅克隆，作为协议开发参考，不属于发布内容（已 gitignore）。

## 已知边界

- 需要本地安装 ZCode；app-server 协议非官方承诺，版本升级可能变动
  （当前针对 0.16.9 实测）。
- 桥创建的会话里，预置官方插件（如联网搜索）以空身份启动，该类工具可能
  不可用；模型与本地工具不受影响。
- Windows 优先（默认路径指向 Windows 版 ZCode），其余代码全平台可移植。
- 归档/删除是直接操作共享存储（上游无协议支持）。不要删除桌面端当前
  正打开的对话；对运行中会话的删除是尽力而为。`zcode_session_discard` 不可恢复，
  务必先跑预演。

## 许可证

MIT
