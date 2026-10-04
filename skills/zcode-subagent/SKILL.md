---
name: zcode-subagent
description: "Use this skill when delegating implementation, review, research, or any multi-step coding task to ZCode as a subagent worker through the zcode-mcp tools (zcode_session_new / zcode_session_send / zcode_session_status / zcode_session_output / zcode_session_wait / zcode_session_stop / zcode_session_list / zcode_session_read / zcode_session_archive / zcode_session_discard). Triggers: the orchestrator wants a second agent to do work in parallel or in the background, wants ZCode to edit files in a project while Codex coordinates, or wants to replace the built-in subagent with a ZCode worker. Covers session patterns (blocking, fire-and-observe), project-level conversations, worker verification loops, and lifecycle hygiene."
---

# Driving ZCode as a subagent (zcode-mcp)

> Sub-skill of **zcode-mcp** (tool inventory, core concepts, decision guide).
> This file covers one specific usage: orchestrating ZCode as a subagent
> worker. Read the parent skill first if you are new to the tools.

## Overview

ZCode (Z.AI's agentic coding app) runs as an independent worker you drive over
MCP. You (the orchestrating agent) stay in charge: you decompose the task,
dispatch it to ZCode, observe progress mid-turn, verify the result, and decide
the next instruction. ZCode has its own model, its own tools, and edits real
files — treat it like a competent remote teammate, not a command line.

Core contract:

- Every conversation has a `session_id`; keep it for follow-ups.
- `zcode_session_new` / `zcode_session_send` **block** until the turn ends by default and
  return `status` + ZCode's reply text.
- With `wait: false` they return immediately; observe with `zcode_session_status` /
  `zcode_session_output` and collect with `zcode_session_wait`.

## Choosing the right session shape

| Goal | Call |
|---|---|
| Quick question / self-contained task, no file legacy | `zcode_session_new {text, temporary: true}` — auto-discarded after ~10 min idle (TTL configurable) or when the bridge exits; no cleanup call needed |
| **Work inside a real project** (edits must land in the repo, desktop shows it under the project) | `zcode_session_new {text, project: "D:/path/to/project"}` — the directory must already exist |
| Project worker you won't need afterwards | `zcode_session_new {text, project: …, temporary: true}` — the worker edits the project but the conversation auto-cleans instead of accumulating in the desktop sidebar |
| Long-lived worker for a project you'll come back to | `zcode_session_new {text, project: …}` (not temporary), `zcode_session_archive` when paused |
| Follow-up / course correction on an existing conversation | `zcode_session_send {session_id, text}` |
| Scratch sandbox work (no project) | `zcode_session_new {text}` (defaults to the bridge's sandbox workspace) |

`project` is the key parameter for subagent work: the conversation is attached
to that directory, ZCode reads/edits the project's real files, and the
conversation shows up in the desktop app under that project. Never use
`project` for throwaway questions — that litters the project's conversation
list; use `temporary: true` instead. `temporary` composes with `project`:
dispatch workers that way whenever you consume their report in the
orchestrator and don't need the conversation itself afterwards.

## Pattern A — blocking dispatch (simple, sequential)

Use for short tasks (< ~3 min) where you have nothing else to do meanwhile.

```
zcode_session_new {project: "…", text: "<task + acceptance criteria>"}
→ reply contains status=completed and the final report
→ verify (run tests, read the diff yourself), then zcode_session_send for fixes
```

Add `temporary: true` when the worker's report is all you need — the
conversation cleans itself up after you're done with it.

## Pattern B — fire-and-observe (parallel workers, long tasks)

Use for long tasks or several workers at once. Blocking calls are also
safe for long tasks now — the bridge caps them at 240s and returns a
resumable `timeout` (turn keeps running; call `zcode_session_wait` again) — but
fire-and-observe gives you progress visibility in between.

```
1. zcode_session_new {project: "…", text: "…", wait: false, temporary: true} → session_id at once
2. zcode_session_status {session_id}     → is the turn running? event history
3. zcode_session_output {session_id}     → the model's text so far (poll to refresh)
4. … do your own work; poll again later …
5. zcode_session_wait {session_id}        → final reply
6. zcode_session_result {session_id}     → structured terminal result
7. zcode_session_diff {session_id}       → verify workspace changes
```

Every `zcode_session_*` call on the worker refreshes its idle clock, so a
temporary worker being actively orchestrated is never reaped mid-flight;
reaping only targets conversations abandoned past the TTL while no turn is
running.

While workers run, you can dispatch more workers, answer the user, or review
partial output early and `zcode_session_stop {session_id}` a worker that went the
wrong way, then re-dispatch with `zcode_session_send`.

## The verification loop (you are the reviewer)

Never assume ZCode's reply means success — verify like you would a junior
dev's PR:

1. Read the `status` in the reply: `completed` / `failed` / `waiting_input` /
   `timeout`. A `completed (cancelled)` means it was interrupted.
2. Verify the workspace yourself: call `zcode_session_result` and `zcode_session_diff`,
   run the tests, read changed files, or dispatch a second ZCode session as a read-only reviewer
   (`zcode_session_new {project: …, mode: "plan", text: "review …, do not edit files"}`).
3. Feed concrete defects back with `zcode_session_send {session_id, text: "…"}` — the
   worker keeps its context, so corrections are cheap.
4. Cap the loop (2–3 rounds); if it still fails, stop and report to the user.

## Task text that works

ZCode starts with zero context about your conversation. Include in `text`:

- the goal and the acceptance criteria ("make X pass", "do not touch Y");
- exact paths (files, test commands) instead of "the thing we discussed";
- constraints: permission `mode` (`plan` for read-only/review workers,
  `yolo` only when autonomous edits are intended), what not to do;
- for follow-ups, reference what changed since ("your last change broke Z").

## Lifecycle hygiene

- Temporary conversations (`temporary: true`) clean themselves up — after
  ~10 min idle (TTL configurable via `ZCODE_MCP_TEMP_TTL`) or on bridge exit.
  `zcode_session_discard {session_id, confirm: true}` is only for early
  cleanup or for regular conversations you want gone now.
- Finished project conversation worth keeping → `zcode_session_archive {session_id}`.
- Paused worker you'll resume → leave it; `zcode_session_send` reactivates it later.
- `zcode_session_list {}` shows active conversations (archived hidden;
  temporary ones marked `[temporary]`);
  `zcode_session_list {include_archived: true}` shows everything with markers.

## Model choice per worker

- Dispatch with `zcode_session_new {project: …, model: "GLM-5.3-Flash", …}` to pin a
  worker's model; levels via `$high` / `$low` (default prefers `high`).
- **Quota exhaustion mid-task is a stop-and-ask event.** When a worker's
  model runs out of quota or its credentials cool down, do NOT pick
  another model yourself — pause and ask the user which model to continue
  on. Switch only when the user names one or explicitly authorized the
  switch in advance (`zcode_session_set_model` + `zcode_session_send` to
  resume). Unrequested switches may burn plans/balances the user never
  offered.
- `zcode_session_set_model {session_id, model}` is otherwise a
  user-requested operation (e.g. they want a stronger/cheaper brain for a
  phase), not a cost-saving move you make on your own.
- `zcode_quota {}` before committing to several long workers.

## Non-yolo workers (interactive permissions)

For work where autonomous edits are not acceptable, run the worker with
`mode: "build"` (or `edit`) instead of `yolo`. When the worker needs an
approval the turn pauses and your blocking call returns
`status=waiting_permission` with the pending request. Then:

```
zcode_session_permissions {session_id}                     → tool, reason, risk, input
zcode_session_decide {session_id, request_id, approve: …}  → turn resumes
zcode_session_wait {session_id}                            → final reply
```

You stay the approval gate: inspect `input` (file path, command) before
deciding. Use `wait: false` dispatch for the same flow without holding a
blocking call open.

## Failure handling

- `status=failed (turn failed: …)` → read the error; usually re-dispatch with
  a narrower task or fixed input. If the error is quota exhaustion or
  credential cooldown, stop and ask the user which model to continue on —
  never switch models on your own (see Model choice per worker).
- `status=waiting_input` → ZCode asked a question; answer via `zcode_session_send`.
- `status=timeout` → still running or stuck; check `zcode_session_output` to judge,
  then `zcode_session_wait` again or `zcode_session_stop`.
- Write errors inside a project → check the project path exists and you used
  `project:`, not a typo'd `cwd`.

## Anti-patterns

- Don't paste huge file contents into `text` — use `files` attachments; ZCode
  reads them from disk.
- Don't run two turns in the same session concurrently — `zcode_session_send` into a
  running session queues unpredictably; use separate sessions per worker.
- Don't use `yolo` for untrusted instructions on a real project; use `mode:
  "plan"` for review work.
- Don't forget the first `zcode_session_list` sanity call when tool discovery feels
  stale (MCP tools may be lazily listed).
