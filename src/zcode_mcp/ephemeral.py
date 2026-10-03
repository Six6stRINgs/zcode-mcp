"""Auto-cleanup for temporary (subagent) conversations.

``zcode_session_new{temporary: true}`` registers the session here. A daemon
reaper discards it once ``ZCODE_MCP_TEMP_TTL`` seconds pass without any tool
call touching it (and no turn is still running); whatever survives is
discarded when the bridge process exits. The bridge owns this cleanup
because deferred persistence only protects EMPTY drafts — a temporary
session that exchanged messages lands in the shared store like any other
and would otherwise pollute the desktop sidebar.

Safety rules, in order of importance:
- a session with a tool call currently executing on it (``begin``/``end``)
  is never reaped, so "actively orchestrated workers are never reaped
  mid-flight" is enforced, not just intended;
- a turn is only considered finished when the monitor saw it end; a
  session whose events were never observed (subscribe failed, bridge
  restarted) is treated as live and left to the exit discard;
- the runtime session is stopped and closed before the store rows go, so
  the app-server cannot resurrect rows after the DELETE.
"""

from __future__ import annotations

import atexit
import threading
import time

from . import config
from .config import log

_lock = threading.Lock()
_sessions: dict[str, float] = {}  # sid -> last-touch monotonic timestamp
_inflight: dict[str, int] = {}  # sid -> tool calls currently executing
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


def begin(sid: str) -> None:
    """Mark one tool call as executing on the session; the reaper defers."""
    with _lock:
        if sid in _sessions:
            _inflight[sid] = _inflight.get(sid, 0) + 1


def end(sid: str) -> None:
    """Release one in-flight mark taken by :func:`begin`."""
    with _lock:
        n = _inflight.get(sid)
        if n is None:
            return
        if n <= 1:
            del _inflight[sid]
        else:
            _inflight[sid] = n - 1


def forget(sid: str) -> None:
    """Drop the session from the registry (manual discard path)."""
    with _lock:
        _sessions.pop(sid, None)
        _inflight.pop(sid, None)


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
    """Whether a turn may still be live. Fails closed: a session whose
    events were never observed (subscribe failed) counts as live, and a
    ``running`` turn state counts as live even when the phase looks
    ``stalled`` (model-retry windows report exactly that)."""
    from .appserver import SERVER

    try:
        mon = SERVER._monitor(sid)
        if not mon.events:
            return True  # never observed: assume live
        return mon.turn_state == "running"
    except Exception:
        return True


def _end_runtime_session(sid: str) -> None:
    """Best-effort: stop the turn and close the runtime session so the
    app-server holds nothing that could resurrect rows after the DELETE."""
    try:
        from .protocol import stop_session

        stop_session(sid)
    except Exception:
        pass
    try:
        from .appserver import SERVER

        SERVER.request("session/close", {"sessionId": sid}, timeout=15)
    except Exception:
        pass


def _reap_one(sid: str, force: bool = False, ttl: float | None = None) -> bool:
    ttl = config.TEMP_TTL if ttl is None else ttl
    with _lock:
        if sid not in _sessions:
            return False
        if not force and (
            _inflight.get(sid) or time.monotonic() - _sessions[sid] <= ttl
        ):
            # a call is executing on it, or a touch landed after the reaper
            # cycle snapshot was taken (TOCTOU guard)
            return False
    if not force and _turn_running(sid):
        return False
    from .store import discard_session  # late import: tests monkeypatch it

    _end_runtime_session(sid)
    try:
        discard_session(sid)
    except Exception as e:
        log(f"temp reaper: discard {sid} failed: {e!r}")
        return False  # keep registered; the next cycle retries
    with _lock:
        _sessions.pop(sid, None)
        _inflight.pop(sid, None)
    try:
        from .appserver import SERVER

        SERVER.monitors.pop(sid, None)
    except Exception:
        pass
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
        if _reap_one(sid, ttl=ttl):
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
