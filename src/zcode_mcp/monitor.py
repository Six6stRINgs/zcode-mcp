"""Per-session observability state.

`SessionMonitor` accumulates the event stream of one ZCode conversation so
other tools can answer "what is the model doing right now" at any time.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any


class SessionMonitor:
    """Ring buffer of session events plus derived streaming state.

    Fed from live ``session/event`` notifications and from ``session/subscribe``
    replay, so mid-turn state survives across MCP tool calls.
    """

    def __init__(self) -> None:
        self.events: deque[tuple[float, str, dict]] = deque(maxlen=600)
        self.stream_mid: str | None = None
        self.stream_text: list[str] = []
        self.turn_id: str | None = None
        self.turn_state: str = "idle"  # idle | running | failed
        self.last_response: str = ""
        self.last_result_type: str = ""
        self.last_error: str = ""
        self.last_status: str = ""
        self.turns_completed: int = 0

    def feed(self, env: dict) -> None:
        etype = env.get("type", "")
        payload = env.get("payload") or {}
        self.events.append((time.time(), etype, payload))
        if etype == "turn.started":
            self.turn_id = env.get("turnId") or payload.get("turnId")
            self.turn_state = "running"
            self.stream_mid = None
            self.stream_text = []
        elif etype == "model.streaming":
            kind = payload.get("kind", "text_delta")
            if kind == "text_delta":
                mid = payload.get("assistantMessageId")
                if mid != self.stream_mid:
                    self.stream_mid = mid
                    self.stream_text = []
                delta = payload.get("delta")
                if isinstance(delta, str):
                    self.stream_text.append(delta)
        elif etype == "turn.completed":
            self.turn_state = "idle"
            self.turns_completed += 1
            self.last_response = str(payload.get("response") or "")
            self.last_result_type = str(payload.get("resultType") or "success")
        elif etype == "turn.failed":
            self.turn_state = "failed"
            err = payload.get("error")
            self.last_error = (
                err.get("message", "unknown") if isinstance(err, dict) else str(err)
            )
        elif etype == "state.updated":
            status = (payload.get("patch") or {}).get("status")
            if isinstance(status, str):
                self.last_status = status

    def current_output(self, max_chars: int = 4000) -> str:
        text = "".join(self.stream_text)
        return text[-max_chars:] if len(text) > max_chars else text

    def summary(self) -> dict[str, Any]:
        last = self.events[-1] if self.events else None
        return {
            "turn_state": self.turn_state,
            "turn_id": self.turn_id,
            "status": self.last_status,
            "events_buffered": len(self.events),
            "last_event": last[1] if last else None,
            "last_event_age_s": round(time.time() - last[0], 1) if last else None,
            "stream_chars": len("".join(self.stream_text)),
            "turns_completed": self.turns_completed,
            "last_result_type": self.last_result_type,
        }
