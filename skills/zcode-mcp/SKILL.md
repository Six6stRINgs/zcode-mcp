---
name: zcode-mcp
description: "Use this skill when working with the zcode-mcp MCP server: creating or continuing ZCode conversations (zcode_session_new, zcode_session_send), choosing or switching models (zcode_models, zcode_session_set_model, zcode_quota — GLM Coding Plan / Start Plan quota), observing a running turn (zcode_session_status, zcode_session_output), collecting replies (zcode_session_wait), interrupting (zcode_session_stop), deciding permission requests (zcode_session_permissions, zcode_session_decide), listing/reading conversations (zcode_session_list, zcode_session_read), or managing their lifecycle (zcode_session_archive, zcode_session_discard, temporary/project conversations). Triggers on any mention of zcode-mcp, driving ZCode over MCP, session_id handling, attachments, model selection, plan quota, or ZCode conversation lifecycle. For delegation/orchestration patterns (ZCode as a subagent worker), see the zcode-subagent skill."
---

# zcode-mcp: driving ZCode conversations over MCP

## Overview

zcode-mcp is an MCP server that bridges into [ZCode](https://zcode.z.ai)
desktop conversations. Every tool talks to a real ZCode conversation — the
same sessions the desktop app shows — so work done here is visible and
resumable there.

Two things to internalize before calling anything:

1. **Everything revolves around `session_id`.** Create once
   (`zcode_session_new` → returns `session_id`), then send follow-ups
   (`zcode_session_send`), observe (`zcode_session_status` / `zcode_session_output`), collect
   (`zcode_session_wait`), or dispose (`zcode_session_discard`).
2. **Calls either block or don't.** By default `zcode_session_new` / `zcode_session_send`
   block until the turn ends and return `status` + ZCode's reply text.
   Blocking calls are capped at `ZCODE_MCP_TOOL_BUDGET` (240s) — under MCP
   clients' ~300s tools/call abort — and a cap hit returns a resumable
   `timeout` status while the turn keeps running: just call `zcode_session_wait`
   again. `wait: false` returns `session_id` immediately if you prefer
   explicit polling.

## Tools

| Tool | Returns / does |
|---|---|
| `zcode_session_new` | New conversation; first reply. Key params: `project`, `model`, `temporary`, `mode`, `wait`, `files` |
| `zcode_session_send` | Follow-up to `session_id`; same blocking semantics |
| `zcode_session_status` | JSON state: desktop status, turn state, recent events with ages |
| `zcode_session_output` | Model's current streaming text, or last completed response |
| `zcode_session_wait` | Block until the running turn ends; final reply |
| `zcode_session_result` | Structured worker result for orchestration |
| `zcode_session_diff` | Git status, changed files, and optional bounded diff |
| `zcode_health` | Bridge, Node.js, ZCode CLI, app-server and catalogue health |
| `zcode_session_stop` | Interrupt the running turn |
| `zcode_models` | Standalone: FULL model catalogue across all providers |
| `zcode_session_set_model` | Switch a conversation's model mid-flight |
| `zcode_quota` | GLM Coding Plan / Start Plan quota windows |
| `zcode_session_permissions` | Pending permission/user-input requests pausing a non-yolo turn |
| `zcode_session_decide` | Answer a pending request (allow/deny) — turn resumes |
| `zcode_session_list` | Conversations across workspaces (`include_archived` to see archived) |
| `zcode_session_read` | Recent messages of a conversation (only when no turn is running) |
| `zcode_session_archive` / `unarchive` | Hide from lists (nothing deleted) / restore |
| `zcode_session_discard` | Permanently delete; dry-run row counts unless `confirm: true` |

## Core concepts

### Workspace: project vs sandbox vs temporary

- `zcode_session_new {project: "D:/path/to/project"}` — **project-level
  conversation**: attached to an existing directory, ZCode edits its real
  files, the desktop app groups it under that project. Use for any work
  that should land in a repo.
- `zcode_session_new {text}` without `project` — lands in the bridge's sandbox
  workspace (env `ZCODE_MCP_WORKSPACE`); fine for questions and scratch.
- `temporary: true` — throwaway conversation; pair with
  `zcode_session_discard {session_id, confirm: true}` when done (dry-run first
  without `confirm`).
- `zcode_session_archive {session_id}` — keep history, hide from lists;
  `unarchive: true` restores.

### Permission `mode`

`plan` (read-only/review) · `build` · `edit` · `yolo` (autonomous edits —
default). Pick `plan` for reviewer workers, `yolo` only when the worker is
meant to actually change files.

### Attachments

`files: ["<abs path>", …]` — like dragging into the desktop composer;
kind (image/pdf/audio/video/file) is inferred. Prefer this over pasting
contents into `text`.

### Model selection & quota

- `zcode_models {}` — the FULL catalogue across all providers (standalone)
  (built-in, Coding Plan / Start Plan, custom), never narrowed by previous
  switches, plus the session's current pick. Probes the catalogue on first
  use when cold.
- Selectors — canonical: `providerId/modelId`, optionally with
  `$reasoningLevel` (`GLM-5.3-Flash$low`). A bare `modelId` resolves only
  when unique across all providers. With no level, `high` is preferred
  when the model supports it.
- `zcode_session_new {model: …}` starts a conversation on that model; a cold bridge
  first probes the catalogue with a throwaway session (invisible).
- **Default:** without `model`, conversations run on the built-in
  `GLM-5.3-Flash` (reasoning `high`) — overridable via
  `ZCODE_MCP_DEFAULT_MODEL`.
- `zcode_session_set_model {session_id, model}` switches mid-conversation; applies
  from the next message. After a switch the session's own list narrows to
  that provider — resolution uses the full cached catalogue, so
  cross-provider switches keep working.
- `zcode_quota {}` — plan windows (used / remaining / percentage / next
  reset). Needs the optional `cryptography` package. Check before long
  tasks; if a provider's credentials are cooling down, switch models.
- **Default model:** without `model`, `zcode_session_new` uses the
  built-in `bigmodel-api/GLM-5.3-Flash` at reasoning `high`
  (`ZCODE_MCP_DEFAULT_MODEL` overrides).

### Observing a running turn

```
zcode_session_status {session_id}   → turn_state, event ages — cheap, any time
zcode_session_output {session_id}   → the model's text so far (streaming)
zcode_session_result {session_id}   → structured terminal result for orchestration
```

Statuses you can see from a blocked/collected turn:
`completed` · `completed (cancelled)` · `failed (…)` · `waiting_input`
(ZCode asked a question — answer via `zcode_session_send`) · `waiting_permission`
(approval needed — `zcode_session_permissions` then `zcode_session_decide`, turn resumes) · `timeout`.

## Decision guide

- One-off question, nothing to clean → `zcode_session_new {temporary: true}`, read reply, `zcode_session_discard`.
- Task touching a repo → `zcode_session_new {project: …}`; verify the workspace
  yourself afterwards with `zcode_session_result`, `zcode_session_diff`, tests, and diffs.
- Long or parallel work → `wait: false`, poll `zcode_session_status`/`zcode_session_output`,
  collect with `zcode_session_wait`; `zcode_session_stop` a worker going the wrong way.
- Follow-up/correction → `zcode_session_send {session_id, …}` — the worker keeps
  its context.
- Lost track of sessions → `zcode_session_list` (add `include_archived: true` if
  needed).
- A worker reports credential cooldown / usage limit →
  `zcode_session_set_model` to another provider and `zcode_session_send` to retry.
- Before a long expensive task → `zcode_quota` to check remaining windows.

## Sub-skills

- **`zcode-subagent`** — orchestrating ZCode as a subagent worker:
  dispatch patterns, verification loops, per-project workers, lifecycle
  hygiene. Read it before building multi-worker or A2A flows.

(Reads as a living index; new sub-skills will be added under the same
`skills/` directory of the zcode-mcp repository.)

## Caveats

- Codex headless (`codex exec`) rejects MCP calls under its default
  approval policy — use `--dangerously-bypass-approvals-and-sandbox` or
  `--approve-for-me` for automation.
- Keep `text` concise and self-contained (ZCode starts with zero context:
  goals, acceptance criteria, exact paths); move bulk content into `files`.
- Never expect a reply mid-turn from `zcode_session_read` — read only idle
  conversations; use `zcode_session_output` for running ones.
