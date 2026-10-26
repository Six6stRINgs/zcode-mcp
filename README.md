# zcode-mcp

English | [中文](README_zh.md)

Model Context Protocol (MCP) gateway for ZCode.

Connects local ZCode runtime capabilities into external AI agent workflows (such as Codex, Claude Code, and other MCP clients). Enables multi-turn conversation management, subagent dispatch, streaming output observation, dynamic model switching, and automated cleanup of temporary sessions, fully synchronized with the ZCode desktop interface.

---

## Key Features

- **Shared Sessions with the Desktop App**: Sessions persist to ZCode's shared session store and appear in the desktop app, where they can be opened and continued from either side. Live streaming only flows to the process driving a turn: bridge-driven messages show up in the desktop when the conversation is reopened (fresh read from the store), and the sidebar refreshes on window focus.
- **Automated Lifecycle Management**: Manages temporary session lifecycles with idle timeout cleanup to prevent session clutter.
- **Model Orchestration**: Supports dynamic switching across configured providers and configurable reasoning effort levels.
- **Observability & Streaming**: Real-time turn state tracking, output polling, and tool budget timeout protection.
- **Workspace Integration**: Binds sessions to existing repository workspaces with Git status and diff inspection.
- **Zero External Dependencies**: Built entirely on Python 3.9+ standard library.

## Requirements

- **Python**: ≥ 3.9
- **Node.js**: System installation or the runtime bundled with ZCode Desktop
- **ZCode**: Installed and logged in via ZCode Desktop or CLI (0.16.x or newer, tested against 0.17.0)
- **Operating System**: Cross-platform (Windows, Linux, macOS); standard installation paths detected automatically on each platform

## Setup

Add the server to your MCP client configuration:

### Codex
```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

### Claude Code
```bash
claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

For non-standard ZCode installations, set the `ZCODE_CJS` environment variable to the path of `zcode.cjs`. Configure execution approval settings in headless environments according to client security policies.

## Cloud Link

The app-server protocol is plain NDJSON over a byte stream, so the bridge can drive a ZCode app-server on any reachable machine instead of a local one. The remote host needs a logged-in ZCode CLI; with SSH transport no extra server-side daemon is required. Set one variable to switch transports:

| Environment Variable | Purpose |
| --- | --- |
| `ZCODE_MCP_REMOTE_SSH` | SSH destination (e.g. `user@10.0.0.8`); the bridge spawns the remote CLI over the ssh pipe |
| `ZCODE_MCP_SSH_ARGS` | Extra ssh arguments (port, key file); key-based auth is required — interactive password prompts cannot be answered |
| `ZCODE_MCP_REMOTE_CJS` | Remote entry: absolute `zcode.cjs` path (run via node) or a bare CLI command name; default `zcode` from the remote PATH |
| `ZCODE_MCP_REMOTE_WORKSPACE` | Remote working directory passed as app-server `--cwd` (default `.`) |
| `ZCODE_MCP_REMOTE_TCP` | `host:port` of a raw remotely-exposed app-server socket; takes precedence over SSH when both are set |

Cloud-link semantics by design: session data lives in the remote host's stores, so local-store operations degrade — `zcode_session_archive` / `zcode_session_discard` refuse with guidance, `zcode_session_diff` points at the remote host, and temporary-session cleanup closes the runtime session without deleting remote rows. `zcode_models` and all conversation tools work unchanged; `zcode_quota` still reports the local machine's plans. `zcode_health` reports the active transport. Sessions created by an earlier app-server process are transparently re-activated: on a `-32004 Session is not active` rejection the bridge runs `session/resume` and retries the call once.

## Built-in Skills

The repository includes three standardized SKILL.md documents to guide agents on tool usage and orchestration:

| Skill | Description |
| --- | --- |
| `zcode-mcp` | Complete tool reference, model selector syntax, permission workflows, and argument rules |
| `zcode-subagent` | Subagent worker dispatch patterns, verification cycles, and session cleanup procedures |
| `zcode-code-reviewer` | Read-only code review workflows based on Git diffs |

Install to Codex:
```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/

# Windows PowerShell
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## Tools

Provides 18 MCP tools categorized into standalone global tools and conversation orchestration tools.

### Standalone Tools

| Tool | Description |
| --- | --- |
| `zcode_models` | Queries available models, provider display names, supported reasoning levels, and non-addressable desktop sources |
| `zcode_quota` | Fetches plan quota window utilization and Start Plan daily token balances |
| `zcode_health` | Checks connectivity and health of the MCP bridge, Node.js runtime, ZCode CLI, and app-server |

### Conversation Orchestration Tools

All conversation tools operate on a target `session_id`:

| Tool | Description |
| --- | --- |
| `zcode_session_new` | Opens a new conversation with an initial prompt; supports workspace binding, model selection, execution modes, file attachments, and temporary lifecycle flags |
| `zcode_session_send` | Sends subsequent messages and attachments to an active conversation |
| `zcode_session_list` | Lists conversation summaries across all workspaces (ID, status, execution mode, title), with optional archived session retrieval |
| `zcode_session_status` | Returns the current state, active model, turn phase, and pending approvals for a conversation |
| `zcode_session_output` | Polls streaming generation text from an ongoing or recently completed turn |
| `zcode_session_result` | Retrieves consolidated turn execution results, including status, reply content, errors, and model metadata |
| `zcode_session_diff` | Retrieves Git status, modified file lists, and diff excerpts for the workspace bound to the session |
| `zcode_session_read` | Reads recent message history when the session is idle |
| `zcode_session_wait` | Blocks until the active turn finishes, bounded by the tool execution budget |
| `zcode_session_stop` | Interrupts the actively running turn |
| `zcode_session_set_model` | Changes the active model for subsequent messages in the conversation |
| `zcode_session_permissions` | Lists pending permission requests or user prompt queries in the conversation |
| `zcode_session_decide` | Submits approval decisions (allow, deny, escalate, modify) or answers interactive prompts |
| `zcode_session_archive` | Toggles conversation archived state, hiding it from default lists without deleting data |
| `zcode_session_discard` | Permanently deletes conversation records from storage; performs a dry-run unless confirmation is provided |

## Specifications

### Model Selector Syntax
Model parameters follow the standardized pattern:
```
[Provider/]<ModelID>[$ReasoningLevel]
```
- **Matching Rules**: Resolves unique Model IDs, `providerId/modelId` identifiers, or `ProviderName/modelId` display names.
- **Reasoning Levels**: Configured via the `$<level>` suffix (such as `$high`, `$medium`, `$low`). When omitted on supported models, defaults to the highest available level.

### Temporary Session Lifecycle
- **Automatic Reaper**: Conversations initialized with `temporary: true` are tracked by a background daemon and permanently deleted after exceeding the configured idle duration. All active temporary sessions are cleared when the bridge process exits.
- **Execution Safeguards**: Sessions with active turns or ongoing tool executions are protected from reaping. Every tool call touching the session resets the idle timer.

### Timeout Control
- Blocking tool executions are bounded by `ZCODE_MCP_TOOL_BUDGET`. Before reaching host client timeouts, the bridge returns intermediate status reports and resumes execution via `zcode_session_wait`.
- Non-blocking execution is supported via `wait: false` on message creation and delivery tools.

## Configuration

| Environment Variable | Default | Description |
| --- | --- | --- |
| `ZCODE_CJS` | auto-detected | Path to the ZCode CLI entry (`<install dir>/resources/glm/zcode.cjs`) |
| `ZCODE_MCP_WORKSPACE` | `<repo root>/sandbox` | Default workspace directory when no project path is specified |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | Fallback model used when no model is explicitly passed |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | Maximum execution time in seconds for blocking tool calls |
| `ZCODE_MCP_TEMP_TTL` | `600` | Idle timeout in seconds before reaping temporary sessions (`0` disables) |
| `ZCODE_MCP_DEBUG` | disabled | Enables detailed protocol logging |
| `ZCODE_MCP_NO_WARMUP` | disabled | Skips the initial app-server warm-up connection |
| `ZCODE_HOME` | `~/.zcode` | Root directory for ZCode user data and shared storage |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | Overrides the SQLite session database path |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | Overrides the desktop task index database path |
| `ZCODE_MCP_CREDENTIALS` | `$ZCODE_HOME/v2/credentials.json` | Overrides the OAuth credentials file path |
| `ZCODE_MCP_ZCODE_CONFIG` | `$ZCODE_HOME/v2/config.json` | Overrides the user configuration file path |
| `ZCODE_MCP_PROVIDER_CONFIG` | `$ZCODE_HOME/v2/provider_config.json` | Overrides the provider registry file path |
| `ZCODE_MCP_APP_VERSION` | `3.16.3` | Client version sent in quota balance requests |

## Architecture

```
MCP Client (Codex / Claude Code / Agent)
       │
       │ MCP Protocol (stdio JSON-RPC)
       ▼
zcode-mcp Gateway
       │
       │ ZCode Internal Protocol (NDJSON / stdio)
       ▼
zcode app-server
       │
       ▼
Local SQLite Storage & Workspace Files ◄──► ZCode Desktop App
```

## Considerations

- **Desktop-Only Account Sources**: Models tied exclusively to desktop account sources cannot be addressed in headless sessions; use providers with standard API access.
- **No Live Streaming into the Desktop**: ZCode has no cross-process event bus — turn events only flow to subscribers of the app-server process driving the turn. The bridge spawns its own app-server, so bridge-driven messages do not live-stream into an open desktop view: reopen the conversation in the desktop to see them (fresh read from the shared store); the sidebar refreshes on window focus. Turn streaming for MCP clients is unaffected (`zcode_session_output` polls it live).
- **No Autonomous Model Switching**: When the model in use exhausts its quota mid-task, the agent must pause and ask the user which model to continue on; switching models without the user's explicit instruction is forbidden. The bundled skills enforce this rule.
- **Local Environment**: Requires a local ZCode desktop or CLI installation with an active login session.
- **Permanent Deletion**: The `zcode_session_discard` tool irreversibly deletes conversation data.
- **Abnormal Termination**: If the bridge process is forcefully terminated, temporary sessions created during the run remain in the local database.

## License

MIT
