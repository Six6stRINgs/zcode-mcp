# zcode-mcp

[English](README.md) | 中文

用任何 MCP 客户端驱动 [ZCode](https://zcode.z.ai)（智谱 Z.AI 的 agentic coding 应用）：Codex CLI、Claude Code、Cursor 或你自己的 agent。桥创建的是真实 ZCode 对话，会出现在桌面 App 里；模型还在输出时就能读到部分产物；对话中途可切换模型；派出去的一次性 subagent 干完活自动清理。

Windows 优先。实测环境 ZCode 0.16.9（桌面端 3.14.4）。Python ≥ 3.9，纯标准库。MIT。

## 快速开始

需要 Python ≥ 3.9、Node.js（用 ZCode 桌面端自带的即可），以及一个已登录的 ZCode 桌面端或 CLI 0.16.x。

注册到 Codex CLI：

```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

`uvx` 会拉取仓库并在隔离环境中运行入口。要固定版本，在 git URL 后追加 `@<tag>`。其他客户端把同一条命令注册为 stdio MCP server 即可；Claude Code 对应 `claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp`。

然后从你的 agent 发出第一段对话：

```json
{"name": "zcode_session_new", "arguments": {"text": "列出这个工作区里的 Python 文件并计数"}}
```

```
session_id=sess_8b0d1110-4d8c-4071-845e-69ceba860e9f
workspace=D:\work\sandbox
共有 3 个 Python 文件：agent.py、fetch.py、report.py。
```

这个会话是真实的：它会出现在 ZCode 桌面 App 里，你可以在桌面端续聊，也可以用 `zcode_session_send` 从 agent 侧继续。

最先会碰到的两件事：

- ZCode 如果装在非默认位置，把 `ZCODE_CJS` 环境变量指向它的 `zcode.cjs` 入口（详见下文配置节）。
- 无头 `codex exec` 在默认审批策略下会拒绝 MCP 工具调用。自动化场景用 `--dangerously-bypass-approvals-and-sandbox`（先想清楚你的 agent 能碰到什么）或 `--approve-for-me`；交互式 Codex 首次调用问一次即可。

## 技能（Skills）

仓库自带三份 SKILL.md 文档，供读取该格式的客户端使用（Codex 支持）：

| 技能 | 用途 |
| --- | --- |
| `zcode-mcp` | 参考手册：全部工具、模型选择、权限流程、选型指南 |
| `zcode-subagent` | 把 ZCode 当工人的派工模式、验收循环、生命周期管理 |
| `zcode-code-reviewer` | 只读代码评审 |

Codex 的安装方式是复制进它的 skills 目录：

```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/
```

```powershell
# Windows（PowerShell）
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## 工具

18 个工具，分两组。

独立工具，不需要任何对话：

| 工具 | 用途 |
| --- | --- |
| `zcode_models` | 实时模型目录，带 provider 显示名与 reasoning 档位；同时列出会话不可用的桌面端来源 |
| `zcode_quota` | 一次调用返回全部套餐额度窗口与 Start Plan token 余额 |
| `zcode_health` | 桥、Node.js、ZCode CLI 与 app-server 健康检查 |

会话工具，全部携带 `session_id`：

| 工具 | 用途 |
| --- | --- |
| `zcode_session_new` | 新对话 + 首条消息；默认阻塞到回复完成，`wait: false` 除外 |
| `zcode_session_send` | 后续消息，可带附件 |
| `zcode_session_status` | 实时状态：当前模型、turn 状态、待决交互 |
| `zcode_session_output` | 模型迄今已输出的内容，turn 运行中可轮询 |
| `zcode_session_result` | 紧凑的机器可读结果：状态、回复、错误、模型 |
| `zcode_session_diff` | 对话工作区的 git 状态、变更文件与限长 diff |
| `zcode_session_read` | 最近消息历史（限空闲会话） |
| `zcode_session_wait` | 阻塞到运行中的 turn 结束并取回回复 |
| `zcode_session_stop` | 中断运行中的 turn |
| `zcode_session_set_model` | 切换对话模型，下一条消息生效 |
| `zcode_session_permissions` | 列出待决的权限 / 用户输入请求 |
| `zcode_session_decide` | 应答待决请求，turn 随即恢复 |
| `zcode_session_archive` | 从列表隐藏，不删除内容；`unarchive: true` 恢复 |
| `zcode_session_discard` | 永久删除，带预演保护 |

模型选择器有三种写法：裸 `modelId`（全目录唯一时可用）、`providerId/modelId`、`ProviderName/modelId`（如 `CPA/gpt-5.6-luna`），均可追加 `$reasoningLevel`（如 `GLM-5.3-Flash$high`）。未给档位时，模型支持的情况下优先 `high`。实时目录用 `zcode_models` 查看。

`session_id` 之外值得知道的参数：

- `zcode_session_new`：`project` 把对话绑定到已存在的仓库，修改直接落地；`temporary` 让对话自清理（闲置 10 分钟或桥退出时自动删除），可与 `project` 组合；`model` 和 `mode`（`plan`/`build`/`edit`/`yolo`/`auto`）选模型与权限级别；`files` 附带本地文件；`wait: false` 立即返回。所有阻塞调用受 `ZCODE_MCP_TOOL_BUDGET`（240s）约束，到点返回可续等的 timeout，用 `zcode_session_wait` 续等。
- `zcode_session_send`：后续消息的附件与等待行为同上。
- `zcode_session_decide`：接收 `zcode_session_permissions` 给出的 `request_id`，加 `approve: true/false` 或 `decision`（`allow`/`deny`/`escalate`/`modify`），可附 `reason`。
- `zcode_session_wait`：超时说明会注明 turn 此刻是流式输出、思考还是卡住。
- `zcode_session_discard`：不带 `confirm: true` 时仅预演行数。

## 配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ZCODE_CJS` | 自动探测 | ZCode CLI 入口路径（`<安装目录>/resources/glm/zcode.cjs`），未设置时扫描常见安装位置。可设全局，也可按服务注册：`codex mcp add zcode-mcp --env ZCODE_CJS="<安装目录>/resources/glm/zcode.cjs" -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp` |
| `ZCODE_MCP_WORKSPACE` | `<仓库>/sandbox` | `zcode_session_new` 的默认工作区 |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | `zcode_session_new` 未指定 `model` 时使用的模型 |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | 单次阻塞工具调用的时间上限（秒）。Codex 会在 ~300s 掐断 tools/call，桥在此之前返回可续等的 timeout |
| `ZCODE_MCP_TEMP_TTL` | `600` | `temporary` 对话闲置多少秒后自动删除。运行中的 turn 不会被回收；`0` 关闭 |
| `ZCODE_MCP_DEBUG` | 关 | 详细协议日志（`bridge.log`、`child_dump.log`） |
| `ZCODE_MCP_NO_WARMUP` | 关 | 跳过 app-server 预热 |
| `ZCODE_HOME` | `~/.zcode` | ZCode 共享存储根目录 |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | 覆盖会话库路径 |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | 覆盖任务索引路径 |
| `ZCODE_MCP_CREDENTIALS` | `$ZCODE_HOME/v2/credentials.json` | 覆盖 OAuth 凭据存储路径（额度） |
| `ZCODE_MCP_ZCODE_CONFIG` | `$ZCODE_HOME/v2/config.json` | 覆盖 provider 配置路径（Start Plan 余额） |
| `ZCODE_MCP_PROVIDER_CONFIG` | `$ZCODE_HOME/v2/provider_config.json` | 覆盖 app-server provider 注册表路径（模型显示名） |
| `ZCODE_MCP_APP_VERSION` | `3.14.4` | 套餐额度端点携带的 `app_version` |

## 工作原理

桥拉起一个 `zcode app-server` 子进程，说 ZCode Protocol：stdio 上的换行分隔 JSON，无握手。一次对话是 `session/create`、`session/subscribe`、`session/send`，回复以 `turn.completed` 事件到达。

```
MCP 客户端 (Codex / Claude / 你的 agent)         ZCode 桌面端
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ 共享会话存储
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server（桥拉起）
```

该协议是 ZCode 的内部协议，不是公开 API，有不少棱角，桥已替你处理：

- turn 运行中绝不调 `session/read`，它会静默中断 turn；
- 先 `subscribe` 再 `send`，订阅只捕获其后开始的 turn；
- `session/list` 会提前谎报 `idle`，有时贯穿整个模型重试窗口，完成判定只认事件；
- 服务端的反向请求（运行时偏好、插件身份头）会被应答，会话无需桌面端在场即可物化。

归档与删除直接操作 ZCode 的两个共享 SQLite 存储，协议本身没有这类方法。

模型身份的原理：会话通过 app-server 注册表（`~/.zcode/v2/provider_config.json`）寻址 provider。自定义 API provider 沿用配置里的 id（通常是 UUID），BigModel 族通道折叠为一个 `bigmodel-api` provider，显示名即该条目的名字。桌面账号型来源（BigModel 个人、Start Plan、Z.ai）靠桌面登录支撑，不会进入该注册表；`zcode_models` 会列出它们供参考，选择时返回指路说明。

## 已知边界

- **桌面账号型额度无法经 MCP 消费。** Start Plan、BigModel 个人、Z.ai 的模型不会进入无头会话可寻址的注册表，其额度只能在桌面 App 自己的对话里消耗，与剩余额度无关。纯 API key 的 provider 不同：在 ZCode 里配成自定义 provider 后即可在 MCP 中正常使用。
- 需要本地安装 ZCode。app-server 协议非公开 API，版本升级可能变动（实测 0.16.9 / 桌面端 3.14.4）。
- Windows 优先：默认路径按 Windows 版 ZCode 假设，其余代码全平台可移植。
- 桥创建的会话里，预置官方插件（联网搜索等）以空身份启动，模型与本地工具不受影响。
- 不要 discard 桌面端当前打开的对话；对运行中会话的删除是尽力而为。`zcode_session_discard` 不可恢复，先跑预演。

## 许可证

MIT
