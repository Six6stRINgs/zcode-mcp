#!/usr/bin/env python3
"""zcode-mcp MCP entry point: JSON-RPC 2.0 stdio plumbing.

Can be run as a package module (``python -m zcode_mcp.server``) or directly
as a script (``python .../zcode_mcp/server.py``); both paths work.

Module layout:
    config.py     environment knobs, paths, logging
    monitor.py    per-session event buffers (observability state)
    appserver.py  zcode app-server child + ZCode Protocol wire handling
    protocol.py   session operations (create/send/subscribe/wait/attachments)
    store.py      shared-store operations (archive / discard)
    tools.py      MCP tool implementations + schemas
    server.py     this file: MCP framing
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any

try:
    from . import __version__
    from . import ephemeral
    from .appserver import SERVER
    from .config import DEFAULT_WS, NO_WARMUP, log, resolve_zcode_cjs
    from .tools import TOOL_IMPL, TOOLS
except ImportError:  # executed as a plain script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from zcode_mcp import __version__
    from zcode_mcp import ephemeral
    from zcode_mcp.appserver import SERVER
    from zcode_mcp.config import DEFAULT_WS, NO_WARMUP, log, resolve_zcode_cjs
    from zcode_mcp.tools import TOOL_IMPL, TOOLS

VERSION = __version__


def _dispatch_tool(req_id: Any, params: dict) -> None:
    """Run one tools/call in its own thread and emit the response."""
    name = params.get("name")
    targs = params.get("arguments") or {}
    impl = TOOL_IMPL.get(name)
    if impl is None:
        resp = mcp_result(
            req_id,
            {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True},
        )
    else:
        try:
            sid = targs.get("session_id")
            if sid:
                ephemeral.touch(sid)
            resp = mcp_result(req_id, {"content": [{"type": "text", "text": impl(targs)}]})
        except Exception as e:
            log(f"tool {name} failed: {e!r}")
            resp = mcp_result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"tool {name} failed: {e}"}],
                    "isError": True,
                },
            )
    out = json.dumps(resp, ensure_ascii=False)
    log(f"MCP -> {out[:200]}")
    with _stdout_lock:
        sys.stdout.write(out + "\n")
        sys.stdout.flush()


_stdout_lock = threading.Lock()


def mcp_result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def mcp_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}
    log(f"MCP <- {method}" + (f" {params.get('name')}" if method == "tools/call" else ""))
    if method == "initialize":
        if not NO_WARMUP:
            # reply immediately; warm up the app-server in the background so a
            # slow/contended child can never eat into the client's startup
            # timeout (desktop clients allow 30s for the whole handshake)
            def _warm():
                try:
                    SERVER.ensure()
                except Exception as e:
                    log(f"warm-up spawn failed: {e}")
            threading.Thread(target=_warm, daemon=True).start()
        return mcp_result(
            req_id,
            {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "serverInfo": {"name": "zcode-mcp", "version": VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return mcp_result(req_id, {})
    if method == "tools/list":
        return mcp_result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        # tools run concurrently: a blocking zcode_new/zcode_send must not
        # prevent the caller from issuing zcode_permissions / zcode_decide
        # while the turn is paused on a parked permission request
        threading.Thread(
            target=_dispatch_tool, args=(req_id, params), daemon=True
        ).start()
        return None
    if method == "resources/list":
        return mcp_result(req_id, {"resources": []})
    if method == "resources/templates/list":
        return mcp_result(req_id, {"resourceTemplates": []})
    if method == "prompts/list":
        return mcp_result(req_id, {"prompts": []})
    if req_id is not None:
        return mcp_error(req_id, -32601, f"Method not found: {method}")
    return None


def main() -> None:
    # Windows pipes translate "\n" to "\r\n" in text mode; some MCP clients
    # are strict about line framing. Force LF-only UTF-8 on both streams.
    try:
        sys.stdin.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, OSError):
            pass
    log(f"=== zcode-mcp v{VERSION} starting (default workspace={DEFAULT_WS})")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(req)
        except Exception as e:
            log(f"handle error: {e!r}")
            resp = mcp_error(req.get("id"), -32603, f"internal error: {e}")
        if resp is not None:
            out = json.dumps(resp, ensure_ascii=False)
            log(f"MCP -> {out[:200]}")
            with _stdout_lock:
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
