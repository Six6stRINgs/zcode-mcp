"""Tests for the shared-store helpers (archive / discard) using temp DBs."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import zcode_mcp.store as store  # noqa: E402


def make_session_db(path: Path, sessions: list[tuple[str, int | None]]):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, time_archived INTEGER)"
    )
    con.executemany("INSERT INTO session VALUES (?, ?)", sessions)
    con.commit()
    con.close()


def make_tasks_db(path: Path, tasks: list[tuple[str, int, int]]):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, archived INTEGER, deleted INTEGER)"
    )
    con.executemany("INSERT INTO tasks VALUES (?, ?, ?)", tasks)
    con.commit()
    con.close()


class StoreHelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_db = Path(self.tmp.name) / "db.sqlite"
        self.tasks_db = Path(self.tmp.name) / "tasks-index.sqlite"
        make_session_db(self.session_db, [("s_keep", None), ("s_old", 111)])
        make_tasks_db(self.tasks_db, [("s_keep", 0, 0), ("s_old", 0, 0)])
        self._orig = (store.SESSION_DB_PATH, store.TASKS_INDEX_PATH)
        store.SESSION_DB_PATH = str(self.session_db)
        store.TASKS_INDEX_PATH = str(self.tasks_db)

    def tearDown(self):
        store.SESSION_DB_PATH, store.TASKS_INDEX_PATH = self._orig
        self.tmp.cleanup()

    def test_archived_session_ids(self):
        self.assertEqual(store.archived_session_ids(), {"s_old"})

    def test_archived_ids_tolerates_missing_db(self):
        store.SESSION_DB_PATH = str(Path(self.tmp.name) / "nope.sqlite")
        self.assertEqual(store.archived_session_ids(), set())

    def test_archive_and_unarchive(self):
        res = store.set_session_archived("s_keep", True)
        self.assertEqual(res["session_store_rows"], 1)
        self.assertEqual(res["task_index_rows"], 1)
        con = sqlite3.connect(self.session_db)
        ts = con.execute("SELECT time_archived FROM session WHERE id='s_keep'").fetchone()[0]
        con.close()
        self.assertIsNotNone(ts)
        self.assertEqual(store.archived_session_ids(), {"s_old", "s_keep"})

        res = store.set_session_archived("s_keep", False)
        con = sqlite3.connect(self.session_db)
        ts = con.execute("SELECT time_archived FROM session WHERE id='s_keep'").fetchone()[0]
        con.close()
        self.assertIsNone(ts)
        self.assertEqual(store.archived_session_ids(), {"s_old"})

    def test_archive_unknown_session_reports_zero_rows(self):
        res = store.set_session_archived("s_ghost", True)
        self.assertEqual(res["session_store_rows"], 0)

    def test_discard_scope_counts(self):
        con = sqlite3.connect(self.session_db)
        con.execute("CREATE TABLE message (session_id TEXT, body TEXT)")
        con.execute("CREATE TABLE part (session_id TEXT, body TEXT)")
        con.execute("INSERT INTO message VALUES ('s_keep', 'hi')")
        con.execute("INSERT INTO message VALUES ('s_other', 'hi')")
        con.execute("INSERT INTO part VALUES ('s_keep', 'p')")
        con.commit()
        con.close()
        scope = store.discard_scope("s_keep")
        self.assertEqual(scope["message"], 1)
        self.assertEqual(scope["part"], 1)
        self.assertEqual(scope["session"], 1)

    def test_discard_removes_exactly_the_target(self):
        con = sqlite3.connect(self.session_db)
        con.execute("CREATE TABLE message (session_id TEXT, body TEXT)")
        con.execute("INSERT INTO message VALUES ('s_keep', 'a')")
        con.execute("INSERT INTO message VALUES ('s_other', 'b')")
        con.commit()
        con.close()

        deleted = store.discard_session("s_keep")
        self.assertEqual(deleted["message"], 1)
        self.assertEqual(deleted["session"], 1)

        con = sqlite3.connect(self.session_db)
        left = [r[0] for r in con.execute("SELECT id FROM session").fetchall()]
        msgs = con.execute("SELECT session_id FROM message").fetchall()
        con.close()
        self.assertEqual(left, ["s_old"])
        self.assertEqual(msgs, [("s_other",)])

        con = sqlite3.connect(self.tasks_db)
        flag = con.execute("SELECT deleted FROM tasks WHERE task_id='s_keep'").fetchone()[0]
        con.close()
        self.assertEqual(flag, 1)

    def test_discard_unknown_session_deletes_nothing(self):
        deleted = store.discard_session("s_ghost")
        self.assertEqual(deleted["session"], 0)
        con = sqlite3.connect(self.session_db)
        n = con.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        con.close()
        self.assertEqual(n, 2)


class CreateParamsTest(unittest.TestCase):
    def test_schema_has_no_unexpected_keys(self):
        # guard against protocol drift: create params we send must stay minimal
        import inspect

        from zcode_mcp import protocol

        src = inspect.getsource(protocol.create_session)
        for key in ("workspace", "mode", "titleGenerationEnabled", "persistence"):
            self.assertIn(key, src)


class EffectiveTimeoutTest(unittest.TestCase):
    def test_caps_at_budget(self):
        import zcode_mcp.config as cfg
        from zcode_mcp import tools

        self.assertEqual(tools._effective_timeout({"timeout_sec": 9999}), cfg.TOOL_BUDGET)
        self.assertEqual(tools._effective_timeout({}), min(cfg.DEFAULT_TIMEOUT, cfg.TOOL_BUDGET))
        self.assertEqual(tools._effective_timeout({"timeout_sec": 30}), 30)

    def test_budget_floor(self):
        import zcode_mcp.config as cfg
        from zcode_mcp import tools

        old = cfg.TOOL_BUDGET
        cfg.TOOL_BUDGET = 0
        try:
            self.assertEqual(tools._effective_timeout({}), 1)
        finally:
            cfg.TOOL_BUDGET = old


class ResolveZcodeCjsTest(unittest.TestCase):
    def test_env_var_wins(self):
        import zcode_mcp.config as cfg

        existing = __file__  # a path that definitely exists
        old = os.environ.get("ZCODE_CJS")
        os.environ["ZCODE_CJS"] = existing
        try:
            self.assertEqual(cfg.resolve_zcode_cjs(), existing)
        finally:
            if old is None:
                del os.environ["ZCODE_CJS"]
            else:
                os.environ["ZCODE_CJS"] = old

    def test_env_var_pointing_nowhere_raises(self):
        import zcode_mcp.config as cfg

        old = os.environ.get("ZCODE_CJS")
        os.environ["ZCODE_CJS"] = "Z:/no/such/zcode.cjs"
        try:
            with self.assertRaises(RuntimeError):
                cfg.resolve_zcode_cjs()
        finally:
            if old is None:
                del os.environ["ZCODE_CJS"]
            else:
                os.environ["ZCODE_CJS"] = old

    def test_unresolved_error_is_actionable(self):
        import zcode_mcp.config as cfg

        old = os.environ.get("ZCODE_CJS")
        os.environ.pop("ZCODE_CJS", None)
        orig_isfile = os.path.isfile

        def fake_isfile(p):
            if "zcode.cjs" in str(p).lower():
                return False
            return orig_isfile(p)

        os.path.isfile = fake_isfile
        try:
            with self.assertRaises(RuntimeError) as ctx:
                cfg.resolve_zcode_cjs()
            self.assertIn("ZCODE_CJS", str(ctx.exception))
        finally:
            os.path.isfile = orig_isfile
            if old is not None:
                os.environ["ZCODE_CJS"] = old


if __name__ == "__main__":
    unittest.main()
