# zcode-mcp

[English](README.md) | 中文

ZCode 是个跑 agent 的好地方，但你的主力 agent 多半住在 Codex 或 Claude Code 里。zcode-mcp 用 MCP 把两边接起来：你的 agent 直接开 ZCode 对话、派活、盯着模型写、把结果拿回来。这些对话在 ZCode 桌面端里和普通对话没有任何区别，可以随时接着聊——不是藏在角落里的影子会话。

桥走的是 ZCode 自带的 app-server 协议（桌面 App 同一条通道），协议里的坑它都已经替你踩过了；派出去的一次性 subagent，干完活会自己收拾干净。

Windows 优先。实测环境 ZCode 0.16.9（桌面端 3.14.4）。Python ≥ 3.9，纯标准库。MIT。

## 快速开始

需要 Python ≥ 3.9、Node.js（ZCode 桌面端自带那个就行）、一个已登录的 ZCode 桌面端或 CLI 0.16.x。

在 Codex 里注册：

```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

uvx 会自己拉仓库、建隔离环境、跑起来，不需要手动装任何东西。想固定版本就在 git URL 后面加 `@<tag>`。Claude Code 和其他 MCP 客户端拿同一条命令注册成 stdio server 即可（`claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp`）。

然后给你的 agent 派第一件活：

```json
{"name": "zcode_session_new", "arguments": {"text": "列出这个工作区里的 Python 文件并计数"}}
```

```
session_id=sess_8b0d1110-4d8c-4071-845e-69ceba860e9f
workspace=D:\work\sandbox
共有 3 个 Python 文件：agent.py、fetch.py、report.py。
```

打开 ZCode 桌面端看一眼：对话就在那里，两边都能接着聊。

第一天最容易撞上的两件事：

- ZCode 装在非默认位置？把 `ZCODE_CJS` 指向它的 `zcode.cjs` 入口（见下文配置）。
- 无头 `codex exec` 默认审批策略会拒掉 MCP 调用。自动化场景用 `--dangerously-bypass-approvals-and-sandbox`（先想清楚你的 agent 能碰什么）或 `--approve-for-me`；交互式 Codex 问一次就放行。

## 技能（Skills）

给 18 个工具各写一遍正确的调用方式，是 agent 该干的活，不是你的。仓库自带三份 SKILL.md，agent 读完就会用（Codex 支持，其他认 SKILL.md 的客户端同样适用）：

| 技能 | agent 能学会什么 |
| --- | --- |
| `zcode-mcp` | 全套手册：每个工具、模型选择、权限流程、什么场景用什么 |
| `zcode-subagent` | 把 ZCode 当工人派活：派工模式、验收循环、收拾残局 |
| `zcode-code-reviewer` | 只读代码评审 |

装进 Codex：

```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/
```

```powershell
# Windows（PowerShell）
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## 工具

18 个工具：3 个独立使用，其余每个都围着一段对话转。

独立工具：

| 工具 | 干什么 |
| --- | --- |
| `zcode_models` | 实时模型目录，带 provider 显示名和 reasoning 档位——顺带列出会话碰不到的桌面端来源 |
| `zcode_quota` | 一次调用拿回所有套餐额度窗口和 Start Plan token 余额 |
| `zcode_health` | 桥、Node.js、ZCode CLI、app-server 各自活没活着 |

会话工具，全部要传 `session_id`：

| 工具 | 干什么 |
| --- | --- |
| `zcode_session_new` | 开对话、发首条消息；默认等回复回来，`wait: false` 除外 |
| `zcode_session_send` | 续聊，可带附件 |
| `zcode_session_status` | 对话此刻在干嘛：当前模型、turn 状态、等谁审批 |
| `zcode_session_output` | 模型已经写到哪了，turn 跑着的时候轮询看 |
| `zcode_session_result` | 最终结果打包成一份：状态、回复、错误、模型 |
| `zcode_session_diff` | 对话工作区的 git 状态、改了哪些文件、限长 diff |
| `zcode_session_read` | 最近消息历史，限空闲会话 |
| `zcode_session_wait` | 等运行中的 turn 结束，把回复交给你 |
| `zcode_session_stop` | 掐断运行中的 turn |
| `zcode_session_set_model` | 换模型，下一条消息生效 |
| `zcode_session_permissions` | 列出待决的权限 / 用户输入请求 |
| `zcode_session_decide` | 答一个，turn 从暂停处接着跑 |
| `zcode_session_archive` | 藏起来但什么都不删；`unarchive: true` 找回来 |
| `zcode_session_discard` | 永久删除，先预演 |

模型选择器三种写法：裸 `modelId`（全目录唯一时才行）、`providerId/modelId`、`ProviderName/modelId`（比如 `CPA/gpt-5.6-luna`），后面都能接 `$reasoningLevel`（比如 `GLM-5.3-Flash$high`）。不给档位的话，模型支持就选 `high`。目录用 `zcode_models` 随时看。

`session_id` 之外值得知道的参数：

- `zcode_session_new`：`project` 把对话绑到已有仓库，改动直接落盘；`temporary` 让对话用完自清——闲置 10 分钟或桥退出时自动删掉——和 `project` 可以一起用；`model` 和 `mode`（`plan`/`build`/`edit`/`yolo`/`auto`）管用什么脑子、要什么权限；`files` 带本地文件；`wait: false` 发完就走。所有阻塞调用都受 `ZCODE_MCP_TOOL_BUDGET`（240s）管着，到点返回可续等的 timeout，用 `zcode_session_wait` 接着等。
- `zcode_session_send`：续聊的附件和等待行为同上。
- `zcode_session_decide`：拿 `zcode_session_permissions` 给的 `request_id`，加 `approve: true/false` 或 `decision`（`allow`/`deny`/`escalate`/`modify`），可附 `reason`。
- `zcode_session_wait`：超时说明里会讲清 turn 此刻是流式输出、思考还是卡住。
- `zcode_session_discard`：不带 `confirm: true` 只报行数，不动真格。

## 配置

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ZCODE_CJS` | 自动探测 | ZCode CLI 入口路径（`<安装目录>/resources/glm/zcode.cjs`），未设置时扫描常见安装位置。可设全局，也可按服务注册：`codex mcp add zcode-mcp --env ZCODE_CJS="<安装目录>/resources/glm/zcode.cjs" -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp` |
| `ZCODE_MCP_WORKSPACE` | `<仓库>/sandbox` | `zcode_session_new` 的默认工作区 |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | `zcode_session_new` 不传 `model` 时用的模型 |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | 单次阻塞工具调用的时间上限（秒）。Codex 会在 ~300s 掐断 tools/call，桥赶在那之前返回可续等的 timeout |
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

桥拉起一个 `zcode app-server` 子进程，说 ZCode Protocol：stdio 上的换行分隔 JSON，不握手。一段对话就是 `session/create`、`session/subscribe`、`session/send` 三步，回复从 `turn.completed` 事件里来。

```
MCP 客户端 (Codex / Claude / 你的 agent)         ZCode 桌面端
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ 共享会话存储
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server（桥拉起）
```

这个协议是 ZCode 的内部协议，没对外承诺稳定，而且坑不少。桥替你踩过了：

- turn 没跑完时调 `session/read` 会把 turn 悄悄弄死——桥绝不这么干；
- subscribe 必须赶在 send 前面，晚一步整个 turn 就错过了；
- `session/list` 在模型重试窗口里谎报 `idle`——完成只认事件；
- 服务端会反过来问问题（运行时偏好、插件身份头），桥都接住了，桌面 App 不开也能把会话跑起来。

归档和删除是直接操作 ZCode 的两个 SQLite 库——协议里压根没有这两个方法。

模型从哪来：会话能用哪些 provider，由 app-server 注册表（`~/.zcode/v2/provider_config.json`）说了算。你自己加的 provider 沿用配置里的 id（通常是个 UUID），BigModel 系的通道都折叠成一个 `bigmodel-api`。桌面端的账号型来源（BigModel 个人、Start Plan、Z.ai）绑着你的桌面登录，进不了这个注册表——`zcode_models` 会列出来供参考，你真去选它会讲清为什么不行。

## 已知边界

- **桌面账号型额度的 token，MCP 这边一个都用不了。** Start Plan、BigModel 个人、Z.ai 的模型进不了无头会话的注册表，这些额度不管剩多少，都只能在桌面 App 自己的对话里花。纯 API key 的 provider 不一样：在 ZCode 里加一个，MCP 里就能当普通 provider 用。
- 需要本地装 ZCode。app-server 协议没对外承诺稳定，版本升级可能变动（实测 0.16.9 / 桌面端 3.14.4）。
- Windows 优先：默认路径按 Windows 版 ZCode 假设，其余代码全平台可移植。
- 桥创建的会话里，预置官方插件（联网搜索这类）以空身份启动，模型和本地工具不受影响。
- 桌面端正开着的对话别 discard；删运行中的会话是尽力而为。`zcode_session_discard` 不可恢复，先预演。桥要是没走正常退出（崩溃、被杀），它名下的临时对话会留在库里且不带标记。

## 许可证

MIT
