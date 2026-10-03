# zcode-mcp

English | [中文](README_zh.md)

ZCode is a great place to run an agent — but your main agent probably lives in Codex or Claude Code. zcode-mcp connects the two over MCP: your agent opens real ZCode conversations, hands them work, watches the model write, and collects the result. The conversations show up in the ZCode desktop app like any other, so nothing you create here is locked into a side channel.

The bridge speaks ZCode's own app-server protocol (the desktop app's channel), has already stepped on the protocol's landmines for you, and cleans up throwaway subagent sessions when the work is done.

Windows-first. Tested against ZCode 0.16.9 (desktop 3.14.4). Python ≥ 3.9, standard library only. MIT.

## Quick start

You need Python ≥ 3.9, Node.js (the one bundled with the ZCode desktop app works fine), and a logged-in ZCode desktop app or CLI 0.16.x.

Register with Codex:

```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

`uvx` pulls the repo, builds an isolated environment and runs it — there is nothing to install by hand. Pin a version by appending `@<tag>` to the git URL. Claude Code and other MCP clients take the same command as a stdio server (`claude mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp`).

Now give your agent its first job through ZCode:

```json
{"name": "zcode_session_new", "arguments": {"text": "List the Python files in this workspace and count them"}}
```

```
session_id=sess_8b0d1110-4d8c-4071-845e-69ceba860e9f
workspace=D:\work\sandbox
There are 3 Python files: agent.py, fetch.py, report.py.
```

Open the ZCode desktop app and look: the conversation is right there, and both sides can keep talking to it.

Two things that trip people up on day one:

- ZCode installed somewhere unusual? Point `ZCODE_CJS` at its `zcode.cjs` entry (see Configuration).
- Headless `codex exec` refuses MCP tool calls under its default approval policy. For automation use `--dangerously-bypass-approvals-and-sandbox` (after deciding what your agents may touch) or `--approve-for-me`; interactive Codex asks once and moves on.

## Skills

Writing the perfect invocation for each of 18 tools is the agent's job, not yours. The repo ships three SKILL.md documents that teach it (Codex reads them; other SKILL.md-aware clients too):

| Skill | What your agent learns |
| --- | --- |
| `zcode-mcp` | The full manual: every tool, model selection, permission flow, what to use when |
| `zcode-subagent` | Running ZCode as a worker: dispatch patterns, verification loops, cleanup |
| `zcode-code-reviewer` | Read-only code review over a diff |

Install for Codex:

```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/
```

```powershell
# Windows (PowerShell)
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills\
```

## Tools

18 tools. Three stand alone; the rest each drive one conversation.

Standalone:

| Tool | What it does |
| --- | --- |
| `zcode_models` | The live model catalogue with provider display names and reasoning levels — plus the desktop-only sources sessions can't touch |
| `zcode_quota` | Every plan quota window and Start Plan token balance in one call |
| `zcode_health` | Whether the bridge, Node.js, ZCode CLI and app-server are alive and happy |

Conversation tools, all taking a `session_id`:

| Tool | What it does |
| --- | --- |
| `zcode_session_new` | Opens a conversation and sends the first message; blocks for the reply unless `wait: false` |
| `zcode_session_send` | Follow-up messages, with or without attachments |
| `zcode_session_status` | What the conversation is doing right now: model, turn state, pending approvals |
| `zcode_session_output` | What the model has written so far; poll it while the turn runs |
| `zcode_session_result` | The end result in one compact blob: status, reply, error, model |
| `zcode_session_diff` | Git status, changed files, a bounded diff for the conversation's workspace |
| `zcode_session_read` | Recent message history, once the conversation is idle |
| `zcode_session_wait` | Blocks until the running turn ends and hands you the reply |
| `zcode_session_stop` | Interrupts the running turn |
| `zcode_session_set_model` | Switches the model, effective from the next message |
| `zcode_session_permissions` | Lists pending permission / user-input requests |
| `zcode_session_decide` | Answers one; the turn picks up where it paused |
| `zcode_session_archive` | Hides from lists, deletes nothing; `unarchive: true` brings it back |
| `zcode_session_discard` | Permanent delete, dry-run first |

A model selector is a bare `modelId` (only when unique across the catalogue), `providerId/modelId`, or `ProviderName/modelId` like `CPA/gpt-5.6-luna` — each optionally suffixed with `$reasoningLevel` (`GLM-5.3-Flash$high`). With no level given, models that support it get `high`. The live catalogue is one `zcode_models` call away.

Parameters worth knowing beyond `session_id`:

- `zcode_session_new`: `project` binds the conversation to an existing repo so edits land there; `temporary` makes it self-cleaning — auto-deleted after 10 idle minutes or when the bridge exits — and combines with `project`; `model` and `mode` (`plan`/`build`/`edit`/`yolo`/`auto`) pick the brain and the permission level; `files` attaches local files; `wait: false` fires and returns. Every blocking call is capped by `ZCODE_MCP_TOOL_BUDGET` (240s) and returns a resumable timeout; `zcode_session_wait` picks the wait back up.
- `zcode_session_send`: same attachment and wait behavior, for follow-ups.
- `zcode_session_decide`: takes the `request_id` from `zcode_session_permissions` plus `approve: true/false` or a `decision` of `allow`/`deny`/`escalate`/`modify`, optional `reason`.
- `zcode_session_wait`: on timeout, the note says whether the turn is streaming, producing, or stalled.
- `zcode_session_discard`: dry-run row counts unless `confirm: true`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZCODE_CJS` | auto-detected | Path to the ZCode CLI entry (`<install dir>/resources/glm/zcode.cjs`); common install locations are scanned when unset. Set it globally or per-server: `codex mcp add zcode-mcp --env ZCODE_CJS="<install dir>/resources/glm/zcode.cjs" -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp` |
| `ZCODE_MCP_WORKSPACE` | `<repo>/sandbox` | Default workspace for `zcode_session_new` |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash` | Model used when `zcode_session_new` gets no `model` |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | Cap for any single blocking tool call, in seconds. Codex kills a tools/call at ~300s; the bridge returns a resumable timeout before that |
| `ZCODE_MCP_TEMP_TTL` | `600` | Idle seconds before a `temporary` conversation is auto-deleted. Running turns are never reaped; `0` disables |
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

The bridge spawns one `zcode app-server` child and talks ZCode Protocol: newline-delimited JSON over stdio, no handshake. A conversation is `session/create`, `session/subscribe`, `session/send` — the reply arrives as a `turn.completed` event.

```
MCP client (Codex / Claude / your agent)        ZCode desktop app
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ shared session store
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server (spawned)
```

The protocol is ZCode's internal one, not a published API, and it bites. The bridge handles the bites:

- calling `session/read` while a turn runs silently kills the turn — so it never does
- subscribe must happen before send; a late subscription misses the whole turn
- `session/list` reports `idle` through model-retry windows — completion is only believed from events
- the server asks reverse questions (runtime preferences, plugin identity headers); they get answered, so sessions come up fine without the desktop app

Archive and discard go straight at ZCode's two shared SQLite stores, because the protocol has no methods for either.

Where models come from: what a session can address is decided by the app-server registry (`~/.zcode/v2/provider_config.json`). Providers you add yourself keep their config id (often a UUID), and all BigModel-family channels collapse into one `bigmodel-api` provider. The desktop's account sources (BigModel 个人, Start Plan, Z.ai) are tied to your desktop login and never enter this registry — `zcode_models` lists them for reference, and explains why when you try to select one.

## Limitations

- **Desktop account quotas can't be spent from MCP sessions.** Start Plan, BigModel 个人 and Z.ai models never enter the registry headless sessions use, so those tokens are desktop-only no matter how many are left. Plain API-key providers are different: add one in ZCode and it works here like any other.
- Requires a local ZCode install. The app-server protocol is not a published API and may change between ZCode versions (tested against 0.16.9 / desktop 3.14.4).
- Windows-first: default paths assume a Windows ZCode install. Everything else is portable standard library.
- Preset official plugin MCPs (web search and friends) start without desktop credentials in bridge-created sessions; the model and local tools are unaffected.
- Don't discard a conversation the desktop app currently has open, and expect discarding a running session to be best-effort. `zcode_session_discard` is irreversible; dry-run first. And if the bridge dies without a clean exit (crash, kill), its temporary conversations stay behind unmarked.

## License

MIT
