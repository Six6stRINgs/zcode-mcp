"""ZCode Protocol app-server child management.

Speaks the official ZCode Protocol (verified against zcode 0.16.9 and the
open-source tree at github.com/zai-org/ZCode) over NDJSON stdio:

- Envelope ``{id, method, params}`` (no "jsonrpc" field). Responses:
  ``{id, result}`` / ``{id, error}``. No handshake method; just connect.
- The server issues reverse requests that MUST be answered:
  * ``session/requestRuntimePreferences`` -> three booleans (see
    config.RUNTIME_PREFS_RESULT).
  * ``interaction/requestOfficialMcpAuthHeaders`` -> answered
    ``{"ok": true, "headers": {}}`` so the preset image-search plugin
    materializes with an empty identity; replying ``ok: false`` aborts the
    whole turn in 0.16.9.
- Events arrive as ``session/event`` notifications (envelope with
  ``sessionId``, ``seq``, ``type``, ``payload``). ``turn.completed``
  carries the full reply in ``payload.response``.
- A subscription only captures turns that START after ``session/subscribe``,
  so always subscribe before sending.
- NEVER call ``session/read`` while a turn may be running: in 0.16.9 a
  mid-turn read silently aborts the running turn (no messages persisted,
  model request killed). ``session/list`` ``status`` also flips to ``idle``
  early and must not be used as a completion signal.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

from .config import (
    DEBUG,
    DEFAULT_WS,
    RAW_DUMP,
    RUNTIME_PREFS_RESULT,
    log,
    resolve_zcode_cjs,
)
from .monitor import SessionMonitor

# GUI hosts may launch us with a PATH that lacks node; resolve once and fall
# back to each platform's standard install location (then to bare "node").
_NODE_FALLBACKS = [
    "C:/Program Files/nodejs/node.exe",  # Windows
    "/usr/local/bin/node",  # macOS / Linux (source, Homebrew Intel)
    "/opt/homebrew/bin/node",  # macOS (Homebrew ARM)
    "/usr/bin/node",
]


def _resolve_node() -> str:
    found = shutil.which("node")
    if found:
        return found
    for candidate in _NODE_FALLBACKS:
        if os.path.isfile(candidate):
            return candidate
    return "node"


NODE_EXE = _resolve_node()


class AppServer:
    """One persistent ``zcode app-server`` child; thread-safe request()."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._spawn_lock = threading.Lock()
        self._write_lock = threading.Lock()  # stdin writes come from 2 threads
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._event_waiters: dict[str, queue.Queue] = {}
        self._waiters_lock = threading.Lock()
        self.monitors: dict[str, SessionMonitor] = {}
        self._monitors_lock = threading.Lock()
        # interaction reverse requests awaiting a decision, keyed by requestId:
        # {"kind": "permission"|"user_input", "session_id", "params", "protocol_request_id"}
        self.pending_interactions: dict[str, dict] = {}
        self._interactions_lock = threading.Lock()
        self._ids = itertools.count(1)
        self.last_models: dict | None = None
        atexit.register(self.shutdown)

    # -- lifecycle ---------------------------------------------------------

    def _spawn(self) -> None:
        zcode_cjs = resolve_zcode_cjs()  # may raise with actionable guidance
        log(f"spawning app-server (cwd={DEFAULT_WS}, zcode.cjs={zcode_cjs})")
        t0 = time.time()
        os.makedirs(DEFAULT_WS, exist_ok=True)
        # a fresh child invalidates every parked interaction from the old one
        with self._interactions_lock:
            self.pending_interactions.clear()
        self._proc = subprocess.Popen(
            [NODE_EXE, zcode_cjs, "app-server", "--cwd", DEFAULT_WS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        log(f"app-server pid={self._proc.pid} spawned in {time.time() - t0:.2f}s")
        threading.Thread(target=self._reader, daemon=True).start()
        deadline = time.time() + 30
        while time.time() < deadline:
            if getattr(self, "_storage_ready", False):
                log(f"storage ready after {time.time() - t0:.2f}s")
                return
            if self._proc.poll() is not None:
                raise RuntimeError("app-server exited during startup")
            time.sleep(0.2)
        log("storage readiness wait timed out; continuing anyway")

    def ensure(self) -> subprocess.Popen:
        with self._spawn_lock:
            if self._proc is None or self._proc.poll() is not None:
                self._storage_ready = False
                self._spawn()
            return self._proc

    def shutdown(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass

    # -- wire ---------------------------------------------------------------

    def _send_line(self, obj: dict) -> None:
        proc = self.ensure()
        line = json.dumps(obj, ensure_ascii=False)
        if DEBUG:
            log(f">>> {line[:300]}")
        try:
            with self._write_lock:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            log("write failed; respawning app-server")
            with self._spawn_lock:
                self._proc = None
            proc = self.ensure()
            with self._write_lock:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()

    def _reader(self) -> None:
        assert self._proc is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            if DEBUG:
                try:
                    with open(RAW_DUMP, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    pass
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = m.get("method")
            if method == "startup/storageState":
                if (m.get("params") or {}).get("phase") == "ready":
                    self._storage_ready = True
                continue
            if method == "session/event":
                self._dispatch_event(m.get("params") or {})
                continue
            if DEBUG:
                log(f"<<< {json.dumps(m, ensure_ascii=False)[:300]}")
            if method and "id" in m:  # server -> client request
                self._answer_server_request(m)
            elif "id" in m:
                with self._pending_lock:
                    q = self._pending.pop(m["id"], None)
                if q:
                    q.put(m)
        log("app-server stdout closed")

    def _monitor(self, sid: str) -> SessionMonitor:
        with self._monitors_lock:
            mon = self.monitors.get(sid)
            if mon is None:
                mon = self.monitors[sid] = SessionMonitor()
            return mon

    def _dispatch_event(self, env: dict) -> None:
        sid = env.get("sessionId")
        if not sid:
            return
        self._monitor(sid).feed(env)
        with self._waiters_lock:
            q = self._event_waiters.get(sid)
        if q:
            q.put(env)

    def _answer_server_request(self, m: dict) -> None:
        result: dict = {}
        if m["method"] == "session/requestRuntimePreferences":
            result = dict(RUNTIME_PREFS_RESULT)
        elif m["method"] in ("interaction/requestPermission", "interaction/requestUserInput"):
            # The runtime pauses the turn until we answer. Stash the request so
            # an orchestrating agent can decide via zcode_decide (permissions)
            # or answer via zcode_decide (user input) — mirrors how the desktop
            # host parks these until the user clicks.
            params = m.get("params") or {}
            rid = str(params.get("requestId") or m["id"])
            kind = "permission" if m["method"].endswith("Permission") else "user_input"
            entry = {
                "kind": kind,
                "session_id": params.get("sessionId"),
                "params": params,
                "protocol_request_id": m["id"],
                "method": m["method"],
            }
            with self._interactions_lock:
                self.pending_interactions[rid] = entry
            log(f"parked {kind} request {rid} (session {entry['session_id']})")
            return  # no answer yet — the orchestrator decides
        elif m["method"] == "interaction/requestOfficialMcpAuthHeaders":
            # Preset plugin MCPs (e.g. image-search) ask the host for
            # zcode.z.ai identity headers on every session. We have no OAuth
            # credential chain; the desktop's decline shape makes the whole
            # turn abort in 0.16.9, so let the plugin start with an empty
            # identity instead.
            result = {"ok": True, "headers": {}}
        else:
            log(f"auto-answering server request {m['method']} with {{}}")
        try:
            self._send_line({"id": m["id"], "result": result})
        except Exception as e:  # never let the reader thread die
            log(f"failed answering {m['method']}: {e}")

    # -- pending interactions ----------------------------------------------

    def pending_for(self, sid: str) -> list[dict]:
        with self._interactions_lock:
            return [
                {"request_id": rid, **entry}
                for rid, entry in self.pending_interactions.items()
                if entry.get("session_id") == sid
            ]

    def respond_interaction(self, request_id: str, result: dict) -> None:
        with self._interactions_lock:
            entry = self.pending_interactions.pop(request_id, None)
        if entry is None:
            raise KeyError(f"no pending interaction {request_id}")
        self._send_line({"id": entry["protocol_request_id"], "result": result})

    # -- public -------------------------------------------------------------

    def request(self, method: str, params: dict, timeout: float = 30) -> Any:
        self.ensure()
        with self._pending_lock:
            rid = next(self._ids)
            q: queue.Queue = queue.Queue(maxsize=1)
            self._pending[rid] = q
        log(f"req #{rid} {method} (timeout={timeout}s)")
        t0 = time.time()
        self._send_line({"id": rid, "method": method, "params": params})
        try:
            resp = q.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(rid, None)
            log(f"req #{rid} {method} TIMEOUT after {time.time() - t0:.1f}s")
            raise TimeoutError(f"app-server {method} timed out after {timeout}s")
        log(
            f"req #{rid} {method} done in {time.time() - t0:.2f}s"
            + (" ERROR" if "error" in resp else "")
        )
        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(
                f"app-server {method} error {err.get('code')}: {err.get('message')}"
            )
        return resp.get("result")

    def event_waiter(self, sid: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._waiters_lock:
            self._event_waiters[sid] = q
        return q

    def drop_event_waiter(self, sid: str) -> None:
        with self._waiters_lock:
            self._event_waiters.pop(sid, None)


SERVER = AppServer()
