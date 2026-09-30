"""Configuration, paths and logging for zcode-mcp.

All environment-derived knobs live here so every other module (and tests)
has a single place to read or override them.
"""

from __future__ import annotations

import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_WS = os.environ.get(
    "ZCODE_MCP_WORKSPACE", os.path.join(_PROJECT_ROOT, "sandbox")
)
DEBUG = os.environ.get("ZCODE_MCP_DEBUG") == "1"
NO_WARMUP = os.environ.get("ZCODE_MCP_NO_WARMUP") == "1"
LOG_PATH = os.path.join(_PROJECT_ROOT, "bridge.log")
RAW_DUMP = os.path.join(_PROJECT_ROOT, "child_dump.log")

# Shared ZCode stores (read-modified carefully; see store.py for semantics)
ZCODE_HOME = os.environ.get("ZCODE_HOME", os.path.expanduser("~/.zcode"))
SESSION_DB_PATH = os.environ.get(
    "ZCODE_MCP_SESSION_DB", os.path.join(ZCODE_HOME, "cli", "db", "db.sqlite")
)
TASKS_INDEX_PATH = os.environ.get(
    "ZCODE_MCP_TASKS_INDEX", os.path.join(ZCODE_HOME, "v2", "tasks-index.sqlite")
)
CREDENTIALS_PATH = os.environ.get(
    "ZCODE_MCP_CREDENTIALS", os.path.join(ZCODE_HOME, "v2", "credentials.json")
)

DEFAULT_TIMEOUT = 600
# Codex-like MCP clients cap a single tools/call at ~300s; any blocking tool
# must return before that so the orchestrator gets a resumable status instead
# of a transport error.
TOOL_BUDGET = int(os.environ.get("ZCODE_MCP_TOOL_BUDGET", "240"))
DELIVERY_KIND = "desktop-continuous"
TERMINAL_STATUSES = {"idle", "completed", "error", "paused"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}

# Schema-required answer for the server's runtime-preferences reverse request
RUNTIME_PREFS_RESULT = {
    "nativeSearchEnhancementsEnabled": False,
    "memoryEnabled": False,
    "askUserQuestionAutoResolutionEnabled": True,
}


def resolve_zcode_cjs() -> str:
    """Locate the ZCode CLI entry (zcode.cjs), lazily and portably.

    Order: ZCODE_CJS env var → common per-user/system install locations.
    Raises RuntimeError with actionable guidance when nothing is found;
    callers decide whether that is fatal.
    """
    env = os.environ.get("ZCODE_CJS")
    if env:
        if os.path.isfile(env):
            return env
        raise RuntimeError(
            f"ZCODE_CJS is set but the file does not exist: {env}"
        )
    local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))
    roots = [
        os.path.join(local_app, "Programs", "ZCode"),
        os.path.join(local_app, "ZCode"),
        "C:/Program Files/ZCode",
        "C:/Program Files (x86)/ZCode",
    ]
    for root in roots:
        cjs = os.path.join(root, "resources", "glm", "zcode.cjs")
        if os.path.isfile(cjs):
            return cjs
    raise RuntimeError(
        "Cannot locate the ZCode CLI entry (zcode.cjs). "
        "Set the ZCODE_CJS environment variable to "
        "'<ZCode install dir>/resources/glm/zcode.cjs' "
        "(searched: " + "; ".join(roots) + ")"
    )


def log(msg: str) -> None:
    """Always append to bridge.log; stderr only under DEBUG.

    GUI hosts (Codex desktop) may never drain our stderr pipe — a full pipe
    buffer would block the whole server, so stderr stays silent by default.
    """
    line = f"[{time.strftime('%H:%M:%S')}] [zcode-mcp] {msg}"
    if DEBUG:
        print(line, file=sys.stderr, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
