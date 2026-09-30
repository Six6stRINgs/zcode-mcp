"""Shared-store operations: archive / discard.

Verified on 0.16.9 against the open-source tree and live databases:

- `~/.zcode/cli/db/db.sqlite` (session store): `session.time_archived` is the
  runtime-level archive flag; archived sessions drop out of `session/list`
  on the next app-server start.
- `~/.zcode/v2/tasks-index.sqlite` (desktop task index): `tasks.archived`
  hides a conversation from the desktop sidebar; `tasks.deleted` is the
  desktop's delete marker. Rows only exist there once the desktop app has
  synced the session, so updates may match 0 rows for sandbox-only sessions.

The protocol itself has NO archive/delete method (verified against the
0.16.9 binary), so these flags are maintained directly. All writes use
short transactions with busy_timeout; every statement is scoped by exact
session id.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from .config import SESSION_DB_PATH, TASKS_INDEX_PATH, log

_SESSION_CHILD_TABLES = (
    "part", "message", "todo", "session_entry", "input_history",
    "session_target", "model_usage", "turn_usage", "tool_usage",
    "session_input", "dwf_actor",
)


def _connect(path: str) -> sqlite3.Connection:
    """Open a short-lived connection; callers MUST close() it (use closing())."""
    con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def session_exists(sid: str) -> bool:
    with closing(_connect(SESSION_DB_PATH)) as con:
        return con.execute(
            "SELECT 1 FROM session WHERE id=?", (sid,)
        ).fetchone() is not None


def archived_session_ids() -> set[str]:
    """Session ids flagged archived in the shared session store."""
    try:
        with closing(_connect(SESSION_DB_PATH)) as con:
            rows = con.execute(
                "SELECT id FROM session WHERE time_archived IS NOT NULL"
            ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.Error as e:
        log(f"archived_session_ids read failed: {e}")
        return set()


def set_session_archived(sid: str, archived: bool) -> dict[str, int | bool]:
    """Archive (or unarchive) a conversation in both shared stores."""
    now_ms = int(time.time() * 1000)
    out: dict[str, int | bool] = {}
    try:
        with closing(_connect(SESSION_DB_PATH)) as con:
            cur = con.execute(
                "UPDATE session SET time_archived=? WHERE id=?",
                (now_ms if archived else None, sid),
            )
            con.commit()
            out["session_store_rows"] = cur.rowcount
    except sqlite3.Error as e:
        log(f"archive: session store update failed: {e}")
        out["session_store_rows"] = -1
    try:
        with closing(_connect(TASKS_INDEX_PATH)) as con:
            cur = con.execute(
                "UPDATE tasks SET archived=? WHERE task_id=?",
                (1 if archived else 0, sid),
            )
            con.commit()
            out["task_index_rows"] = cur.rowcount
    except sqlite3.Error as e:
        log(f"archive: task index update failed: {e}")
        out["task_index_rows"] = -1
    return out


def discard_scope(sid: str) -> dict[str, int]:
    """Row counts a discard would remove (dry run; read-only)."""
    scope: dict[str, int] = {}
    with closing(_connect(SESSION_DB_PATH)) as con:
        for t in _SESSION_CHILD_TABLES:
            if _table_exists(con, t):
                scope[t] = con.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE session_id=?", (sid,)
                ).fetchone()[0]
        scope["session"] = con.execute(
            "SELECT COUNT(*) FROM session WHERE id=?", (sid,)
        ).fetchone()[0]
    return scope


def discard_session(sid: str) -> dict[str, int]:
    """Permanently delete a conversation from the shared session store.

    Child rows go first, then the session row, all inside one transaction
    and scoped by the exact id. The desktop task-index row (if synced) is
    flagged deleted, matching desktop delete semantics.
    """
    with closing(_connect(SESSION_DB_PATH)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            deleted: dict[str, int] = {}
            for t in _SESSION_CHILD_TABLES:
                if _table_exists(con, t):
                    cur = con.execute(f"DELETE FROM {t} WHERE session_id=?", (sid,))
                    deleted[t] = cur.rowcount
            cur = con.execute("DELETE FROM session WHERE id=?", (sid,))
            deleted["session"] = cur.rowcount
            con.commit()
        except Exception:
            con.rollback()
            raise
    try:
        with closing(_connect(TASKS_INDEX_PATH)) as con:
            con.execute("UPDATE tasks SET deleted=1 WHERE task_id=?", (sid,))
            con.commit()
    except sqlite3.Error as e:
        log(f"discard: task index update failed: {e}")
    return deleted
