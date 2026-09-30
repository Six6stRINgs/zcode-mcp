**zcode-mcp** — MCP gateway into ZCode desktop conversations.

English | [中文](README_zh.md)

---

**Talk to [ZCode](https://zcode.z.ai) — Z.AI's agentic coding app — from any MCP
client** (Codex CLI, Claude Code, Cursor, your own agents): open conversations,
send follow-ups with file/image attachments, watch the model's output stream in
mid-turn, and collect the final reply. Built directly on ZCode's official
**app-server protocol** — the same channel the desktop app itself uses — so
bridged sessions are first-class conversations, visible in the desktop app.

Pure Python standard library. Zero runtime dependencies.

```
MCP client (Codex / Claude / your agent)        ZCode desktop app
        │  MCP (stdio JSON-RPC)                        ▲
        ▼                                              │ shared session store
zcode-mcp  ──ZCode Protocol NDJSON/stdio──►  zcode app-server (spawned)
```

## Highlights

- **Multi-turn conversations** — hold a session id, send follow-ups, correct course.
- **Mid-turn observability** — poll `zcode_status` / `zcode_output` while a turn
  runs and see the model's text as it streams. Coordinating agents can make
  informed decisions instead of waiting blind.
- **Interruptible** — `zcode_stop` cancels a running turn.
- **Native attachments** — files and images go through ZCode's own attachment
  pipeline, exactly like dragging them into the desktop composer.
- **Lifecycle control** — temporary throwaway conversations, archive/unarchive,
  and permanent discard.
- **Desktop interoperability** — sessions live in the shared store; the desktop
  app can list and resume them.
- **Fire-and-observe** — `wait: false` returns at once; collect later with
  `zcode_wait`, dodging MCP client tool timeouts on long tasks.
- **Interactive permissions** — non-yolo modes work: a paused turn surfaces
  its pending approval via `zcode_permissions`; the orchestrating agent
  decides with `zcode_decide` and the turn resumes.
- **Model selection & quota** — pick any model (built-in, Coding Plan /
  Start Plan providers) per conversation, switch mid-flight with reasoning
  levels (`high` preferred by default), and check plan quota windows with
  `zcode_quota` before you commit to a long task.

## Requirements & installation

**Requirements**

- Python ≥ 3.9 (stdlib only)
- Node.js (bundled with the ZCode desktop app is fine)
- [ZCode](https://zcode.z.ai) desktop app / CLI 0.16.x, logged in
- Optional: `cryptography` — only for `zcode_quota` (reads the plan quota
  with your local ZCode OAuth credentials)

**Get the code & register with Codex CLI**

```bash
git clone https://github.com/Six6stRINgs/zcode-mcp.git

# run straight from the clone (uv builds an isolated env for it)
codex mcp add zcode-mcp -- uvx --from "<path-to>/zcode-mcp" zcode-mcp

# or, once the package is on PyPI:
codex mcp add zcode-mcp -- uvx zcode-mcp

# or, from a published git repo without cloning:
codex mcp add zcode-mcp -- uvx --from "git+https://github.com/Six6stRINgs/zcode-mcp" zcode-mcp
```

No dependencies to install — `uvx` builds an isolated environment from
`pyproject.toml` automatically. (`pip install -e .` + the `zcode-mcp`
console entry point works too.)

Headless `codex exec` runs with approval policy `never`, which rejects MCP
tool calls; automation should use `--dangerously-bypass-approvals-and-sandbox`
(review what your agents can reach first) or `--approve-for-me`. Interactive
Codex just prompts once.

**Other MCP clients** (Claude Code, Cursor, …): register the same command as
a stdio MCP server.

Optional `pip install -e .` gives you a `zcode-mcp` console entry point.

## Tools

| Tool | Purpose |
|---|---|
| `zcode_new` | Open a new conversation, send the first message, block for the reply (or `wait: false` to fire-and-observe). `project: <dir>` attaches it to a project (project-level conversation); `temporary: true` creates a throwaway |
| `zcode_send` | Follow-up message to an existing conversation (desktop-created ones too), with `files` attachments |
| `zcode_status` | Current state: desktop status, turn state, buffered event history with ages |
| `zcode_output` | The model's **current streaming output**, or the last completed response |
| `zcode_read` | Recent message history (role + text) |
| `zcode_wait` | Block until the running turn ends; returns the reply |
| `zcode_stop` | Interrupt the running turn |
| `zcode_models` | Available models (built-in + Coding Plan / Start Plan) with reasoning levels, and the current selection |
| `zcode_set_model` | Switch a conversation's model (takes effect from the next message) |
| `zcode_quota` | GLM Coding Plan / Start Plan quota: per-window usage, remaining, next reset |
| `zcode_list` | All conversations across workspaces; archived ones hidden unless `include_archived: true` |
| `zcode_archive` | Archive a conversation (hidden from lists, nothing deleted); `unarchive: true` restores it |
| `zcode_discard` | **Permanently delete** a conversation (session + full history); dry-run row counts unless `confirm: true` |
| `zcode_permissions` | List pending permission / user-input requests pausing a non-yolo conversation |
| `zcode_decide` | Answer a pending request (allow/deny) — the turn resumes immediately |

### Parameters

#### `zcode_new`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `text` | string | **required** | Message text to send. |
| `project` | string | — | Absolute path to an **existing** project directory; creates a project-level conversation (desktop groups it under that project). Overrides `cwd`. |
| `cwd` | string | `$ZCODE_MCP_WORKSPACE` | Workspace directory for the conversation (ignored when `project` is given). |
| `mode` | enum | `yolo` | `plan` / `build` / `edit` / `yolo` / `auto` — permission mode. Non-yolo modes pause the turn for approvals (see `zcode_permissions`). |
| `temporary` | boolean | `false` | Throwaway conversation (deferred persistence); pair with `zcode_discard` when done. |
| `files` | string[] | — | Absolute paths of files to attach; kind (image/pdf/audio/video/file) inferred from extension. |
| `attachments` | object[] | — | Raw ZCode attachment objects (advanced passthrough). |
| `title_generation` | boolean | `false` | Let ZCode auto-generate the conversation title. |
| `wait` | boolean | `true` | Block until the turn ends; `false` returns `session_id` immediately. |
| `timeout_sec` | integer | `600` | Max seconds to wait when blocking (capped at `ZCODE_MCP_TOOL_BUDGET`, default 240 — the turn keeps running past it; call `zcode_wait` again to resume). |

#### `zcode_send`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation (bridge- or desktop-created). |
| `text` | string | **required** | Follow-up message text. |
| `files` / `attachments` | — | — | Same as `zcode_new`. |
| `mode` | enum | — | Not settable here; the session keeps its mode. |
| `wait` | boolean | `true` | Block until the turn ends. |
| `timeout_sec` | integer | `600` | Max seconds to wait when blocking (capped at `ZCODE_MCP_TOOL_BUDGET`, default 240 — the turn keeps running past it; call `zcode_wait` again to resume). |

#### `zcode_list`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_archived` | boolean | `false` | Also list archived conversations (marked `[archived]`). |

#### `zcode_status` / `zcode_permissions`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |

#### `zcode_output`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |
| `max_chars` | integer | `4000` | Tail length of the returned text. |

#### `zcode_decide`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `request_id` | string | **required** | The pending request (from `zcode_permissions`). |
| `session_id` | string | — | Validated against the pending request when given. |
| `approve` | boolean | — | Shorthand: `true` → `allow`, `false` → `deny`. |
| `decision` | enum | — | `allow` / `deny` / `escalate` / `modify` (overrides `approve`). |
| `reason` | string | — | Optional explanation attached to the decision. |

#### `zcode_read`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation (must have no running turn). |
| `message_limit` | integer | `50` | How many recent messages to read. |

#### `zcode_wait`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |
| `timeout_sec` | integer | `600` | Max seconds to wait (same budget cap; re-call `zcode_wait` to keep collecting). |

#### `zcode_archive`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |
| `unarchive` | boolean | `false` | `true` restores instead of archiving. |

#### `zcode_discard`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |
| `confirm` | boolean | `false` | `false` = dry-run (reports row counts); `true` = irreversible delete. |

#### `zcode_stop`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation whose running turn is interrupted. |

#### `zcode_models`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | — | Read that session's list; omit to use the catalogue cached from the last `zcode_new`. |

#### `zcode_set_model`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_id` | string | **required** | Target conversation. |
| `model` | string | **required** | `modelId` / `providerId/modelId` / `providerId/modelId$reasoningLevel`. When no level is given, `high` is preferred when the model supports it (otherwise the model's own default). |

#### `zcode_quota`

No parameters. Reads the GLM Coding Plan / Start Plan limit endpoint with
the local ZCode OAuth credentials (decrypted in-process, never logged).
Requires the optional `cryptography` package: `pip install "zcode-mcp[quota]"`.

### Observability pattern

```
1. zcode_new {text: "...", wait: false}     → fires, returns session_id at once
2. zcode_status {session_id}                → turn_state: running, events…
3. zcode_output {session_id}                → the model's text so far (streaming)
4. zcode_wait  {session_id}                 → final reply
```

A coordinating agent watches progress and bails out early — stop a turn that
is clearly going the wrong way, or start reviewing partial output before the
turn finishes.

### Model selection & quota

```
zcode_models {session_id}                              → what's available, current pick
zcode_new    {text, model: "GLM-5.3-Flash"}            → start on a chosen model
zcode_set_model {session_id, model: "…$reasoningLevel"} → switch mid-conversation
zcode_quota {}                                         → plan windows, remaining, reset times
```

Selector formats: `modelId`, `providerId/modelId`, or append
`$reasoningLevel`. With no level specified, `high` is preferred when the
model supports it. Handy when one provider's credentials are cooling down —
switch models and keep working.

### Skills

Ship-ready skill docs live in [`skills/`](skills/); copy what you need into
your client's skills directory (e.g. `~/.codex/skills/` for Codex):

- **[`zcode-mcp`](skills/zcode-mcp/SKILL.md)** — the overview: tool
  inventory, core concepts (session lifecycle, project vs temporary,
  observability), decision guide.
- **[`zcode-subagent`](skills/zcode-subagent/SKILL.md)** — orchestrating
  ZCode as a subagent worker: dispatch patterns, verification loops,
  per-project workers, lifecycle hygiene.

### Lifecycle: temporary, archive, discard

```
# throwaway Q&A — no clutter left behind
sid = zcode_new {text, temporary: true}     → deferred-persistence conversation
… use zcode_send / zcode_wait as usual …
zcode_discard {session_id: sid}             → dry-run: shows what would be deleted
zcode_discard {session_id: sid, confirm: true} → permanently deleted

# keep history but hide from lists
zcode_archive {session_id}                  → hidden from zcode_list + desktop sidebar
zcode_list {include_archived: true}         → shows it with an [archived] marker
zcode_archive {session_id, unarchive: true} → restored
```

Implementation notes: ZCode's protocol has no archive/delete method, so
zcode-mcp maintains the two shared stores directly — the session store
(`~/.zcode/cli/db/db.sqlite`, `session.time_archived`; the runtime hides
archived sessions from `session/list` on its next start) and the desktop task
index (`~/.zcode/v2/tasks-index.sqlite`, `tasks.archived` / `tasks.deleted`).
`discard` deletes rows scoped by exact session id in one transaction, after
best-effort `session/stop` + `session/close`; don't discard a conversation the
desktop currently has open. The running bridge filters archived sessions from
`zcode_list` itself, so hiding is effective immediately.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ZCODE_CJS` | auto-detected | Explicit path to the ZCode CLI entry (`<install dir>/resources/glm/zcode.cjs`). When unset, common install locations are scanned; a clear error names the searched paths if nothing is found |
| `ZCODE_MCP_WORKSPACE` | `<repo>/sandbox` | Default workspace for `zcode_new` |
| `ZCODE_MCP_DEBUG` | off | Verbose protocol logging (`bridge.log`, `child_dump.log`) |
| `ZCODE_MCP_NO_WARMUP` | off | Skip the app-server warm-up spawn |
| `ZCODE_MCP_TOOL_BUDGET` | `240` | Cap for any single blocking tool call (seconds). MCP clients like Codex abort a tools/call at ~300s; the bridge returns a resumable `timeout` status before that, and the turn keeps running — call `zcode_wait` again to continue collecting |
| `ZCODE_HOME` | `~/.zcode` | Root of ZCode's shared stores (archive/discard) |
| `ZCODE_MCP_SESSION_DB` | `$ZCODE_HOME/cli/db/db.sqlite` | Override session store path |
| `ZCODE_MCP_TASKS_INDEX` | `$ZCODE_HOME/v2/tasks-index.sqlite` | Override desktop task-index path |

## How it works

The bridge spawns one `zcode app-server` child and speaks ZCode Protocol
(newline-delimited JSON over stdio, no handshake):

- `session/create` → `session/subscribe` → `session/send`, then waits for the
  `turn.completed` event, whose payload carries the full reply text.
- Every `session/event` notification feeds a per-session ring buffer
  (`SessionMonitor`), which accumulates `model.streaming` text deltas — that
  is what `zcode_output` serves, even from other concurrent tool calls.
- Reverse requests from the server are answered: runtime preferences
  (three booleans) and official-MCP identity headers (empty identity, so the
  preset image-search plugin materializes without desktop credentials).

Protocol landmines we handle for you (verified on 0.16.9 — see
`src/zcode_mcp/appserver.py` module docstring):

- never call `session/read` mid-turn (it silently aborts the running turn);
- subscribe *before* send (a subscription only captures turns that start after it);
- `session/list.status` flips to `idle` early — completion must come from events.

`ref/ZCode` holds a shallow clone of the open-source tree
([zai-org/ZCode](https://github.com/zai-org/ZCode)) used as protocol
reference during development; it is not part of the package.

## Known limitations

- Requires a local ZCode install; the app-server protocol is unofficial and
  may change between ZCode versions (tested against 0.16.9).
- Preset official plugin MCPs (e.g. web search) start without desktop
  credentials in bridge-created sessions, so those specific tools may be
  unavailable there; the model and local tools are unaffected.
- Windows-first (paths default to a Windows ZCode install); everything else
  is portable stdlib.
- Archive/discard operate on the shared stores directly (no protocol support
  upstream). Don't discard a conversation the desktop app currently has open;
  a discard of a running session is best-effort. `zcode_discard` is
  irreversible — always do the dry-run first.

## License

MIT
