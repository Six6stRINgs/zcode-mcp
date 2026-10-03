# zcode-mcp

[English](README.md) | 中文

ZCode 的 Model Context Protocol (MCP) 桥接服务。

将本地 ZCode 运行环境接入外部 AI Agent 工具链（如 Codex、Claude Code 等）。支持多轮会话驱动、子任务派发、流式输出观测、动态模型切换与临时会话自动清理，所有会话与 ZCode 桌面端实时双向同步。

---

## 核心特性

- **桌面端双向同步**：通过 ZCode 本地 app-server 协议通信，创建的会话与桌面端完全一致，可在桌面端即时查看与接管。
- **子任务自动回收**：支持临时会话生命周期管理，任务完成后自动回收资源，避免无用会话堆积。
- **全模型调度**：支持多 Provider 动态切换与 Reasoning 思考档位配置。
- **状态观测与流式捕获**：提供实时的 Turn 执行状态检测、流式内容轮询及超时间隔防护。
- **工作区上下文集成**：支持直接绑定已有项目仓库，提供 Git 状态与变更 Diff 查询。
- **轻量零依赖**：基于 Python 3.9+ 纯标准库实现，无外部第三方库强依赖。

## 运行环境

- **Python**：≥ 3.9
- **Node.js**：系统已安装或使用 ZCode 桌面端内置运行时
- **ZCode**：已安装并完成登录的 ZCode 桌面端或 CLI（推荐 0.16.x 及以上）
- **操作系统**：跨平台支持（Windows、Linux、macOS），自动探测各平台标准安装路径

## 接入配置

在 MCP 宿主客户端中添加服务配置：

### Codex
```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

### Claude Code
```bash
claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

若 ZCode 安装在非默认目录，可通过环境变量 `ZCODE_CJS` 指定其 `zcode.cjs` 核心入口路径。在无头自动化环境中执行时，需根据宿主客户端策略配置相应的工具审批权限。

## 内置技能 (Skills)

仓库内置 3 个标准化 SKILL.md，用于为 MCP Agent 提供编排与调度规则：

| 技能名称 | 定位与能力 |
| --- | --- |
| `zcode-mcp` | 完整工具使用规约、模型选择器语法、权限审批流与参数规范 |
| `zcode-subagent` | ZCode 任务派发规范、执行与验收循环、临时会话自动回收流程 |
| `zcode-code-reviewer` | 基于 Git Diff 的只读代码评审规范 |

安装至 Codex：
```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/

# Windows PowerShell
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## 工具列表

服务共提供 18 个 MCP 工具，划分为独立全局工具与会话操作工具两类。

### 独立全局工具

| 工具名称 | 功能描述 |
| --- | --- |
| `zcode_models` | 查询当前可用模型目录、Provider 显示名、支持的 Reasoning 档位及桌面端专用非编排模型状态 |
| `zcode_quota` | 获取当前账户套餐额度窗口使用情况与 Start Plan 每日 Token 余额 |
| `zcode_health` | 检查 MCP 桥接服务、Node.js、ZCode CLI 及 app-server 进程连通性 |

### 会话操作工具

所有会话工具均基于 `session_id` 句柄进行交互：

| 工具名称 | 功能描述 |
| --- | --- |
| `zcode_session_new` | 创建新对话并发送首条消息；支持项目目录绑定、模型指定、权限模式、附件传递及临时标记 |
| `zcode_session_send` | 向指定会话发送后续消息与附件 |
| `zcode_session_list` | 列出全部工作区的会话摘要，包含会话 ID、状态、模式、标题，支持查询归档会话 |
| `zcode_session_status` | 查询指定会话的当前状态、运行模型、Turn 阶段与待决权限 |
| `zcode_session_output` | 轮询当前或最近已完成 Turn 的流式生成文本 |
| `zcode_session_result` | 获取 Turn 的综合结算结果，包含执行状态、最终回复文本、报错详情与模型信息 |
| `zcode_session_diff` | 获取会话关联工作区的 Git 变更文件列表与上下文 Diff 内容 |
| `zcode_session_read` | 在会话空闲时读取最近的消息历史记录 |
| `zcode_session_wait` | 阻塞等待正在执行的 Turn 结束并返回结果，受工具调用超时上限控制 |
| `zcode_session_stop` | 强制终止当前会话中正在运行的 Turn |
| `zcode_session_set_model` | 修改会话生效模型，于下一轮消息交互时起效 |
| `zcode_session_permissions` | 列出当前会话中挂起的权限审批或交互输入请求 |
| `zcode_session_decide` | 提交对挂起权限的审批决定（允许、拒绝、升级、修改）或答复交互输入 |
| `zcode_session_archive` | 切换会话归档状态，隐藏显示而不删除历史数据 |
| `zcode_session_discard` | 物理删除会话记录；默认执行预检并返回受影响行数，需显式确认生效 |

## 规格说明

### 模型选择器语法
模型参数统一遵循以下命名格式：
```
[Provider/]<ModelID>[$ReasoningLevel]
```
- **匹配规则**：支持使用全局唯一 ModelID、`providerId/modelId`（配置标识符）或 `ProviderName/modelId`（展示名）。
- **思考档位**：支持通过 `$<level>` 指定 Reasoning 强度（如 `$high`, `$medium`, `$low`）；未显式指定且模型支持思考档位时，默认启用最强档位。

### 临时会话管理
- **自动清理**：在创建会话时指定 `temporary: true`，后台守护进程将在会话闲置达到超时阈值后自动执行物理删除，并在桥接服务退出时清理所有存活的临时会话。
- **运行保护**：存在正在执行的 Turn 或正在处理的工具调用时，会话受到保护不会被回收。每次工具调用均会重置闲置计时。

### 超时控制
- 单次同步阻塞调用受 `ZCODE_MCP_TOOL_BUDGET` 控制。在达到宿主客户端超时阈值前，桥接服务会主动返回带有当前执行状态的中间结果，支持通过 `zcode_session_wait` 继续等待。
- 创建及发送接口支持通过 `wait: false` 切换为非阻塞模式，转由后台异步执行。

## 环境变量配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ZCODE_CJS` | 自动探测 | ZCode CLI 入口路径（`<安装目录>/resources/glm/zcode.cjs`） |
| `ZCODE_MCP_WORKSPACE` | `<仓库根目录>/sandbox` | 新建会话未指定项目时的默认沙箱路径 |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | 新建会话未指定模型时的默认模型标识 |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | 单次阻塞工具调用的最大等待秒数 |
| `ZCODE_MCP_TEMP_TTL` | `600` | 临时会话自动回收的闲置判定秒数（设为 `0` 则禁用自动清理） |
| `ZCODE_MCP_DEBUG` | 停用 | 启用协议通信详细调试日志输出 |
| `ZCODE_MCP_NO_WARMUP` | 停用 | 跳过服务启动时的 app-server 预热连接 |
| `ZCODE_HOME` | `~/.zcode` | ZCode 用户数据与配置存储根目录 |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | 会话数据库绝对路径覆盖 |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | 桌面端任务索引数据库路径覆盖 |
| `ZCODE_MCP_CREDENTIALS` | `$ZCODE_HOME/v2/credentials.json` | 额度认证凭据路径覆盖 |
| `ZCODE_MCP_ZCODE_CONFIG` | `$ZCODE_HOME/v2/config.json` | 用户全局配置文件路径覆盖 |
| `ZCODE_MCP_PROVIDER_CONFIG` | `$ZCODE_HOME/v2/provider_config.json` | Provider 注册表文件路径覆盖 |
| `ZCODE_MCP_APP_VERSION` | `3.14.4` | 请求套餐额度接口时使用的客户端版本标识 |

## 运行架构

```
MCP 宿主客户端 (Codex / Claude Code / Agent)
       │
       │ MCP 协议 (stdio JSON-RPC)
       ▼
zcode-mcp 桥接服务
       │
       │ ZCode 内部协议 (NDJSON / stdio)
       ▼
zcode app-server
       │
       ▼
本地 SQLite 会话存储与工作区文件 ◄──► ZCode 桌面客户端
```

## 注意事项

- **桌面登录专属模型限制**：绑定于桌面端特定登录身份的账号源模型无法在无头会话中直接调度；需使用配置有有效独立 API 密钥的 Provider。
- **依赖本地环境**：依赖本地安装且处于登录状态的 ZCode 桌面端或 CLI 运行时。
- **物理删除不可逆**：`zcode_session_discard` 为永久性物理删除操作。
- **未正常退出清理**：若桥接服务进程异常终止，未及清理的临时会话将保留在本地数据库中。

## 许可证

MIT
