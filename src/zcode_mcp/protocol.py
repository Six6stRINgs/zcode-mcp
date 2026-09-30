"""Session operations over the ZCode Protocol.

High-level wrappers around the raw app-server methods (see appserver.py for
wire details): session lifecycle, messaging, attachments, turn waiting and
snapshot parsing.
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import time
from typing import Any

from .appserver import SERVER
from .config import (
    AUDIO_EXT,
    DEFAULT_TIMEOUT,
    DEFAULT_WS,
    DELIVERY_KIND,
    IMAGE_EXT,
    TERMINAL_STATUSES,
    VIDEO_EXT,
    log,
)


def _norm_ws(cwd: str | None) -> dict[str, str]:
    ws = os.path.abspath(cwd or DEFAULT_WS)
    return {"workspacePath": ws, "workspaceKey": ws}


def session_list() -> list[dict]:
    return SERVER.request("session/list", {}, timeout=30).get("sessions", [])


def find_session(sid: str) -> dict | None:
    for s in session_list():
        if s.get("sessionId") == sid:
            return s
    return None


def create_session(
    cwd: str | None = None,
    mode: str = "yolo",
    title_generation: bool = False,
    persistence: str | None = None,
    model: dict | None = None,
) -> str:
    params: dict = {
        "workspace": _norm_ws(cwd),
        "mode": mode,
        "titleGenerationEnabled": bool(title_generation),
    }
    if persistence:
        params["persistence"] = persistence
    if model:
        params["model"] = model
    r = SERVER.request("session/create", params, timeout=60)
    # cache the FULL catalogue only: creating with a model narrows the
    # session's available list to that provider
    if isinstance(r, dict) and not model and (r.get("settings") or {}).get("model"):
        SERVER.last_models = r["settings"]["model"]
    sid = ""
    if isinstance(r, dict):
        sid = r.get("sessionId") or ((r.get("session") or {}).get("sessionId") or "")
    if not sid:
        raise RuntimeError(
            f"session/create returned no sessionId: {json.dumps(r, ensure_ascii=False)[:300]}"
        )
    return sid


def subscribe(sid: str, include_snapshot: bool = False) -> dict:
    r = SERVER.request(
        "session/subscribe",
        {
            "sessionId": sid,
            "deliveryKind": DELIVERY_KIND,
            "includeSnapshot": include_snapshot,
        },
        timeout=30,
    )
    # feed replayed events into the monitor so buffers survive bridge restarts
    mon = SERVER._monitor(sid)
    for env in (r or {}).get("events") or []:
        mon.feed(env)
    return r or {}


def send_message(sid: str, text: str, attachments: list | None = None) -> Any:
    params: dict = {"sessionId": sid, "content": text}
    if attachments:
        params["attachments"] = attachments
    return SERVER.request("session/send", params, timeout=30)


def set_model(sid: str, selection: dict) -> dict:
    return SERVER.request(
        "session/setModel", {"sessionId": sid, "model": selection}, timeout=30
    )


def stop_session(sid: str) -> Any:
    return SERVER.request("session/stop", {"sessionId": sid}, timeout=30)


def read_snapshot(sid: str, message_limit: int = 50) -> dict:
    return SERVER.request(
        "session/read",
        {"sessionId": sid, "messageLimit": message_limit},
        timeout=30,
    )


def attachment_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    return "file"


def build_attachments(paths: list[str]) -> list[dict]:
    """Protocol attachments per ZCodePromptAttachment.

    Desktop ZCode sends ``localPath`` for zero-copy file access, which works
    because the bridge and the app-server share this machine.
    """
    out = []
    for p in paths or []:
        ap = os.path.abspath(p)
        if not os.path.isfile(ap):
            raise FileNotFoundError(f"attachment not found: {ap}")
        mime = mimetypes.guess_type(ap)[0] or "application/octet-stream"
        out.append(
            {
                "kind": attachment_kind(ap),
                "filename": os.path.basename(ap),
                "mimeType": mime,
                "localPath": ap,
                "sizeBytes": os.path.getsize(ap),
            }
        )
    return out


def _message_texts(msg: dict) -> tuple[str, str]:
    texts = []
    for part in msg.get("parts") or []:
        if (
            isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and not part.get("ignored")
        ):
            texts.append(part["text"])
    info = msg.get("info")
    role = ""
    if isinstance(info, dict):
        role = str(info.get("role") or info.get("sender") or "")
    return role, "\n".join(texts)


def snapshot_last_reply(snapshot: dict) -> str:
    best = ""
    for msg in (snapshot or {}).get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role, text = _message_texts(msg)
        if text.strip() and "assistant" in role.lower():
            best = text
    return best.strip()


def wait_turn(sid: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, str, str]:
    """Block until the current turn ends; return (status, reply, note).

    Primary signal is the ``turn.completed`` / ``turn.failed`` /
    ``userInput.requested`` event stream (subscribe BEFORE send). Status
    polling is only a fallback and never calls ``session/read`` — a mid-turn
    read aborts the running turn in 0.16.9.
    """
    q = SERVER.event_waiter(sid)
    mon = SERVER._monitor(sid)
    t0 = time.time()
    last_event_at = t0
    next_poll = t0 + 5
    idle_since: float | None = None
    while time.time() - t0 < timeout:
        # a parked permission/user-input request blocks the turn on the
        # runtime side; surface it immediately instead of waiting for events
        try:
            parked = SERVER.pending_for(sid)
        except Exception:
            parked = []
        if parked:
            kinds = {p["kind"] for p in parked}
            if "permission" in kinds:
                return "waiting_permission", "", json.dumps(parked, ensure_ascii=False)
            return "waiting_input", "", json.dumps(parked, ensure_ascii=False)
        try:
            env = q.get(timeout=1.5)
            last_event_at = time.time()
            etype = env.get("type")
            payload = env.get("payload") or {}
            if etype == "turn.completed":
                rt = str(payload.get("resultType") or "success")
                note = "completed" if rt == "success" else f"completed ({rt})"
                return "completed", str(payload.get("response") or ""), note
            if etype == "turn.failed":
                err = payload.get("error") or {}
                msg = (
                    err.get("message", "unknown error")
                    if isinstance(err, dict)
                    else str(err)
                )
                return "failed", "", f"turn failed: {msg}"
            if etype == "userInput.requested":
                return "waiting_input", "", "session is asking the user a question"
        except queue.Empty:
            pass
        now = time.time()
        if now >= next_poll:
            next_poll = now + 5
            try:
                s = find_session(sid)
            except Exception:
                s = None
            if s is None:
                return "error", "", "session disappeared from session/list"
            st = s.get("status")
            if st == "waiting":
                return "waiting_input", "", "session is waiting for user input"
            if st in TERMINAL_STATUSES and st != "idle":
                return st, "", f"session status: {st}"
            if st == "idle":
                idle_since = idle_since or now
                # session/list flips to idle early — during long model-retry
                # windows the runtime reports idle while the turn is still
                # live (a follow-up send then fails with -32010). Only trust
                # the idle status when the monitor never saw this turn start;
                # a started turn must be finished by its own completion event.
                if mon.turn_state != "running" and (
                    now - last_event_at > 20 and now - idle_since > 15
                ):
                    try:
                        reply = snapshot_last_reply(read_snapshot(sid))
                    except Exception as e:
                        log(f"snapshot read failed: {e}")
                        reply = ""
                    return "completed", reply, "completed (poll, events quiet)"
            else:
                idle_since = None
    if mon.turn_state == "running":
        note = (
            "no terminal event after {t}s — the turn is still live (possibly "
            "retrying the model request); poll zcode_status / zcode_output, "
            "or zcode_wait again"
        ).format(t=timeout)
    else:
        note = f"no terminal event after {timeout}s"
    return "timeout", "", note


def run_turn(
    sid: str, text: str, attachments: list | None, wait: bool, timeout: int | None
) -> str:
    """Send a message and (optionally) block for the reply; shared by new/send."""
    # subscription must precede send: only turns that START while subscribed
    # deliver session/event notifications
    try:
        subscribe(sid)
    except Exception as e:
        log(f"subscribe failed ({e}); will rely on status polling")
    send_message(sid, text, attachments)
    if not wait:
        return (
            f"accepted. session_id={sid}\n"
            "observe with zcode_status / zcode_output; collect with zcode_wait."
        )
    status, reply, note = wait_turn(sid, timeout or DEFAULT_TIMEOUT)
    if status in ("waiting_permission", "waiting_input"):
        return (
            f"session_id={sid}\nstatus={status}\npending={note}\n\n"
            "The turn is paused until you decide: call zcode_decide for each "
            "pending request, then collect with zcode_wait."
        )
    if not reply and status == "waiting_input":
        try:
            reply = snapshot_last_reply(read_snapshot(sid))
        except Exception:
            pass
    return f"session_id={sid}\nstatus={status} ({note})\n\nreply:\n{reply or '(none)'}"
