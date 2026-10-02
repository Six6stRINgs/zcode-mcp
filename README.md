# zcode-mcp

English | [中文](README_zh.md)

Talk to [ZCode](https://zcode.z.ai) — Z.AI's agentic coding app — from any
MCP client (Codex CLI, Claude Code, Cursor, your own agents).

zcode-mcp opens ZCode conversations, keeps them going across turns, and lets
you check on the model's partial output as it is generated. It speaks to ZCode through its official
**app-server protocol** — the same channel the desktop app uses — so every
conversation you create here is a real one: visible in the desktop app,
resumable there, and editing real files in your projects.

```
MCP client (Codex / Claude / your agent)        ZCode desktop app
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ shared session store
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server (spawned)
```

Pure Python standard library — the only optional dependency is
`cryptography`, and only if you want plan-quota reporting.

## Highlights

- **Multi-turn conversations** — hold a session id, send follow-ups, correct
  course mid-task.
- **Mid-turn observability** — while a turn runs, poll status and read what
  the model has written so far (accumulated live by the bridge); wait
  timeouts classify the turn as streaming, thinking, or stalled.
- **Interactive permissions** — non-yolo modes work: when ZCode asks for
  approval, the orchestrating agent sees the request, decides, and the turn
  resumes.
- **Model selection & quota** — choose any session-addressable model per
  conversation by name (`CPA/gpt-5.6-luna`) or id, switch mid-flight, and
  check all plan quota windows in one call.
- **Lifecycle control** — project-scoped and throwaway conversations,
  archive/unarchive, and permanent delete with a dry-run guard.
- **Native attachments** — files and images go through ZCode's own
  attachment pipeline, exactly like dragging them into the desktop composer.
- **Desktop interoperability** — sessions live in the shared store; the
  desktop app can list and resume everything you create here.

## Requirements & installation

**Requirements**

- Python ≥ 3.9 (stdlib only; `cryptography` optional, for `zcode_quota`)
- Node.js (the one bundled with the ZCode desktop app is fine)
- [ZCode](https://zcode.z.ai) desktop app or CLI 0.16.x, logged in

**Install & register with Codex CLI**

One command, straight from this repository — no clone, no install:

```bash
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

`uvx` fetches the repo, builds an isolated environment from
`pyproject.toml` and exposes the `zcode-mcp` entry point — nothing to
install by hand. To pin a version, append `@<tag>` to the git URL.

**ZCode CLI path (`zcode.cjs`)** — the bridge drives ZCode through its CLI
entry, normally at `<ZCode install dir>/resources/glm/zcode.cjs`. It is
auto-detected from the common install locations (`%LOCALAPPDATA%/Programs/ZCode`,
`C:/Program Files/ZCode`, …). If your ZCode lives somewhere else, point the
`ZCODE_CJS` environment variable at it — either globally, or per-server in
the MCP registration:

```bash
codex mcp add zcode-mcp --env ZCODE_CJS="<install-dir>/resources/glm/zcode.cjs" -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

On Windows you can also add the directory that contains `zcode.cjs`
(`… esources\glm`) to the **system environment variable** `ZCODE_CJS`
(Settings → System → About → Advanced system settings → Environment
Variables) instead of per-server config — the bridge reads it either way.

Headless `codex exec` rejects MCP tool calls under its default approval
policy. For automation use `--dangerously-bypass-approvals-and-sandbox`
(after reviewing what your agents can reach) or `--approve-for-me`;
interactive Codex simply asks once.

**Other MCP clients** (Claude Code, Cursor, …): register the same command as
a stdio MCP server.

## Skills

This repository ships ready-made skill documents (for Codex and other
clients that read `SKILL.md` files): `zcode-mcp` (overview: tools, core
concepts, decision guide), `zcode-subagent` (orchestrating ZCode as a
subagent worker) and `zcode-code-reviewer` (read-only code review over a
diff).

To install them with Codex, copy the skill folders into the Codex skills
directory:

```bash
# macOS / Linux
cp -r skills/* ~/.codex/skills/

# Windows (PowerShell)
Copy-Item -Recurse -Force skills\* $env:USERPROFILE\.codex\skills```

## Tools

Two families, by design:

**Standalone** — no conversation needed:

| Tool             | Purpose                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `zcode_models` | Every session-addressable model with provider display names (`CPA/gpt-5.6-luna`), reasoning levels and context windows; also lists the desktop-managed account sources sessions cannot address |
| `zcode_quota`  | All plan quotas in one call: GLM Coding Plan windows and Start Plan token balances                                                   |
| `zcode_health` | Bridge, Node.js, ZCode CLI and app-server health check                                                                               |

**Conversation-scoped** — all take a `session_id`:

| Tool                          | Purpose                                                                               |
| ----------------------------- | ------------------------------------------------------------------------------------- |
| `zcode_session_new`         | New conversation + first message; blocks for the reply unless`wait: false`          |
| `zcode_session_send`        | Follow-up message (text and/or attachments)                                           |
| `zcode_session_status`      | Live state: model in use, turn state, pending interactions, events                    |
| `zcode_session_output`      | What the model has written so far in the running turn (poll-based), or the last reply |
| `zcode_session_result`      | Compact machine-readable result: status, reply, error, model                          |
| `zcode_session_diff`        | Git status / changed files / bounded diff for the worker's workspace                  |
| `zcode_session_read`        | Recent message history (idle conversations only)                                      |
| `zcode_session_wait`        | Block until the running turn ends; returns the reply                                  |
| `zcode_session_stop`        | Interrupt the running turn                                                            |
| `zcode_session_set_model`   | Switch the conversation's model (next message on)                                     |
| `zcode_session_permissions` | Pending permission / user-input requests                                              |
| `zcode_session_decide`      | Answer a pending request (allow/deny) — turn resumes                                 |
| `zcode_session_archive`     | Hide a conversation from lists (nothing deleted);`unarchive: true` restores         |
| `zcode_session_discard`     | Permanently delete (dry-run row counts unless`confirm: true`)                       |

### Parameters

#### `zcode_session_new`

| Parameter            | Type     | Default                        | Description                                                                                                                                      |
| -------------------- | -------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `text`             | string   | **required**             | First message to send.                                                                                                                           |
| `project`          | string   | —                             | Absolute path to an existing project directory; the conversation becomes project-scoped and edits land in that repo. Overrides`cwd`.           |
| `cwd`              | string   | `$ZCODE_MCP_WORKSPACE`       | Workspace directory (ignored when`project` is given).                                                                                          |
| `model`            | string   | `bigmodel-api/GLM-5.3-Flash` | Selector: `providerId/modelId`, `ProviderName/modelId` (e.g. `CPA/gpt-5.6-luna`), optionally `$reasoningLevel`. `high` is the preferred level when none is given. See `zcode_models`.       |
| `mode`             | enum     | `yolo`                       | `plan` / `build` / `edit` / `yolo` / `auto`. Non-yolo modes pause for approvals.                                                       |
| `temporary`        | boolean  | `false`                      | Throwaway conversation; pair with`zcode_session_discard`.                                                                                      |
| `files`            | string[] | —                             | Absolute paths of files to attach.                                                                                                               |
| `attachments`      | object[] | —                             | Raw ZCode attachment objects (advanced passthrough).                                                                                             |
| `title_generation` | boolean  | `false`                      | Let ZCode auto-generate the conversation title.                                                                                                  |
| `wait`             | boolean  | `true`                       | Block until the turn ends.                                                                                                                       |
| `timeout_sec`      | integer  | `600`                        | Max seconds to wait; capped by`ZCODE_MCP_TOOL_BUDGET` (default 240). On a cap hit the turn keeps running — call `zcode_session_wait` again. |

#### `zcode_session_send`

| Parameter                   | Type    | Default            | Description                                       |
| --------------------------- | ------- | ------------------ | ------------------------------------------------- |
| `session_id`              | string  | **required** | Target conversation (bridge- or desktop-created). |
| `text`                    | string  | **required** | Follow-up message text.                           |
| `files` / `attachments` | —      | —                 | Same as`zcode_session_new`.                     |
| `wait`                    | boolean | `true`           | Block until the turn ends.                        |
| `timeout_sec`             | integer | `600`            | Same budget cap as above.                         |

#### `zcode_session_status`

| Parameter      | Type   | Default            | Description          |
| -------------- | ------ | ------------------ | -------------------- |
| `session_id` | string | **required** | Target conversation. |

Returns `current_model`, `persisted_status` (desktop store; may lag),
`turn_state` (live), turn details and the pending-interaction count.

#### `zcode_session_output`

| Parameter      | Type    | Default            | Description                       |
| -------------- | ------- | ------------------ | --------------------------------- |
| `session_id` | string  | **required** | Target conversation.              |
| `max_chars`  | integer | `4000`           | Tail length of the returned text. |

#### `zcode_session_result`

| Parameter      | Type   | Default            | Description          |
| -------------- | ------ | ------------------ | -------------------- |
| `session_id` | string | **required** | Target conversation. |

#### `zcode_session_diff`

| Parameter        | Type    | Default            | Description                                       |
| ---------------- | ------- | ------------------ | ------------------------------------------------- |
| `session_id`   | string  | **required** | Target conversation (its workspace is inspected). |
| `include_diff` | boolean | `false`          | Include a bounded unified diff.                   |
| `max_chars`    | integer | `20000`          | Max diff characters when`include_diff` is on.   |

#### `zcode_session_read`

| Parameter         | Type    | Default            | Description                                      |
| ----------------- | ------- | ------------------ | ------------------------------------------------ |
| `session_id`    | string  | **required** | Target conversation (must have no running turn). |
| `message_limit` | integer | `50`             | How many recent messages to read.                |

#### `zcode_session_wait`

| Parameter       | Type    | Default            | Description                                                                                             |
| --------------- | ------- | ------------------ | ------------------------------------------------------------------------------------------------------- |
| `session_id`  | string  | **required** | Target conversation.                                                                                    |
| `timeout_sec` | integer | `600`            | Same budget cap as above. On timeout the note says whether the turn is streaming, producing or stalled. |

#### `zcode_session_stop`

| Parameter      | Type   | Default            | Description          |
| -------------- | ------ | ------------------ | -------------------- |
| `session_id` | string | **required** | Target conversation. |

#### `zcode_session_set_model`

| Parameter      | Type   | Default            | Description                                                      |
| -------------- | ------ | ------------------ | ---------------------------------------------------------------- |
| `session_id` | string | **required** | Target conversation.                                             |
| `model`      | string | **required** | `providerId/modelId`, `ProviderName/modelId`, or either + `$reasoningLevel`. |

#### `zcode_session_permissions`

| Parameter      | Type   | Default            | Description          |
| -------------- | ------ | ------------------ | -------------------- |
| `session_id` | string | **required** | Target conversation. |

#### `zcode_session_decide`

| Parameter      | Type    | Default            | Description                                                               |
| -------------- | ------- | ------------------ | ------------------------------------------------------------------------- |
| `request_id` | string  | **required** | Pending request id (from`zcode_session_permissions`).                   |
| `session_id` | string  | —                 | Validated against the pending request when given.                         |
| `approve`    | boolean | —                 | `true` → allow, `false` → deny.                                     |
| `decision`   | enum    | —                 | `allow` / `deny` / `escalate` / `modify` (overrides `approve`). |
| `reason`     | string  | —                 | Optional explanation attached to the decision.                            |

#### `zcode_session_archive`

| Parameter      | Type    | Default            | Description                 |
| -------------- | ------- | ------------------ | --------------------------- |
| `session_id` | string  | **required** | Target conversation.        |
| `unarchive`  | boolean | `false`          | Restore instead of archive. |

#### `zcode_session_discard`

| Parameter      | Type    | Default            | Description                                                       |
| -------------- | ------- | ------------------ | ----------------------------------------------------------------- |
| `session_id` | string  | **required** | Target conversation.                                              |
| `confirm`    | boolean | `false`          | `false` = dry-run (row counts); `true` = irreversible delete. |

#### `zcode_models` / `zcode_quota` / `zcode_health`

No parameters.

About model identity: sessions address providers the way ZCode's app-server
registry does (`~/.zcode/v2/provider_config.json`) — custom API providers keep
their config id (often a UUID), and all BigModel-family channels collapse into
one `bigmodel-api` provider whose display name is whatever that entry is called
(e.g. "BigModel Coding Plan"). Desktop account sources (BigModel 个人 / Start
Plan / Z.ai, the picker sections backed by a desktop login) are **not**
session-addressable; `zcode_models` lists them separately, and selecting one
by name returns guidance instead of a silent failure.

## Configuration (environment variables)

| Variable                    | Default                               | Purpose                                                                                                                                                  |
| --------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ZCODE_CJS`               | auto-detected                         | Path to the ZCode CLI entry (`<install dir>/resources/glm/zcode.cjs`). When unset, common install locations are scanned.                               |
| `ZCODE_MCP_WORKSPACE`     | `<repo>/sandbox`                    | Default workspace for`zcode_session_new`.                                                                                                              |
| `ZCODE_MCP_DEFAULT_MODEL` | `bigmodel-api/GLM-5.3-Flash`        | Model used when`zcode_session_new` gets no `model`.                                                                                                  |
| `ZCODE_MCP_TOOL_BUDGET`   | `240`                               | Cap for any single blocking tool call (seconds). MCP clients like Codex abort a tools/call at ~300s; the bridge returns a resumable timeout before that. |
| `ZCODE_MCP_DEBUG`         | off                                   | Verbose protocol logging (`bridge.log`, `child_dump.log`).                                                                                           |
| `ZCODE_MCP_NO_WARMUP`     | off                                   | Skip the app-server warm-up spawn.                                                                                                                       |
| `ZCODE_HOME`              | `~/.zcode`                          | Root of ZCode's shared stores.                                                                                                                           |
| `ZCODE_MCP_SESSION_DB`    | `$ZCODE_HOME/cli/db/db.sqlite`      | Override session store path.                                                                                                                             |
| `ZCODE_MCP_TASKS_INDEX`   | `$ZCODE_HOME/v2/tasks-index.sqlite` | Override desktop task-index path.                                                                                                                        |
| `ZCODE_MCP_CREDENTIALS`   | `$ZCODE_HOME/v2/credentials.json`   | Override OAuth credential store path (quota).                                                                                                            |
| `ZCODE_MCP_ZCODE_CONFIG`  | `$ZCODE_HOME/v2/config.json`        | Override provider config path (Start Plan balance).                                                                                                      |
| `ZCODE_MCP_PROVIDER_CONFIG` | `$ZCODE_HOME/v2/provider_config.json` | Override app-server provider registry path (model names & desktop-managed sources).                                                                      |
| `ZCODE_MCP_APP_VERSION`   | `3.14.4`                            | `app_version` sent to plan-quota endpoints.                                                                                                            |

## How it works

The bridge spawns one `zcode app-server` child and speaks ZCode Protocol
(newline-delimited JSON over stdio, no handshake): `session/create` →
`session/subscribe` → `session/send`, then it waits for the
`turn.completed` event, whose payload carries the full reply text.

Things we handle so you don't have to (all verified on ZCode 0.16.9):

- never call `session/read` while a turn runs — it silently aborts the turn;
- subscribe **before** send — a subscription only captures turns that start after it;
- `session/list` reports `idle` early (and all through model-retry windows) —
  completion is only trusted from events;
- the server's reverse requests (runtime preferences, plugin identity
  headers) are answered so sessions materialize without the desktop app.

Archive/discard are implemented against ZCode's two shared SQLite stores,
since the protocol itself has no such methods.

`ref/` (gitignored) may hold a shallow clone of the open-source tree
([zai-org/ZCode](https://github.com/zai-org/ZCode)) used as a protocol
reference during development; it is not part of the package.

## Known limitations

- Requires a local ZCode install; the app-server protocol is unofficial and
  may change between ZCode versions (tested against 0.16.9 / desktop 3.14.4).
- Preset official plugin MCPs (e.g. web search) start without desktop
  credentials in bridge-created sessions; the model and local tools are
  unaffected.
- Windows-first (default paths point at a Windows ZCode install); everything
  else is portable standard library.
- Don't discard a conversation the desktop app currently has open; discarding
  a running session is best-effort. `zcode_session_discard` is irreversible —
  always dry-run first.

## License

MIT
