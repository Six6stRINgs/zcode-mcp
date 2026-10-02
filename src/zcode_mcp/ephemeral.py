"""Auto-cleanup for temporary (subagent) conversations.

``zcode_session_new{temporary: true}`` registers the session here. A daemon
reaper discards it once ``ZCODE_MCP_TEMP_TTL`` seconds pass without any tool
call touching it (and no turn is still running); whatever survives is
discarded when the bridge process exits. The bridge owns this cleanup
because deferred persistence only protects EMPTY drafts — a temporary
session that exchanged messages lands in the shared store like any other
and would otherwise pollute the desktop sidebar.
"""

from __future__ import annotations

import atexit
import threading
import time

from . import config
from .config import log

_lock = threading.Lock()
_sessions: dict[str, float] = {}  # sid -> last-touch monotonic timestamp
_exit_hook_installed = False


def register(sid: str) -> None:
    """Track a new temporary conversation; starts the reaper on first use."""
    global _exit_hook_installed
    with _lock:
        _sessions[sid] = time.monotonic()
        cold = not _exit_hook_installed
        _exit_hook_installed = True
    if cold:
        atexit.register(discard_all_on_exit)
        threading.Thread(target=_reaper_loop, daemon=True, name="temp-reaper").start()


def touch(sid: str) -> None:
    """Refresh the idle clock when any tool call addresses the session."""
    with _lock:
        if sid in _sessions:
            _sessions[sid] = time.monotonic()


def is_temporary(sid: str) -> bool:
    with _lock:
        return sid in _sessions


def note(sid: str) -> str:
    """Hint for not-found errors when the session was already reaped."""
    if is_temporary(sid):
        return (
            f"note: {sid} was a temporary conversation and has already been "
            f"auto-discarded (idle > {config.TEMP_TTL}s); start a new one"
        )
    return ""


def _turn_running(sid: str) -> bool:
    from .appserver import SERVER

    try:
        return SERVER._monitor(sid).activity()["phase"] in ("streaming", "producing")
    except Exception:
        return False


def _reap_one(sid: str, force: bool = False) -> bool:
    from .store import discard_session

    if not force and _turn_running(sid):
        return False
    try:
        discard_session(sid)
    except Exception as e:
        log(f"temp reaper: discard {sid} failed: {e!r}")
        return False
    with _lock:
        _sessions.pop(sid, None)
    log(f"temp reaper: discarded temporary conversation {sid}")
    return True


def _due_sids(now: float, ttl: float) -> list[str]:
    with _lock:
        return [sid for sid, last in _sessions.items() if now - last > ttl]


def _reap_cycle(ttl: float | None = None) -> int:
    ttl = config.TEMP_TTL if ttl is None else ttl
    if ttl <= 0:
        return 0
    reaped = 0
    for sid in _due_sids(time.monotonic(), ttl):
        if _reap_one(sid):
            reaped += 1
    return reaped


def _reaper_loop() -> None:
    ttl = config.TEMP_TTL
    interval = max(5.0, min(15.0, ttl / 4.0)) if ttl > 0 else 15.0
    while True:
        time.sleep(interval)
        if config.TEMP_TTL <= 0:
            continue  # idle reaping disabled; exit discard still applies
        try:
            _reap_cycle()
        except Exception as e:
            log(f"temp reaper cycle failed: {e!r}")


def discard_all_on_exit() -> None:
    """Best-effort cleanup when the bridge process ends."""
    with _lock:
        sids = list(_sessions)
    for sid in sids:
        try:
            _reap_one(sid, force=True)
        except Exception:
            pass
