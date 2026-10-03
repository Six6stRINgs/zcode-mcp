"""Unit tests for pure logic in zcode_mcp.server (no app-server needed)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zcode_mcp.monitor import SessionMonitor  # noqa: E402
from zcode_mcp.protocol import (  # noqa: E402
    _message_texts,
    _norm_ws,
    attachment_kind,
    build_attachments,
    snapshot_last_reply,
)


def event(etype: str, **payload) -> dict:
    return {"type": etype, "payload": payload, "sessionId": "s1", "seq": 0}


class AttachmentKindTest(unittest.TestCase):
    def test_image(self):
        self.assertEqual(attachment_kind("a/b.png"), "image")
        self.assertEqual(attachment_kind("a/b.JPG"), "image")

    def test_pdf(self):
        self.assertEqual(attachment_kind("x.pdf"), "pdf")

    def test_audio_video(self):
        self.assertEqual(attachment_kind("x.mp3"), "audio")
        self.assertEqual(attachment_kind("x.MOV"), "video")

    def test_default_file(self):
        self.assertEqual(attachment_kind("x.txt"), "file")
        self.assertEqual(attachment_kind("x.py"), "file")


class BuildAttachmentsTest(unittest.TestCase):
    def test_build(self):
        f = Path(__file__)  # definitely exists
        atts = build_attachments([str(f)])
        self.assertEqual(len(atts), 1)
        a = atts[0]
        self.assertEqual(a["kind"], "file")
        self.assertEqual(a["filename"], f.name)
        self.assertEqual(a["localPath"], str(f))
        self.assertEqual(a["sizeBytes"], f.stat().st_size)
        self.assertTrue(a["mimeType"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            build_attachments(["Z:/definitely/not/there.txt"])


class NormWsTest(unittest.TestCase):
    def test_absolutizes_and_pairs(self):
        ws = _norm_ws("some/relative/dir")
        self.assertTrue(os.path.isabs(ws["workspacePath"]))
        self.assertEqual(ws["workspacePath"], ws["workspaceKey"])

    def test_none_uses_default(self):
        ws = _norm_ws(None)
        self.assertTrue(os.path.isabs(ws["workspacePath"]))


class SnapshotReplyTest(unittest.TestCase):
    def test_prefers_last_assistant(self):
        snap = {
            "messages": [
                {"info": {"role": "user"}, "parts": [{"type": "text", "text": "hi"}]},
                {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "first"}]},
                {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "second"}]},
            ]
        }
        self.assertEqual(snapshot_last_reply(snap), "second")

    def test_empty(self):
        self.assertEqual(snapshot_last_reply({"messages": []}), "")
        self.assertEqual(snapshot_last_reply({}), "")

    def test_ignored_parts_skipped(self):
        snap = {
            "messages": [
                {
                    "info": {"role": "assistant"},
                    "parts": [
                        {"type": "text", "text": "hidden", "ignored": True},
                        {"type": "text", "text": "visible"},
                    ],
                }
            ]
        }
        self.assertEqual(snapshot_last_reply(snap), "visible")


class MessageTextsTest(unittest.TestCase):
    def test_role_and_text(self):
        role, text = _message_texts(
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "a"}, {"type": "tool"}]}
        )
        self.assertEqual((role, text), ("user", "a"))


class RegistryConsistencyTest(unittest.TestCase):
    def test_every_declared_tool_is_implemented(self):
        from zcode_mcp.tools import TOOL_IMPL, TOOLS

        declared = {t["name"] for t in TOOLS}
        self.assertEqual(declared, set(TOOL_IMPL),
                         f"schema/impl mismatch: {declared ^ set(TOOL_IMPL)}")

    def test_session_tools_carry_session_in_name(self):
        from zcode_mcp.tools import TOOL_IMPL

        for name in TOOL_IMPL:
            if name in ("zcode_models", "zcode_quota", "zcode_health"):
                self.assertNotIn("session", name)
            else:
                self.assertIn("session", name)


class SessionMonitorTest(unittest.TestCase):
    def test_streaming_accumulation_and_reset(self):
        mon = SessionMonitor()
        mon.feed(event("turn.started", turnId="t1"))
        mon.feed(event("model.streaming", assistantMessageId="m1", delta="Hel", kind="text_delta"))
        mon.feed(event("model.streaming", assistantMessageId="m1", delta="lo", kind="text_delta"))
        self.assertEqual(mon.current_output(), "Hello")
        self.assertEqual(mon.turn_state, "running")
        # new assistant message resets the buffer
        mon.feed(event("model.streaming", assistantMessageId="m2", delta="bye", kind="text_delta"))
        self.assertEqual(mon.current_output(), "bye")

    def test_reasoning_not_counted_as_text(self):
        mon = SessionMonitor()
        mon.feed(event("model.streaming", assistantMessageId="m1", delta="thinking", kind="reasoning_delta"))
        self.assertEqual(mon.current_output(), "")

    def test_completed_lands_response(self):
        mon = SessionMonitor()
        mon.feed(event("turn.started"))
        mon.feed(event("model.streaming", assistantMessageId="m1", delta="OK", kind="text_delta"))
        mon.feed(event("turn.completed", response="OK", resultType="success"))
        self.assertEqual(mon.turn_state, "idle")
        self.assertEqual(mon.last_response, "OK")
        self.assertEqual(mon.last_result_type, "success")
        self.assertEqual(mon.turns_completed, 1)

    def test_failed_lands_error(self):
        mon = SessionMonitor()
        mon.feed(event("turn.failed", error={"message": "boom"}))
        self.assertEqual(mon.turn_state, "failed")
        self.assertEqual(mon.last_error, "boom")

    def test_state_updated_tracks_status(self):
        mon = SessionMonitor()
        mon.feed(event("state.updated", patch={"status": "running"}))
        self.assertEqual(mon.last_status, "running")

    def test_activity_phases(self):
        mon = SessionMonitor()
        mon.feed(event("turn.started", turnId="t1"))
        # producing: turn started, no deltas yet
        self.assertEqual(mon.activity()["phase"], "producing")
        # streaming: a recent text delta
        mon.feed(event("model.streaming", assistantMessageId="m1", delta="hi", kind="text_delta"))
        act = mon.activity()
        self.assertEqual(act["phase"], "streaming")
        self.assertEqual(act["stream_chars"], 2)
        # stalled: quiet for long (rewind both the event and stream clocks)
        ts, t, pl = mon.events[-1]
        mon.events[-1] = (ts - 60, t, pl)
        mon.last_stream_at = mon.last_stream_at - 60
        self.assertEqual(mon.activity()["phase"], "stalled")

    def test_events_without_payload_are_tolerated(self):
        mon = SessionMonitor()
        mon.feed({"type": "session.updated", "payload": None})
        self.assertEqual(len(mon.events), 1)
        self.assertEqual(mon.events[-1][1], "session.updated")


def _write_json(path, data):
    import json

    path.write_text(json.dumps(data), encoding="utf-8")


class ProviderRegistryTest(unittest.TestCase):
    """provider_registry(): merge of provider_config.json + config.json."""

    def setUp(self):
        import tempfile

        import zcode_mcp.models as models

        self.tmp = Path(tempfile.mkdtemp())
        self.pc = self.tmp / "provider_config.json"
        self.v2 = self.tmp / "config.json"
        self.models = models
        self._orig = (models.PROVIDER_CONFIG_PATH, models.ZCODE_V2_CONFIG)
        models.PROVIDER_CONFIG_PATH = str(self.pc)
        models.ZCODE_V2_CONFIG = str(self.v2)

    def tearDown(self):
        self.models.PROVIDER_CONFIG_PATH, self.models.ZCODE_V2_CONFIG = self._orig

    def test_merges_both_layers(self):
        _write_json(self.pc, {"config": {"providerConfigRules": {"providerRules": [
            {"providerId": "uuid-1", "providerName": "CPA",
             "config": {"personalModelIds": ["gpt-x"]}},
            {"providerId": "bigmodel-api", "providerName": "BigModel Coding Plan",
             "config": {"personalModelIds": []}},
        ]}}})
        _write_json(self.v2, {"provider": {
            "builtin:bigmodel-start-plan": {"name": "Start Plan", "enabled": False,
                                            "models": {"GLM-5.3-Flash": {}}},
            "uuid-1": {"name": "CPA"},
        }})
        reg = self.models.provider_registry()
        self.assertEqual(reg["uuid-1"]["name"], "CPA")
        self.assertEqual(reg["uuid-1"]["origin"], "provider_config")
        self.assertEqual(reg["bigmodel-api"]["name"], "BigModel Coding Plan")
        sp = reg["builtin:bigmodel-start-plan"]
        self.assertEqual(sp["origin"], "config")
        self.assertFalse(sp["enabled"])
        self.assertEqual(sp["models"], ["GLM-5.3-Flash"])

    def test_missing_files_give_empty_registry(self):
        self.models.PROVIDER_CONFIG_PATH = str(self.tmp / "nope.json")
        self.models.ZCODE_V2_CONFIG = str(self.tmp / "nope2.json")
        self.assertEqual(self.models.provider_registry(), {})


class ProviderAliasTest(unittest.TestCase):
    """Name-based selector resolution."""

    AVAILABLE = [
        {"provider_id": "uuid-1", "model_id": "gpt-x", "provider_label": "CPA"},
        {"provider_id": "bigmodel-api", "model_id": "GLM-5.3",
         "provider_label": "BigModel Coding Plan"},
    ]
    REGISTRY = {
        "uuid-1": {"name": "CPA"},
        "bigmodel-api": {"name": "BigModel Coding Plan"},
        "builtin:bigmodel-start-plan": {"name": "BigModel- Coding Plan"},
    }

    def _sel(self, selector):
        from zcode_mcp.models import build_provider_aliases, parse_model_selector

        aliases = build_provider_aliases(self.AVAILABLE, self.REGISTRY)
        return parse_model_selector(selector, self.AVAILABLE, aliases)

    def test_name_and_punctuation_insensitive(self):
        self.assertEqual(self._sel("CPA/gpt-x")["providerId"], "uuid-1")
        self.assertEqual(self._sel("cpa/gpt-x$low")["providerId"], "uuid-1")
        self.assertEqual(
            self._sel("bigmodel coding plan/GLM-5.3")["providerId"], "bigmodel-api"
        )
        self.assertEqual(
            self._sel("BigModel-Coding-Plan/GLM-5.3")["providerId"], "bigmodel-api"
        )

    def test_builtin_suffix_alias(self):
        with self.assertRaises(ValueError) as ctx:
            self._sel("start-plan/GLM-5.3-Flash")
        self.assertIn("not addressable", str(ctx.exception))
        self.assertIn("builtin:bigmodel-start-plan", str(ctx.exception))

    def test_ambiguous_desktop_only_name_carries_guidance(self):
        from zcode_mcp.models import build_provider_aliases, parse_model_selector

        reg = dict(self.REGISTRY)
        reg["builtin:zai-start-plan"] = {"name": "Z.ai - Coding Plan"}
        aliases = build_provider_aliases(self.AVAILABLE, reg)
        with self.assertRaises(ValueError) as ctx:
            parse_model_selector("start-plan/GLM-5.3-Flash", self.AVAILABLE, aliases)
        msg = str(ctx.exception)
        self.assertIn("ambiguous", msg)
        self.assertIn("desktop-managed account sources", msg)

    def test_raw_ids_still_work(self):
        self.assertEqual(self._sel("uuid-1/gpt-x")["providerId"], "uuid-1")
        self.assertEqual(self._sel("bigmodel-api/GLM-5.3")["providerId"], "bigmodel-api")

    def test_unknown_provider_lists_known(self):
        with self.assertRaises(ValueError) as ctx:
            self._sel("Nope/model-x")
        self.assertIn("uuid-1", str(ctx.exception))

    def test_name_collision_prefers_addressable(self):
        # real-world case: a typo'd config.json name collides with the
        # addressable provider's label; the addressable one must win
        self.assertEqual(
            self._sel("bigmodel coding plan/GLM-5.3")["providerId"], "bigmodel-api"
        )

    def test_ambiguous_addressable_name(self):
        from zcode_mcp.models import build_provider_aliases, parse_model_selector

        available = self.AVAILABLE + [
            {"provider_id": "uuid-2", "model_id": "gpt-y", "provider_label": "CPA"},
        ]
        aliases = build_provider_aliases(available, self.REGISTRY)
        with self.assertRaises(ValueError) as ctx:
            parse_model_selector("CPA/gpt-x", available, aliases)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_no_aliases_keeps_passthrough(self):
        from zcode_mcp.models import parse_model_selector

        sel = parse_model_selector("some-unknown/x", self.AVAILABLE)
        self.assertEqual(sel["providerId"], "some-unknown")

    def test_empty_catalogue_passthrough(self):
        # catalogue probe failed: ids must pass through so the app-server
        # validates (the default-model path depends on this)
        from zcode_mcp.models import build_provider_aliases, parse_model_selector

        aliases = build_provider_aliases([], self.REGISTRY)
        sel = parse_model_selector("bigmodel-api/GLM-5.3-Flash", [], aliases)
        self.assertEqual(sel["providerId"], "bigmodel-api")


class EphemeralTest(unittest.TestCase):
    """Temporary-conversation registry and reaper decisions."""

    def setUp(self):
        import importlib

        self.eph = importlib.import_module("zcode_mcp.ephemeral")
        with self.eph._lock:
            self.eph._sessions.clear()
            self.eph._inflight.clear()

    def tearDown(self):
        with self.eph._lock:
            self.eph._sessions.clear()
            self.eph._inflight.clear()

    def test_register_touch_note(self):
        self.eph.register("sess_t1")
        self.assertTrue(self.eph.is_temporary("sess_t1"))
        self.assertIn("temporary conversation", self.eph.note("sess_t1"))
        self.eph.touch("sess_t1")
        self.assertTrue(self.eph.is_temporary("sess_t1"))

    def test_forget_drops_session(self):
        self.eph.register("sess_t1")
        self.eph.forget("sess_t1")
        self.assertFalse(self.eph.is_temporary("sess_t1"))
        self.assertEqual(self.eph.note("sess_t1"), "")

    def test_reap_one_guards_running_turn_then_discards(self):
        import zcode_mcp.store as store

        calls = []
        orig_discard = store.discard_session
        orig_running = self.eph._turn_running
        store.discard_session = lambda sid: calls.append(sid) or {"session": 1}
        try:
            self.eph.register("sess_t1")
            with self.eph._lock:
                self.eph._sessions["sess_t1"] -= 10**6  # well past TTL
            self.eph._turn_running = lambda sid: True
            self.assertFalse(self.eph._reap_one("sess_t1"))  # turn moving: keep
            self.assertTrue(self.eph.is_temporary("sess_t1"))
            self.eph._turn_running = lambda sid: False
            self.assertTrue(self.eph._reap_one("sess_t1"))  # idle: discard
            self.assertEqual(calls, ["sess_t1"])
            self.assertFalse(self.eph.is_temporary("sess_t1"))
        finally:
            store.discard_session = orig_discard
            self.eph._turn_running = orig_running

    def test_inflight_call_blocks_reaping(self):
        import zcode_mcp.store as store

        calls = []
        orig_discard = store.discard_session
        orig_running = self.eph._turn_running
        store.discard_session = lambda sid: calls.append(sid) or {"session": 1}
        self.eph._turn_running = lambda sid: False
        try:
            self.eph.register("sess_busy")
            with self.eph._lock:
                self.eph._sessions["sess_busy"] -= 10**6
            self.eph.begin("sess_busy")
            self.assertFalse(self.eph._reap_one("sess_busy"))  # call executing
            self.eph.end("sess_busy")
            self.assertTrue(self.eph._reap_one("sess_busy"))
            self.assertEqual(calls, ["sess_busy"])
        finally:
            store.discard_session = orig_discard
            self.eph._turn_running = orig_running

    def test_reap_one_skips_fresh_sessions(self):
        # TOCTOU guard: a touch after the cycle snapshot resets the clock
        orig_running = self.eph._turn_running
        self.eph._turn_running = lambda sid: False
        try:
            self.eph.register("sess_fresh")
            with self.eph._lock:
                self.eph._sessions["sess_fresh"] -= 10**6
            self.eph.touch("sess_fresh")  # lands after the snapshot
            self.assertFalse(self.eph._reap_one("sess_fresh"))
            self.assertTrue(self.eph.is_temporary("sess_fresh"))
        finally:
            self.eph._turn_running = orig_running

    def test_turn_running_fail_closed(self):
        # live monitor semantics: no events -> assume live; running turn
        # (even stalled) -> live; completed turn -> not live
        from zcode_mcp.appserver import SERVER

        sid = "sess_eph_turn"
        mon = SERVER._monitor(sid)
        self.assertTrue(self.eph._turn_running(sid))  # never observed
        mon.feed({"type": "turn.started", "payload": {}, "sessionId": sid, "seq": 0})
        self.assertTrue(self.eph._turn_running(sid))  # running (stalled counts)
        mon.feed({"type": "turn.completed", "payload": {}, "sessionId": sid, "seq": 1})
        self.assertFalse(self.eph._turn_running(sid))  # saw it end
        SERVER.monitors.pop(sid, None)

    def test_exit_discard_forces_and_forgets(self):
        reaped = []

        def fake_reap(sid, force=False, ttl=None):
            reaped.append((sid, force))
            with self.eph._lock:
                self.eph._sessions.pop(sid, None)
            return True

        self.eph.register("sess_t3")
        orig = self.eph._reap_one
        self.eph._reap_one = fake_reap
        try:
            self.eph.discard_all_on_exit()
        finally:
            self.eph._reap_one = orig
        self.assertEqual(reaped, [("sess_t3", True)])
        self.assertFalse(self.eph.is_temporary("sess_t3"))

    def test_reap_cycle_only_takes_due_sessions(self):
        import time

        from zcode_mcp import config

        self.eph.register("sess_old")
        self.eph.register("sess_new")
        # defuse the background reaper: it must never touch the real store
        orig = self.eph._reap_one
        self.eph._reap_one = lambda sid, force=False, ttl=None: False
        try:
            with self.eph._lock:
                self.eph._sessions["sess_old"] -= config.TEMP_TTL + 60
            due = self.eph._due_sids(time.monotonic(), config.TEMP_TTL)
            self.assertEqual(sorted(due), ["sess_old"])
        finally:
            self.eph._reap_one = orig

    def test_reap_cycle_end_to_end(self):
        import zcode_mcp.store as store

        calls = []
        orig_discard = store.discard_session
        orig_running = self.eph._turn_running
        store.discard_session = lambda sid: calls.append(sid) or {"session": 1}
        self.eph._turn_running = lambda sid: False
        try:
            self.eph.register("sess_due")
            with self.eph._lock:
                self.eph._sessions["sess_due"] -= 10**6
            self.assertEqual(self.eph._reap_cycle(ttl=600), 1)
            self.assertEqual(calls, ["sess_due"])
            self.assertFalse(self.eph.is_temporary("sess_due"))
        finally:
            store.discard_session = orig_discard
            self.eph._turn_running = orig_running

    def test_discard_failure_keeps_session_for_retry(self):
        import zcode_mcp.store as store

        orig_discard = store.discard_session
        orig_running = self.eph._turn_running

        def boom(sid):
            raise RuntimeError("database is locked")

        store.discard_session = boom
        self.eph._turn_running = lambda sid: False
        try:
            self.eph.register("sess_locked")
            with self.eph._lock:
                self.eph._sessions["sess_locked"] -= 10**6
            self.assertFalse(self.eph._reap_one("sess_locked"))
            self.assertTrue(self.eph.is_temporary("sess_locked"))  # retried later
        finally:
            store.discard_session = orig_discard
            self.eph._turn_running = orig_running

    def test_reap_cycle_disabled_when_ttl_zero(self):
        self.eph.register("sess_t2")
        self.assertEqual(self.eph._reap_cycle(ttl=0), 0)
        self.assertTrue(self.eph.is_temporary("sess_t2"))

    def test_note_absent_for_regular_sessions(self):
        self.assertEqual(self.eph.note("sess_never"), "")


if __name__ == "__main__":
    unittest.main()
