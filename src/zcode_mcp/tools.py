"""MCP tool implementations and their schemas.

Each ``tool_*`` function maps to one MCP tool; ``TOOLS`` carries the MCP
input schemas and ``TOOL_IMPL`` dispatches names to implementations.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

from .appserver import NODE_EXE, SERVER
from . import config as _config
from .config import DEFAULT_MODEL, DEFAULT_TIMEOUT, DEFAULT_WS, log
from .protocol import (
    _message_texts,
    build_attachments,
    create_session,
    find_session,
    read_snapshot,
    run_turn,
    session_list,
    set_model,
    snapshot_last_reply,
    stop_session,
    subscribe,
    wait_turn,
)
from .models import (_norm_session_models, fetch_quota,
                     fetch_start_plan_balances, parse_model_selector)
from .store import (
    archived_session_ids,
    discard_scope,
    discard_session,
    session_exists,
    set_session_archived,
)


def _effective_timeout(args: dict) -> int:
    """Cap the caller's timeout at the client-safe tool budget."""
    budget = _config.TOOL_BUDGET
    return max(1, min(int(args.get("timeout_sec") or DEFAULT_TIMEOUT), budget))


def _ensure_catalogue(cwd: str | None = None) -> list:
    """Full model catalogue; probes with a throwaway session when cold."""
    available = _available_from_cache()
    if available:
        return available
    try:
        probe = create_session(cwd=cwd, mode="yolo",
                               title_generation=False, persistence="deferred")
    except Exception as e:
        raise RuntimeError(f"cannot probe model catalogue: {e}")
    try:
        SERVER.request("session/close", {"sessionId": probe}, timeout=15)
    except Exception:
        pass
    return _available_from_cache() or []


def _available_from_cache() -> list | None:
    """Simplified available-model list from the last session/create snapshot."""
    if SERVER.last_models is None:
        return None
    _, available = _norm_session_models({"settings": {"model": SERVER.last_models}})
    return available


def tool_zcode_session_new(args: dict) -> str:
    project = args.get("project")
    if project:
        project = os.path.abspath(project)
        if not os.path.isdir(project):
            return (
                f"error: project directory does not exist: {project}\n"
                "zcode_session_new(project=…) attaches the conversation to an EXISTING "
                "project; create it first or use cwd instead."
            )
        cwd = project
    else:
        cwd = args.get("cwd") or DEFAULT_WS
        os.makedirs(cwd, exist_ok=True)
    temporary = bool(args.get("temporary", False))
    try:
        _ensure_catalogue(cwd)
    except RuntimeError as e:
        if args.get("model"):
            return f"error: {e}"
        log(f"model catalogue probe failed ({e}); using runtime default")
    selection = None
    selector = args.get("model") or DEFAULT_MODEL
    if selector:
        try:
            selection = parse_model_selector(selector, _available_from_cache() or [])
        except ValueError as e:
            if args.get("model"):
                return f"error: {e}"
            log(f"default model {selector!r} unresolved ({e}); using runtime default")
            selection = None
    sid = create_session(
        cwd=cwd,
        mode=args.get("mode") or "yolo",
        title_generation=bool(args.get("title_generation", False)),
        persistence="deferred" if temporary else None,
    )
    if selection:
        # setModel is the canonical switch path; it applies the reasoning
        # level that session/create's model param dropped
        try:
            set_model(sid, selection)
        except RuntimeError as e:
            return f"session_id={sid}" + chr(10) + f"error: model switch failed: {e}"
    try:
        atts = build_attachments(args.get("files"))
    except FileNotFoundError as e:
        return f"error: {e}"
    atts += args.get("attachments") or []
    header = f"session_id={sid}\nworkspace={cwd}"
    if temporary:
        header += "\n(temporary conversation: discard it with zcode_session_discard when done)"
    if project:
        header += "\n(project conversation: ZCode edits files inside this project; "
        header += "the desktop app shows it under the project)"
    body = run_turn(
        sid, args.get("text", ""), atts or None, args.get("wait", True),
        _effective_timeout(args),
    )
    return f"{header}\n{body}"


def tool_zcode_session_send(args: dict) -> str:
    sid = args["session_id"]
    if find_session(sid) is None:
        return f"error: session not found: {sid}"
    try:
        atts = build_attachments(args.get("files"))
    except FileNotFoundError as e:
        return f"error: {e}"
    atts += args.get("attachments") or []
    return run_turn(
        sid, args.get("text", ""), atts or None, args.get("wait", True),
        _effective_timeout(args),
    )


def tool_zcode_session_list(args: dict) -> str:
    sessions = session_list()
    if not sessions:
        return "no sessions"
    include_archived = bool(args.get("include_archived", False))
    archived = archived_session_ids()
    sessions.sort(key=lambda s: s.get("updatedAt", 0), reverse=True)
    lines = [f"{'sessionId':40} {'status':10} {'mode':7} title (workspace)"]
    shown = 0
    for s in sessions:
        sid = s.get("sessionId", "?")
        if sid in archived and not include_archived:
            continue
        ws = (s.get("workspace") or {}).get("workspacePath", "?")
        marker = " [archived]" if sid in archived else ""
        lines.append(
            f"{sid:40} {s.get('status', '?'):10} {s.get('mode', '?'):7} "
            f"{s.get('title', '(untitled)')} ({ws}){marker}"
        )
        shown += 1
        if shown >= 30:
            break
    if not shown:
        lines.append("(all sessions archived; pass include_archived=true to see them)")
    return "\n".join(lines)


def tool_zcode_session_status(args: dict) -> str:
    sid = args["session_id"]
    mon = SERVER._monitor(sid)
    s = find_session(sid)
    if s is None and not mon.events:
        return f"error: session not found: {sid}"
    current_model = mon.current_model or (SERVER.last_models or {}).get("current")
    info = {
        "session_id": sid,
        "persisted_status": (s or {}).get("status"),
        "turn_state": mon.turn_state,
        "title": (s or {}).get("title"),
        "mode": (s or {}).get("mode"),
        "current_model": (
            f"{current_model.get('providerId')}/{current_model.get('modelId')}"
            + (
                f"${(current_model.get('options') or {}).get('reasoningLevel')}"
                if (current_model.get("options") or {}).get("reasoningLevel")
                else ""
            )
            if current_model
            else None
        ),
        "workspace": (s or {}).get("workspace", {}).get("workspacePath"),
        "updated_at": (s or {}).get("updatedAt"),
        "turn": {
            "state": mon.turn_state,
            "turn_id": mon.turn_id,
            "stream_chars": len("".join(mon.stream_text)),
            "last_result_type": mon.last_result_type,
            "last_error": mon.last_error or None,
        },
        "pending_interactions": len(SERVER.pending_for(sid)),
        "monitor": mon.summary(),
        "recent_events": [
            {"type": t, "age_s": round(time.time() - ts, 1)}
            for ts, t, _ in list(mon.events)[-8:]
        ],
    }
    return json.dumps(info, ensure_ascii=False, indent=1)


def tool_zcode_session_output(args: dict) -> str:
    sid = args["session_id"]
    max_chars = int(args.get("max_chars") or 4000)
    mon = SERVER._monitor(sid)
    if not mon.events:
        # never observed by this bridge: subscribe to backfill from replay
        try:
            snap = subscribe(sid, include_snapshot=True)
            if snap.get("snapshot"):
                pass  # replay events already fed into the monitor
        except Exception as e:
            log(f"backfill subscribe failed: {e}")
    parts = [f"session_id={sid}", f"turn_state={mon.turn_state}"]
    if mon.turn_state == "running":
        out = mon.current_output(max_chars)
        parts.append(
            f"streaming_output ({len(''.join(mon.stream_text))} chars so far):\n{out or '(no text yet)'}"
        )
    elif mon.last_response:
        resp = mon.last_response
        parts.append(f"last_response:\n{resp[-max_chars:]}")
    if mon.turn_state == "failed":
        parts.append(f"last_error: {mon.last_error}")
    recent = [t for _, t, _ in list(mon.events)[-5:]]
    parts.append(f"recent_events: {recent}")
    return "\n\n".join(parts)


def _session_context(sid: str) -> tuple[dict | None, Any]:
    """Return persisted session metadata and its live monitor."""
    return find_session(sid), SERVER._monitor(sid)


def tool_zcode_session_result(args: dict) -> str:
    """Return a compact, machine-readable worker result snapshot."""
    sid = args["session_id"]
    session, mon = _session_context(sid)
    if session is None and not mon.events:
        return f"error: session not found: {sid}"
    reply = mon.last_response
    if not reply and mon.turn_state != "running":
        try:
            reply = snapshot_last_reply(read_snapshot(sid))
        except Exception as e:
            log(f"result snapshot read failed for {sid}: {e}")
    model = mon.current_model or (SERVER.last_models or {}).get("current")
    result = {
        "session_id": sid,
        "status": mon.last_result_type or mon.turn_state,
        "turn_state": mon.turn_state,
        "reply": reply or None,
        "error": mon.last_error or None,
        "pending_interactions": len(SERVER.pending_for(sid)),
        "workspace": (session or {}).get("workspace", {}).get("workspacePath"),
        "mode": (session or {}).get("mode"),
        "current_model": (
            f"{model.get('providerId')}/{model.get('modelId')}"
            if model else None
        ),
    }
    return json.dumps(result, ensure_ascii=False, indent=1)


def _run_git(workspace: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", workspace, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )


def tool_zcode_session_diff(args: dict) -> str:
    """Summarize git changes in the worker's project workspace."""
    sid = args["session_id"]
    session = find_session(sid)
    if session is None:
        return f"error: session not found: {sid}"
    workspace = (session.get("workspace") or {}).get("workspacePath")
    if not workspace or not os.path.isdir(workspace):
        return f"error: workspace not found for session: {sid}"
    try:
        root = _run_git(workspace, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: cannot inspect git workspace: {e}"
    if root.returncode != 0:
        return json.dumps({"session_id": sid, "workspace": workspace, "is_git_repo": False}, ensure_ascii=False, indent=1)
    status = _run_git(workspace, "status", "--short")
    stat = _run_git(workspace, "diff", "HEAD", "--stat")
    name_status = _run_git(workspace, "diff", "HEAD", "--name-status")
    result = {
        "session_id": sid,
        "workspace": workspace,
        "is_git_repo": True,
        "root": root.stdout.strip(),
        "status": status.stdout.splitlines(),
        "changed_files": name_status.stdout.splitlines(),
        "stat": stat.stdout.strip(),
    }
    if args.get("include_diff"):
        max_chars = max(1, min(int(args.get("max_chars") or 20000), 100000))
        diff = _run_git(workspace, "diff", "HEAD", "--no-ext-diff", "--", ".")
        result["diff"] = diff.stdout[:max_chars]
        result["diff_truncated"] = len(diff.stdout) > max_chars
    return json.dumps(result, ensure_ascii=False, indent=1)


def tool_zcode_health(args: dict) -> str:
    """Report bridge and app-server health without creating a conversation."""
    try:
        zcode_cjs = _config.resolve_zcode_cjs()
        cjs_ok = os.path.isfile(zcode_cjs)
    except Exception as e:
        zcode_cjs = None
        cjs_ok = False
        cjs_error = str(e)
    proc = SERVER._proc
    app_state = "running" if proc is not None and proc.poll() is None else "not_started"
    result = {
        "bridge": "ok",
        "server_version": getattr(__import__("zcode_mcp"), "__version__", None),
        "node": {"executable": NODE_EXE, "available": shutil.which(NODE_EXE) is not None or os.path.isfile(NODE_EXE)},
        "zcode_cli": {"path": zcode_cjs, "available": cjs_ok},
        "app_server": {"state": app_state, "storage_ready": bool(getattr(SERVER, "_storage_ready", False))},
        "model_catalog_cached": SERVER.last_models is not None,
    }
    if not cjs_ok:
        result["zcode_cli"]["error"] = cjs_error
    return json.dumps(result, ensure_ascii=False, indent=1)


def tool_zcode_session_permissions(args: dict) -> str:
    sid = args["session_id"]
    parked = SERVER.pending_for(sid)
    if not parked:
        return f"session_id={sid}\nno pending permission/user-input requests"
    lines = []
    for p in parked:
        prm = p.get("params") or {}
        if p["kind"] == "permission":
            lines.append(
                f"request_id={p['request_id']} kind=permission\n"
                f"  tool={prm.get('toolName')} risk={prm.get('riskLevel')}\n"
                f"  reason={prm.get('reason')}\n"
                f"  input={json.dumps(prm.get('input'), ensure_ascii=False)[:400]}"
            )
        else:
            lines.append(
                f"request_id={p['request_id']} kind=user_input\n"
                f"  params={json.dumps(prm, ensure_ascii=False)[:500]}"
            )
    return f"session_id={sid}\n{len(parked)} pending:\n\n" + "\n\n".join(lines)


def tool_zcode_session_decide(args: dict) -> str:
    sid = args.get("session_id")
    rid = str(args["request_id"])
    parked = SERVER.pending_for(sid) if sid else []
    if parked and not any(p["request_id"] == rid for p in parked):
        return f"error: request {rid} is not pending on session {sid}"
    decision = args.get("decision")
    if args.get("approve") is not None:
        decision = "allow" if args.get("approve") else "deny"
    if decision not in ("allow", "deny", "escalate", "modify"):
        return "error: decision must be one of allow/deny/escalate/modify (or pass approve=true/false)"
    result: dict = {"decision": decision}
    if args.get("reason"):
        result["reason"] = str(args["reason"])
    try:
        SERVER.respond_interaction(rid, result)
    except KeyError:
        return f"error: no pending interaction {rid}"
    return (
        f"request_id={rid}\ndecision={decision} sent. The turn continues; "
        "collect the result with zcode_session_wait (or keep observing with "
        "zcode_session_status)."
    )


def tool_zcode_models(args: dict) -> str:
    """Standalone: the FULL model catalogue across all providers.

    Never requires or touches a session; probes the catalogue once when cold.
    Model identity is canonical ``providerId/modelId``.
    """
    try:
        available = _ensure_catalogue()
    except RuntimeError as e:
        return f"error: {e}"
    lines = [f"available models ({len(available)}):"]
    for m in available:
        lines.append(
            f"- {m['provider_id']}/{m['model_id']}  label={m.get('label')}  "
            f"provider={m.get('provider_label')}  ctx={m.get('context_window')}  "
            f"reasoning={m.get('reasoning_levels')} (default {m.get('default_reasoning')})"
        )
    lines.append("")
    lines.append(
        "selector: providerId/modelId or providerId/modelId$reasoningLevel "
        "(a bare modelId works only when unique across all providers)"
    )
    return chr(10).join(lines)


def tool_zcode_session_set_model(args: dict) -> str:
    sid = args["session_id"]
    # resolve against the FULL catalogue (cached from a model-less create):
    # after a set_model the session's own available list narrows to the chosen
    # provider, which would block cross-provider switches
    try:
        available = _ensure_catalogue()
    except RuntimeError as e:
        return f"error: {e}"
    try:
        selection = parse_model_selector(args["model"], available)
    except ValueError as e:
        return f"error: {e}"
    try:
        set_model(sid, selection)
    except RuntimeError as e:
        return f"session_id={sid}" + chr(10) + f"error: model switch failed: {e}"
    SERVER._monitor(sid).current_model = selection
    header = (
        f"session_id={sid}\n"
        f"model set to {selection['providerId']}/{selection['modelId']}"
    )
    if selection.get("options"):
        header += f" (reasoning: {selection['options']['reasoningLevel']})"
    return header + ". Takes effect from the next message."


def tool_zcode_quota(args: dict) -> str:
    """All plan quotas: Coding Plan windows + Start Plan token balances."""
    lines = []
    try:
        q = fetch_quota()
        lines.append(f"Coding Plan ({q['level']}):")
        for l in q["limits"]:
            reset = f"  next reset: {l['next_reset']}" if l.get("next_reset") else ""
            lines.append(
                f"- {l['window']}: used {l['used']} / limit {l['limit']} "
                f"(remaining {l['remaining']}, {l['percentage']}%){reset}"
            )
    except RuntimeError as e:
        lines.append(f"Coding Plan: unavailable ({e})")
    try:
        sp = fetch_start_plan_balances()
    except Exception as e:
        sp = [{"provider": "?", "error": str(e)}]
    for entry in sp or []:
        name = entry.get("plan") or entry.get("provider")
        if entry.get("error"):
            lines.append(f"Start Plan ({name}): unavailable ({entry['error']})")
            continue
        lines.append(f"Start Plan ({name}, status: {entry.get('status')}):")
        for b in entry.get("balances") or []:
            lines.append(
                f"- {b.get('model')}: used {b.get('used')} / total {b.get('total')} "
                f"(remaining {b.get('remaining')}, {b.get('percentage')}%)"
                + (f"  expires: {b.get('expires')}" if b.get("expires") else "")
            )
    if not lines:
        return "no plan quota information available"
    return chr(10).join(lines)


def tool_zcode_session_read(args: dict) -> str:
    snap = read_snapshot(args["session_id"], args.get("message_limit") or 50)
    lines = []
    for msg in snap.get("messages") or []:
        role, text = _message_texts(msg)
        if not text.strip():
            continue
        text = text if len(text) <= 400 else text[:400] + "…"
        lines.append(f"[{role or '?'}] {text}")
    if not lines:
        return json.dumps(snap, ensure_ascii=False)[:3000]
    return "\n\n".join(lines[-int(args.get("message_limit") or 20) :])


def tool_zcode_session_wait(args: dict) -> str:
    status, reply, note = wait_turn(args["session_id"], _effective_timeout(args))
    # NEVER session/read after a timeout — the turn may still be running and a
    # mid-turn read aborts it (0.16.9)
    if not reply and status != "timeout":
        try:
            reply = snapshot_last_reply(read_snapshot(args["session_id"]))
        except Exception:
            pass
    return (
        f"session_id={args['session_id']}\nstatus={status} ({note})\n\nreply:\n"
        f"{reply or '(none)'}"
    )


def tool_zcode_session_stop(args: dict) -> str:
    try:
        r = stop_session(args["session_id"])
    except RuntimeError as e:
        return f"stop error: {e}"
    return f"stop sent to {args['session_id']}. result: {json.dumps(r, ensure_ascii=False)[:500]}"


def tool_zcode_session_archive(args: dict) -> str:
    sid = args["session_id"]
    unarchive = bool(args.get("unarchive", False))
    if not session_exists(sid):
        return f"error: session not found in session store: {sid}"
    res = set_session_archived(sid, not unarchive)
    verb = "unarchived" if unarchive else "archived"
    return (
        f"session_id={sid}\n{verb}.\n"
        f"session store rows updated: {res.get('session_store_rows')} "
        f"(runtime picks this up on next app-server start)\n"
        f"desktop task-index rows updated: {res.get('task_index_rows')} "
        f"(0 is normal if the desktop has not synced this session yet)"
    )


def tool_zcode_session_discard(args: dict) -> str:
    sid = args["session_id"]
    confirm = bool(args.get("confirm", False))
    try:
        scope = discard_scope(sid)
    except Exception as e:
        return f"error: cannot inspect session store: {e}"
    if scope.get("session", 0) == 0:
        return f"error: session not found in session store: {sid}"
    total = sum(scope.values())
    if not confirm:
        rows = "\n".join(f"  {t}: {n}" for t, n in scope.items() if n)
        return (
            f"DRY RUN — discard would permanently delete {total} rows for {sid}:\n"
            f"{rows}\n"
            "Call again with confirm=true to execute. This cannot be undone."
        )
    # best-effort: end any active runtime for this session first
    try:
        stop_session(sid)
    except Exception:
        pass
    try:
        SERVER.request("session/close", {"sessionId": sid}, timeout=15)
    except Exception:
        pass
    deleted = discard_session(sid)
    total_deleted = sum(deleted.values())
    SERVER.monitors.pop(sid, None)
    return (
        f"session_id={sid}\ndiscarded: {total_deleted} rows permanently deleted "
        f"(session + history). It will disappear from zcode_list and the desktop "
        f"sidebar (task index flagged deleted)."
    )


FILES_DESC = (
    "Absolute paths of files to attach (like dragging into the ZCode composer). "
    "Kind is inferred from extension: image/pdf/audio/video/file."
)

TOOLS = [
    {
        "name": "zcode_session_new",
        "description": (
            "Open a NEW ZCode conversation (like a human typing in the ZCode desktop "
            "app), send the first message, and (default) block until the turn "
            "completes or fails. Returns session_id, terminal status and ZCode's "
            "reply text. While it runs, other agents can inspect progress with "
            "zcode_session_status / zcode_session_output. Pass project=<dir> to attach the "
            "conversation to an existing project directory (project-level "
            "conversation: shown under that project in the desktop app, ZCode "
            "edits files there)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Message text to send."},
                "project": {"type": "string",
                            "description": "Absolute path to an EXISTING project directory; "
                                           "creates a project-level conversation working in it. "
                                           "Overrides cwd."},
                "files": {"type": "array", "items": {"type": "string"}, "description": FILES_DESC},
                "attachments": {"type": "array", "items": {"type": "object"},
                                "description": "Raw ZCode attachment objects (advanced passthrough)."},
                "mode": {"type": "string", "enum": ["plan", "build", "edit", "yolo", "auto"],
                         "description": "Permission mode, default yolo."},
                "cwd": {"type": "string", "description": "Workspace directory for the new conversation "
                                                         "(ignored when project is given)."},
                "temporary": {"type": "boolean",
                              "description": "Create as a throwaway conversation (deferred persistence); "
                                             "pair with zcode_session_discard when done."},
                "model": {"type": "string",
                          "description": "Model selector for the conversation: modelId | "
                                         "providerId/modelId | providerId/modelId$reasoningLevel. "
                                         "Call zcode_models to list options."},
                "title_generation": {"type": "boolean"},
                "wait": {"type": "boolean", "description": "Block until the turn ends (default true)."},
                "timeout_sec": {"type": "integer", "description": "Max seconds to wait (default 600)."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "zcode_session_send",
        "description": (
            "Send a follow-up message (text and/or file/image attachments) to an "
            "EXISTING ZCode conversation by session_id — desktop-created sessions "
            "work too. Blocks until the turn completes, fails or is interrupted, "
            "then returns the reply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "text": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}, "description": FILES_DESC},
                "attachments": {"type": "array", "items": {"type": "object"}},
                "wait": {"type": "boolean"},
                "timeout_sec": {"type": "integer"},
            },
            "required": ["session_id", "text"],
        },
    },
    {
        "name": "zcode_session_list",
        "description": (
            "List ZCode conversations across all workspaces (id, status, mode, "
            "title). Archived conversations are hidden by default; pass "
            "include_archived=true to list them with an [archived] marker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_archived": {"type": "boolean"},
            },
        },
    },
    {
        "name": "zcode_session_status",
        "description": (
            "Observability: current state of a ZCode conversation — desktop status, "
            "turn state, buffered event history with ages. Cheap; call any time, "
            "even while another agent's zcode_new/zcode_send is still blocking."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_output",
        "description": (
            "Observability: the model's CURRENT streaming output for a session "
            "(text produced so far in the running turn), or the last completed "
            "response. Lets other agents see intermediate reasoning/answers "
            "instead of waiting blindly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "max_chars": {"type": "integer", "description": "Tail length, default 4000."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_result",
        "description": (
            "Return a compact machine-readable result for a worker session: status, "
            "reply, error, pending interactions, workspace and current model."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_diff",
        "description": (
            "Summarize git changes in a worker's project workspace. Set include_diff=true "
            "to include a bounded unified diff."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "include_diff": {"type": "boolean"},
                "max_chars": {"type": "integer", "description": "Maximum diff characters, default 20000."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_health",
        "description": "Check bridge, Node.js, ZCode CLI and app-server health without creating a conversation.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zcode_session_archive",
        "description": (
            "Archive a ZCode conversation: hidden from zcode_list (pass "
            "include_archived=true to see it) and from the desktop sidebar, "
            "but nothing is deleted and it can be restored. Pass "
            "unarchive=true to restore. Works on desktop-created and "
            "bridge-created conversations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "unarchive": {"type": "boolean", "description": "Restore instead of archive."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_discard",
        "description": (
            "PERMANENTLY delete a ZCode conversation (session + full history) — "
            "the throwaway counterpart of zcode_new(temporary=true). Without "
            "confirm=true returns a dry-run row count; with confirm=true deletes "
            "irreversibly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Must be true to actually delete."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_permissions",
        "description": (
            "List pending permission / user-input requests of a conversation in a "
            "non-yolo mode (the turn is paused until each is decided). Use "
            "zcode_decide to answer, then zcode_wait to collect the turn result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_decide",
        "description": (
            "Answer a pending permission (decision allow/deny, or approve=true/false) "
            "or user-input request of a paused conversation. The turn resumes "
            "immediately afterwards."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "request_id": {"type": "string"},
                "approve": {"type": "boolean",
                            "description": "true=allow / false=deny shorthand for permissions."},
                "decision": {"type": "string", "enum": ["allow", "deny", "escalate", "modify"]},
                "reason": {"type": "string"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "zcode_models",
        "description": (
            "Standalone: list ALL models across ALL providers configured in ZCode "
            "(built-in, Coding Plan / Start Plan, custom) with reasoning levels, "
            "context windows and input capabilities. No conversation required."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zcode_session_set_model",
        "description": (
            "Switch the model of an existing conversation (takes effect from the "
            "next message). Selector: modelId | providerId/modelId | "
            "providerId/modelId$reasoningLevel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["session_id", "model"],
        },
    },
    {
        "name": "zcode_quota",
        "description": (
            "GLM Coding Plan / Start Plan quota: per-window usage, remaining, "
            "percentage and next reset time, read via the local ZCode OAuth "
            "credentials. Requires the 'cryptography' package."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zcode_session_read",
        "description": "Read the recent messages of a ZCode conversation (role + text per message).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "message_limit": {"type": "integer"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_wait",
        "description": "Wait for the running turn of a ZCode conversation to end, then return its reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "timeout_sec": {"type": "integer"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "zcode_session_stop",
        "description": "Interrupt/stop the current turn of a ZCode conversation (session/stop).",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
]

TOOL_IMPL = {
    # conversation-scoped
    "zcode_session_new": tool_zcode_session_new,
    "zcode_session_send": tool_zcode_session_send,
    "zcode_session_list": tool_zcode_session_list,
    "zcode_session_status": tool_zcode_session_status,
    "zcode_session_result": tool_zcode_session_result,
    "zcode_session_diff": tool_zcode_session_diff,
    "zcode_session_output": tool_zcode_session_output,
    "zcode_session_read": tool_zcode_session_read,
    "zcode_session_wait": tool_zcode_session_wait,
    "zcode_session_stop": tool_zcode_session_stop,
    "zcode_session_archive": tool_zcode_session_archive,
    "zcode_session_discard": tool_zcode_session_discard,
    "zcode_session_permissions": tool_zcode_session_permissions,
    "zcode_session_decide": tool_zcode_session_decide,
    # standalone (no session required)
    "zcode_models": tool_zcode_models,
    "zcode_session_set_model": tool_zcode_session_set_model,
    "zcode_quota": tool_zcode_quota,
    "zcode_health": tool_zcode_health,
}
