# zcode-mcp

English | [中文](README_zh.md)

Drive [ZCode](https://zcode.z.ai), Z.AI's agentic coding app, from any MCP client: Codex CLI, Claude Code, Cursor, or your own agents. The bridge opens real ZCode conversations that show up in the desktop app, streams the model's partial output while it works, switches models mid-conversation, and cleans up after itself when you dispatch throwaway subagent workers.

Windows-first. Tested against ZCode 0.16.9 (desktop 3.14.4). Python ≥ 3.9, standard library only. MIT.

## Quick start

You need Python ≥ 3.9, Node.js (the one bundled with the ZCode desktop app works), and a logged-in ZCode desktop app or CLI 0.16.x.

Register with Codex CLI:

```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

`uvx` fetches the repo and runs the entry point in an isolated environment. Pin a version by appending `@<tag>` to the git URL. Other clients register the same command as a stdio MCP server; for Claude Code that is `claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp`.

Then send the first conversation from your agent:

```json
{"name": "zcode_session_new", "arguments": {"text": "List the Python files in this workspace and count them"}}
```

```
session_id=sess_8b0d1110-4d8c-4071-845e-69ceba860e9f
workspace=D:\work\sandbox
There are 3 Python files: agent.py, fetch.py, report.py.
```

That session is real: it appears in the ZCode desktop app, and you can continue it there or from your agent with `zcode_session_send`.

Two things people hit first:

- If ZCode is installed outside the default locations, set the `ZCODE_CJS` environment variable to its `zcode.cjs` entry (details in Configuration).
- Headless `codex exec` rejects MCP tool calls under its default approval policy. Use `--dangerously-bypass-approvals-and-sandbox` (after deciding what your agents may reach) or `--approve-for-me`; interactive Codex just asks once.

## Skills

The repo ships three SKILL.md documents for clients that read them (Codex does):

| Skill | Use it for |
| --- | --- |
| `zcode-mcp` | The reference manual: every tool, model selection, permission flow, decision guide |
| `zcode-subagent` | Dispatch patterns for ZCode-as-a-worker, verification loops, lifecycle |
| `zcode-code-reviewer` | Read-only code review over a diff |

Install for Codex by copying them into its skills directory:

```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/
```

```powershell
# Windows (PowerShell)
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## Tools

18 tools in two groups.

Standalone, no conversation required:

| Tool | Purpose |
| --- | --- |
| `zcode_models` | The live model catalogue with provider display names and reasoning levels, plus the desktop-only sources sessions cannot address |
| `zcode_quota` | All plan quota windows and Start Plan token balances in one call |
| `zcode_health` | Bridge, Node.js, ZCode CLI and app-server health check |

Conversation tools, all taking a `session_id`:

| Tool | Purpose |
| --- | --- |
| `zcode_session_new` | New conversation + first message; blocks for the reply unless `wait: false` |
| `zcode_session_send` | Follow-up message, with or without attachments |
| `zcode_session_status` | Live state: current model, turn state, pending interactions |
| `zcode_session_output` | What the model has written so far; poll it mid-turn |
| `zcode_session_result` | Compact machine-readable result: status, reply, error, model |
| `zcode_session_diff` | Git status, changed files and a bounded diff for the conversation's workspace |
| `zcode_session_read` | Recent message history (while the conversation is idle) |
| `zcode_session_wait` | Block until the running turn ends and get the reply |
| `zcode_session_stop` | Interrupt the running turn |
| `zcode_session_set_model` | Switch the conversation's model, effective next message |
| `zcode_session_permissions` | List pending permission or user-input requests |
| `zcode_session_decide` | Answer a pending request; the turn resumes |
| `zcode_session_archive` | Hide from lists, nothing deleted; `unarchive: true` restores |
| `zcode_session_discard` | Permanent delete with a dry-run guard |

A model selector is a bare `modelId` (when unique across the catalogue), `providerId/modelId`, or `ProviderName/modelId` such as `CPA/gpt-5.6-luna`, optionally suffixed with `$reasoningLevel` (`GLM-5.3-Flash$high`). When no level is given, `high` is preferred for models that support it. `zcode_models` prints the live catalogue.

Parameters worth knowing beyond `session_id`:

- `zcode_session_new`: `project` attaches the conversation to an existing repo so edits land there; `temporary` makes it self-cleaning (auto-discarded after 10 idle minutes or when the bridge exits), which composes with `project`; `model` and `mode` (`plan`/`build`/`edit`/`yolo`/`auto`) select brain and permission level; `files` attaches local files; `wait: false` returns immediately, capping at `ZCODE_MCP_TOOL_BUDGET` (240s) like every blocking call, after which `zcode_session_wait` resumes the wait.
- `zcode_session_send`: same attachment and wait behavior for follow-ups.
- `zcode_session_decide`: takes the `request_id` from `zcode_session_permissions` plus `approve: true/false` or a `decision` of `allow`/`deny`/`escalate`/`modify`, with an optional `reason`.
- `zcode_session_wait`: its timeout note tells you whether the turn is streaming, producing, or stalled.
- `zcode_session_discard`: dry-run row counts unless `confirm: true`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZCODE_CJS` | auto-detected | Path to the ZCode CLI entry (`<install dir>/resources/glm/zcode.cjs`). When unset, common install locations are scanned. Set it globally, or per-server: `codex mcp add zcode-mcp --env ZCODE_CJS="<install dir>/resources/glm/zcode.cjs" -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp` |
| `ZCODE_MCP_WORKSPACE` | `<repo>/sandbox` | Default workspace for `zcode_session_new` |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | Model used when `zcode_session_new` gets no `model` |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | Cap for any single blocking tool call, in seconds. Codex aborts a tools/call at ~300s; the bridge returns a resumable timeout before that |
| `ZCODE_MCP_TEMP_TTL` | `600` | Seconds of inactivity before a `temporary` conversation is auto-discarded. Running turns are never reaped; `0` disables |
| `ZCODE_MCP_DEBUG` | off | Verbose protocol logging (`bridge.log`, `child_dump.log`) |
| `ZCODE_MCP_NO_WARMUP` | off | Skip the app-server warm-up spawn |
| `ZCODE_HOME` | `~/.zcode` | Root of ZCode's shared stores |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | Override the session store path |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | Override the desktop task-index path |
| `ZCODE_MCP_CREDENTIALS` | `$ZCODE_HOME/v2/credentials.json` | Override the OAuth credential store (quota) |
| `ZCODE_MCP_ZCODE_CONFIG` | `$ZCODE_HOME/v2/config.json` | Override the provider config path (Start Plan balance) |
| `ZCODE_MCP_PROVIDER_CONFIG` | `$ZCODE_HOME/v2/provider_config.json` | Override the app-server provider registry path (model names) |
| `ZCODE_MCP_APP_VERSION` | `3.14.4` | `app_version` sent to plan-quota endpoints |

## How it works

The bridge spawns one `zcode app-server` child and speaks ZCode Protocol: newline-delimited JSON over stdio, no handshake. A conversation is `session/create`, then `session/subscribe`, then `session/send`, and the reply arrives as the `turn.completed` event.

```
MCP client (Codex / Claude / your agent)        ZCode desktop app
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ shared session store
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server (spawned)
```

The protocol is internal to ZCode, not a published API, and it has sharp edges the bridge handles for you:

- never call `session/read` while a turn runs; it silently aborts the turn
- subscribe before send, because a subscription only captures turns that start after it
- `session/list` reports `idle` early, sometimes through entire model-retry windows, so completion is only trusted from events
- the server's reverse requests (runtime preferences, plugin identity headers) get answered, so sessions materialize without the desktop app running

Archive and discard operate on ZCode's two shared SQLite stores because the protocol has no such methods.

How model identity works: sessions address providers through the app-server registry (`~/.zcode/v2/provider_config.json`). Custom API providers keep their config id (often a UUID), and BigModel-family channels collapse into one `bigmodel-api` provider named after whatever that entry is called. Desktop account sources (BigModel 个人, Start Plan, Z.ai) are backed by the desktop login and never enter this registry; `zcode_models` lists them for reference and refuses selection with guidance.

## Limitations

- **Desktop account quotas cannot be spent from MCP sessions.** Start Plan, BigModel 个人 and Z.ai models never enter the registry headless sessions address, so their quota is consumable only in the desktop app's own conversations, regardless of remaining balance. Providers backed by a plain API key are different: add one as a custom provider in ZCode and it becomes fully usable here.
- Requires a local ZCode install. The app-server protocol is not a published API and may change between ZCode versions (tested against 0.16.9 / desktop 3.14.4).
- Windows-first: default paths assume a Windows ZCode install. Everything else is portable standard library.
- Preset official plugin MCPs (web search and friends) start without desktop credentials in bridge-created sessions; the model and local tools are unaffected.
- Do not discard a conversation the desktop app currently has open, and expect discarding a running session to be best-effort. `zcode_session_discard` is irreversible; always dry-run first.

## License

MIT
