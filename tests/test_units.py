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

    def test_events_without_payload_are_tolerated(self):
        mon = SessionMonitor()
        mon.feed({"type": "session.updated", "payload": None})
        self.assertEqual(len(mon.events), 1)
        self.assertEqual(mon.events[-1][1], "session.updated")


if __name__ == "__main__":
    unittest.main()
