# zcode-mcp

[English](README.md) | 中文

**让任何 MCP 客户端**（Codex CLI、Claude Code、Cursor、你自己的 agent）
**像人一样操作 [ZCode](https://zcode.z.ai)**——智谱 Z.AI 的 agentic coding
应用：新建对话、多轮续聊、带文件/图片附件、轮询查看模型已输出的内容
（准实时）、中途切换模型、收割最终回复。

zcode-mcp 基于 ZCode 官方的 **app-server 协议**（桌面 App 同款通路），
桥创建的每一个对话都是真实对话：桌面端可见、可续聊、直接编辑你项目里的
真实文件。

纯 Python 标准库——唯一的可选依赖是 `cryptography`，且仅在需要查看套餐
额度时使用。

```
MCP 客户端 (Codex / Claude / 你的 agent)         ZCode 桌面端
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ 共享会话存储
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server（桥拉起）
```

## 特色

- **多轮对话** — 持有 session id 持续续聊，随时纠正方向。
- **中途可观测** — turn 运行中可轮询状态、查看模型迄今已写的内容（桥
  实时累积增量，你调用时读取）；wait 超时会标注 turn 此刻是流式输出、
  思考还是卡住。
- **交互式权限** — 非 yolo 模式可用：ZCode 请求审批时，编排方 agent 查看待
  决请求、做出决策，turn 恢复。
- **模型选择与额度** — 对话级指定任意模型（内置 / GLM Coding Plan /
  Start Plan / 自定义供应商），可中途切换；一次调用查看全部套餐额度窗口。
- **生命周期管理** — 项目级对话、一次性对话、归档/恢复、带预演保护的彻底删除。
- **原生附件** — 文件/图片走 ZCode 自己的附件管线，与桌面端拖拽同款。
- **桌面互通** — 会话存于共享存储，桌面端可列出、可续聊这里创建的一切。

## 环境要求与安装

**环境要求**

- Python ≥ 3.9（纯标准库；`cryptography` 可选，仅 `zcode_quota` 需要）
- Node.js（用 ZCode 桌面端自带的即可）
- [ZCode](https://zcode.z.ai) 桌面端 / CLI 0.16.x，已登录

**获取代码并注册到 Codex CLI**

```bash
git clone https://github.com/Six6stRINgs/zcode-mcp.git
codex mcp add zcode-mcp -- uvx --from "<路径>/zcode-mcp" zcode-mcp
```

`uvx` 会按 `pyproject.toml` 自动构建隔离环境——无需手动安装任何东西。
（发布到 PyPI 之后可简化为 `uvx zcode-mcp`；`pip install -e .` +
`zcode-mcp` 命令入口同样可用。）

**ZCode CLI 路径（`zcode.cjs`）**——桥通过 ZCode 的 CLI 入口驱动它，通常
位于 `<ZCode 安装目录>/resources/glm/zcode.cjs`。会自动扫描常见安装位置
（`%LOCALAPPDATA%/Programs/ZCode`、`C:/Program Files/ZCode` 等）。如果你的
ZCode 装在别处，把 `ZCODE_CJS` 环境变量指向它——可以设为全局，也可以只在
MCP 注册时指定：

```bash
codex mcp add zcode-mcp --env ZCODE_CJS="D:/Tools/ZCode/resources/glm/zcode.cjs" -- uvx --from "<路径>/zcode-mcp" zcode-mcp
```

Windows 下也可以在**系统环境变量**里新建 `ZCODE_CJS`，值为 `zcode.cjs`
所在目录（如 `… esources\glm`）（设置 → 系统 → 关于 → 高级系统设置 →
环境变量），不必每个 MCP 注册单独配置——桥两种来源都认。

无头 `codex exec` 在默认审批策略下会拒绝 MCP 工具调用。自动化场景请用
`--dangerously-bypass-approvals-and-sandbox`（先想清楚你的 agent 能碰到
什么）或 `--approve-for-me`；交互式 Codex 首次调用弹一次审批框即可。

**其他 MCP 客户端**（Claude Code、Cursor 等）：把同一条命令注册为 stdio
MCP server。

## 工具

按设计分为两个家族：

**独立工具** —— 不需要任何对话：

| 工具             | 作用                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------------------------- |
| `zcode_models` | 所有已配置 provider 的全部模型（内置 / Coding Plan / Start Plan / 自定义），含 reasoning 档位与上下文窗口 |
| `zcode_quota`  | 一次调用返回全部套餐额度：GLM Coding Plan 窗口 + Start Plan token 余额                                    |
| `zcode_health` | 桥 / Node.js / ZCode CLI / app-server 健康检查（不建会话）                                                |

**会话工具** —— 全部携带 `session_id`：

| 工具                          | 作用                                                      |
| ----------------------------- | --------------------------------------------------------- |
| `zcode_session_new`         | 新对话 + 首条消息；阻塞到回复完成（`wait: false` 除外） |
| `zcode_session_send`        | 后续消息（文本和/或附件）                                 |
| `zcode_session_status`      | 实时状态：当前模型、turn 状态、待决交互数、事件流水       |
| `zcode_session_output`      | 运行中 turn 模型已输出的内容（轮询式），或最近一次回复    |
| `zcode_session_result`      | 紧凑的机器可读结果：状态、回复、错误、模型                |
| `zcode_session_diff`        | 工人工作区的 git 状态 / 变更文件 / 限长 diff              |
| `zcode_session_read`        | 最近消息历史（仅限空闲会话）                              |
| `zcode_session_wait`        | 阻塞到运行中的 turn 结束，返回回复                        |
| `zcode_session_stop`        | 中断运行中的 turn                                         |
| `zcode_session_set_model`   | 切换对话模型（对下一条消息生效）                          |
| `zcode_session_permissions` | 待决的权限 / 用户输入请求                                 |
| `zcode_session_decide`      | 应答待决请求（allow/deny）——turn 立即恢复               |
| `zcode_session_archive`     | 从列表隐藏（不删除任何内容）；`unarchive: true` 恢复    |
| `zcode_session_discard`     | 永久删除（不带`confirm: true` 时仅预演）                |

### 参数

#### `zcode_session_new`

| 参数                 | 类型     | 默认值                         | 说明                                                                                                                          |
| -------------------- | -------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `text`             | string   | **必填**                 | 要发送的首条消息。                                                                                                            |
| `project`          | string   | —                             | 已存在项目目录的绝对路径；对话变为项目级，修改直接落到该仓库。优先于`cwd`。                                                 |
| `cwd`              | string   | `$ZCODE_MCP_WORKSPACE`       | 工作区目录（给了`project` 时被忽略）。                                                                                      |
| `model`            | string   | `bigmodel-api/GLM-5.3-Flash` | 选择器：`providerId/modelId`，可追加 `$reasoningLevel`。未给档位时优先 `high`。见 `zcode_models`。                    |
| `mode`             | enum     | `yolo`                       | `plan` / `build` / `edit` / `yolo` / `auto`。非 yolo 模式会因审批暂停。                                             |
| `temporary`        | boolean  | `false`                      | 一次性对话；用完配`zcode_session_discard`。                                                                                 |
| `files`            | string[] | —                             | 附件绝对路径。                                                                                                                |
| `attachments`      | object[] | —                             | 原生 ZCode 附件对象（高级透传）。                                                                                             |
| `title_generation` | boolean  | `false`                      | 让 ZCode 自动生成对话标题。                                                                                                   |
| `wait`             | boolean  | `true`                       | 阻塞到 turn 结束。                                                                                                            |
| `timeout_sec`      | integer  | `600`                        | 阻塞最长等待秒数；受`ZCODE_MCP_TOOL_BUDGET`（默认 240）约束。到点后 turn 继续运行——再次调用 `zcode_session_wait` 续等。 |

#### `zcode_session_send`

| 参数                        | 类型    | 默认值         | 说明                               |
| --------------------------- | ------- | -------------- | ---------------------------------- |
| `session_id`              | string  | **必填** | 目标对话（桥或桌面端创建的均可）。 |
| `text`                    | string  | **必填** | 后续消息文本。                     |
| `files` / `attachments` | —      | —             | 同`zcode_session_new`。          |
| `wait`                    | boolean | `true`       | 阻塞到 turn 结束。                 |
| `timeout_sec`             | integer | `600`        | 同上预算上限。                     |

#### `zcode_session_status`

| 参数           | 类型   | 默认值         | 说明       |
| -------------- | ------ | -------------- | ---------- |
| `session_id` | string | **必填** | 目标对话。 |

返回 `current_model`、`persisted_status`（桌面持久化状态，可能滞后）、
`turn_state`（实时）、turn 明细与待决交互数。

#### `zcode_session_output`

| 参数           | 类型    | 默认值         | 说明                     |
| -------------- | ------- | -------------- | ------------------------ |
| `session_id` | string  | **必填** | 目标对话。               |
| `max_chars`  | integer | `4000`       | 返回文本的尾部长度上限。 |

#### `zcode_session_result`

| 参数           | 类型   | 默认值         | 说明       |
| -------------- | ------ | -------------- | ---------- |
| `session_id` | string | **必填** | 目标对话。 |

#### `zcode_session_diff`

| 参数             | 类型    | 默认值         | 说明                                      |
| ---------------- | ------- | -------------- | ----------------------------------------- |
| `session_id`   | string  | **必填** | 目标对话（检查其工作区）。                |
| `include_diff` | boolean | `false`      | 附带限长 unified diff。                   |
| `max_chars`    | integer | `20000`      | `include_diff` 开启时的 diff 字符上限。 |

#### `zcode_session_read`

| 参数              | 类型    | 默认值         | 说明                                |
| ----------------- | ------- | -------------- | ----------------------------------- |
| `session_id`    | string  | **必填** | 目标对话（不能有正在运行的 turn）。 |
| `message_limit` | integer | `50`         | 读取最近多少条消息。                |

#### `zcode_session_wait`

| 参数            | 类型    | 默认值         | 说明                                                               |
| --------------- | ------- | -------------- | ------------------------------------------------------------------ |
| `session_id`  | string  | **必填** | 目标对话。                                                         |
| `timeout_sec` | integer | `600`        | 同上预算上限。超时说明里会注明 turn 此刻是流式输出、思考还是卡住。 |

#### `zcode_session_stop`

| 参数           | 类型   | 默认值         | 说明       |
| -------------- | ------ | -------------- | ---------- |
| `session_id` | string | **必填** | 目标对话。 |

#### `zcode_session_set_model`

| 参数           | 类型   | 默认值         | 说明                                                              |
| -------------- | ------ | -------------- | ----------------------------------------------------------------- |
| `session_id` | string | **必填** | 目标对话。                                                        |
| `model`      | string | **必填** | `providerId/modelId` 或 `providerId/modelId$reasoningLevel`。 |

#### `zcode_session_permissions`

| 参数           | 类型   | 默认值         | 说明       |
| -------------- | ------ | -------------- | ---------- |
| `session_id` | string | **必填** | 目标对话。 |

#### `zcode_session_decide`

| 参数           | 类型    | 默认值         | 说明                                                                     |
| -------------- | ------- | -------------- | ------------------------------------------------------------------------ |
| `request_id` | string  | **必填** | 待决请求 id（来自`zcode_session_permissions`）。                       |
| `session_id` | string  | —             | 提供时会与待决请求校验一致性。                                           |
| `approve`    | boolean | —             | `true`→allow，`false`→deny。                                       |
| `decision`   | enum    | —             | `allow` / `deny` / `escalate` / `modify`（优先于 `approve`）。 |
| `reason`     | string  | —             | 附带给决策的说明。                                                       |

#### `zcode_session_archive`

| 参数           | 类型    | 默认值         | 说明           |
| -------------- | ------- | -------------- | -------------- |
| `session_id` | string  | **必填** | 目标对话。     |
| `unarchive`  | boolean | `false`      | 恢复而非归档。 |

#### `zcode_session_discard`

| 参数           | 类型    | 默认值         | 说明                                                  |
| -------------- | ------- | -------------- | ----------------------------------------------------- |
| `session_id` | string  | **必填** | 目标对话。                                            |
| `confirm`    | boolean | `false`      | `false`=预演（报告行数）；`true`=不可恢复地删除。 |

#### `zcode_models` / `zcode_quota` / `zcode_health`

无参数。

## 使用模式

### 异步发射（长任务、并行工人）

```
1. zcode_session_new {text, project: "…", wait: false}   → 立刻拿到 session_id
2. zcode_session_status {session_id}                     → turn 在跑吗？事件流水？
3. zcode_session_output {session_id}                     → 模型已输出的文本
4. zcode_session_wait {session_id}                       → 收割最终回复
```

wait 超时的说明里会标注 turn 此刻的状态（`streaming` 流式输出中 /
`producing` 思考或工具运行中 / `stalled` 卡住）并附已输出内容。注意观测
是轮询式的：桥实时累积模型增量，但你在调用时才读到——没有推送。

### 模型选择与额度

```
zcode_models {}                                              → 全量模型目录
zcode_session_new {text, project: "…", model: "GLM-5.3-Flash"}
zcode_session_set_model {session_id, model: "…$reasoningLevel"}
zcode_quota {}                                               → 全部套餐窗口与余额
```

选择器规范格式：`providerId/modelId`，可追加 `$reasoningLevel`。未指定
档位时优先 `high`（模型支持的话）。不显式指定 `model` 时默认使用内置的
`bigmodel-api/GLM-5.3-Flash`（可用 `ZCODE_MCP_DEFAULT_MODEL` 覆盖）。
某个供应商凭据冷却时，切个模型继续干活。

### 生命周期：临时 / 归档 / 丢弃

```
sid = zcode_session_new {text, temporary: true}     → 一次性对话
… zcode_session_send / zcode_session_wait …
zcode_session_discard {session_id: sid}             → 预演：将删除的行数
zcode_session_discard {session_id: sid, confirm: true} → 永久删除（不可恢复）

zcode_session_archive {session_id}                  → 从列表隐藏（不删除）
zcode_session_list {include_archived: true}         → 带 [archived] 标记列出
zcode_session_archive {session_id, unarchive: true} → 恢复
```

归档/删除直接维护 ZCode 的两个共享存储（协议本身没有这类方法）：会话库
（`session.time_archived`）和桌面任务索引（`tasks.archived` /
`tasks.deleted`）。不要 discard 桌面端当前正打开的对话。

## 配置（环境变量）

| 变量                        | 默认值                                | 说明                                                                                                              |
| --------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `ZCODE_CJS`               | 自动探测                              | ZCode CLI 入口路径（`<安装目录>/resources/glm/zcode.cjs`）；未设置时自动扫描常见安装位置。                      |
| `ZCODE_MCP_WORKSPACE`     | `<仓库>/sandbox`                    | `zcode_session_new` 的默认工作区。                                                                              |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash`        | `zcode_session_new` 未指定 `model` 时使用的模型。                                                             |
| `ZCODE_MCP_TOOL_BUDGET`   | `240`                               | 单次阻塞工具调用的时间上限（秒）。Codex 等 MCP 客户端会在 ~300s 掐断 tools/call；桥在此之前返回可续等的 timeout。 |
| `ZCODE_MCP_DEBUG`         | 关                                    | 详细协议日志（`bridge.log`、`child_dump.log`）。                                                              |
| `ZCODE_MCP_NO_WARMUP`     | 关                                    | 跳过 initialize 时的 app-server 预热。                                                                            |
| `ZCODE_HOME`              | `~/.zcode`                          | ZCode 共享存储根目录。                                                                                            |
| `ZCODE_MCP_SESSION_DB`    | `$ZCODE_HOME/cli/db/db.sqlite`      | 覆盖会话库路径。                                                                                                  |
| `ZCODE_MCP_TASKS_INDEX`   | `$ZCODE_HOME/v2/tasks-index.sqlite` | 覆盖任务索引路径。                                                                                                |
| `ZCODE_MCP_CREDENTIALS`   | `$ZCODE_HOME/v2/credentials.json`   | 覆盖 OAuth 凭据存储路径（额度）。                                                                                 |
| `ZCODE_MCP_ZCODE_CONFIG`  | `$ZCODE_HOME/v2/config.json`        | 覆盖 provider 配置路径（Start Plan 余额）。                                                                       |
| `ZCODE_MCP_APP_VERSION`   | `3.14.4`                            | 套餐额度端点携带的`app_version`。                                                                               |

## 工作原理

桥拉起一个 `zcode app-server` 子进程，说 ZCode Protocol（stdio 上的换行
分隔 JSON，无握手）：`session/create` → `session/subscribe` →
`session/send`，然后等待 `turn.completed` 事件——它的载荷直接带完整回复
文本。

我们替你处理的协议地雷（全部在 ZCode 0.16.9 实测）：

- turn 运行中绝不调 `session/read`——会静默杀死运行中的 turn；
- 先 `subscribe` 再 `send`——订阅只捕获其后开始的 turn；
- `session/list` 会提前（乃至在整个模型重试窗口内）谎报 `idle`——完成判定
  只认事件；
- 服务端的反向请求（运行时偏好、插件身份头）会被应答，会话无需桌面端
  在场即可物化。

归档/删除直接操作 ZCode 的两个共享 SQLite 存储，因为协议本身没有这类
方法。

`ref/`（已 gitignore）可能保存着开源树
（[zai-org/ZCode](https://github.com/zai-org/ZCode)）的浅克隆，作为协议
开发参考，不属于发布内容。

## 已知边界

- 需要本地安装 ZCode；app-server 协议非官方承诺，版本升级可能变动
  （当前针对 0.16.9 / 桌面端 3.14.4 实测）。
- 桥创建的会话里，预置官方插件（如联网搜索）以空身份启动，该类工具可能
  不可用；模型与本地工具不受影响。
- Windows 优先（默认路径指向 Windows 版 ZCode），其余代码全平台可移植。
- 不要 discard 桌面端当前正打开的对话；对运行中会话的删除是尽力而为。
  `zcode_session_discard` 不可恢复，务必先跑预演。

## 技能（Skills）

开箱即用的技能文档在 [`skills/`](skills/)，按需拷进客户端的 skills 目录
（例如 Codex 放 `~/.codex/skills/`）：

- **[`zcode-mcp`](skills/zcode-mcp/SKILL.md)** — 总纲：工具、核心概念、
  选型指南。
- **[`zcode-subagent`](skills/zcode-subagent/SKILL.md)** — 分册：把 ZCode
  当 subagent 工人编排——派发模式、验收闭环、权限闸门、生命周期卫生。

## 许可证

MIT
