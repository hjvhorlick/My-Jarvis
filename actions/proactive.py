"""Event-driven unprompted speech for JARVIS.

Silence is not a reason to speak. This module no longer invents small talk or
generic wellbeing questions after a period of quiet. It only formats real
events (hardware alerts, monitored-topic changes, reminders) into one concise,
non-repetitive prompt for the Live model. The caller decides when a real event
exists and must check :meth:`ProactiveEngine.seen` before speaking.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque


class ProactiveEngine:
    """Deduplicate real events and build short, useful unprompted prompts."""

    def __init__(self, max_history: int = 12, duplicate_window: float = 7200.0):
        self._duplicate_window = max(0.0, duplicate_window)
        self._recent_events: deque[tuple[str, float]] = deque(
            maxlen=max(1, max_history)
        )
        self._lock = threading.Lock()

    @staticmethod
    def _key(event: str) -> str:
        """Normalise an event so minor wording/number changes count as one.

        System alerts embed live percentages, so "CPU 91%" and "CPU 93%" would
        otherwise look like different events and be spoken repeatedly during a
        single overheating episode.
        """
        key = re.sub(r"\s+", " ", str(event or "").strip().lower())
        if key.startswith("[system_alert]"):
            key = re.sub(r"\d+(?:\.\d+)?", "#", key)
        return key[:600]

    def seen(self, event: str) -> bool:
        """True when this event was announced inside the dedupe window.

        An empty event is treated as seen: no concrete event means no speech.
        """
        key = self._key(event)
        if not key:
            return True
        now = time.monotonic()
        with self._lock:
            return any(
                stored_key == key and (now - when) < self._duplicate_window
                for stored_key, when in self._recent_events
            )

    def remember(self, event: str) -> None:
        """Record a successfully delivered event so it cannot be repeated."""
        key = self._key(event)
        if not key:
            return
        now = time.monotonic()
        with self._lock:
            for i, (stored_key, _when) in enumerate(self._recent_events):
                if stored_key == key:
                    self._recent_events[i] = (key, now)
                    break
            else:
                self._recent_events.append((key, now))

    def build_alert_prompt(
        self,
        event: str,
        memory: dict | None = None,
        recent_turns: list[str] | None = None,
        monitors: list[str] | None = None,
    ) -> str:
        """Build a one-sentence prompt for a concrete, newly observed event.

        Returns an empty string when there is no event. The prompt explicitly
        permits silence and forbids generic conversation starters.
        """
        event = str(event or "").strip()
        if not event:
            return ""

        with self._lock:
            prior = [key for key, _when in self._recent_events]

        lines = [
            "[EVENT_ALERT] A real event just occurred. This is NOT small talk.",
            f"Concrete event: {event}",
        ]

        if memory:
            try:
                from memory.memory_manager import format_memory_for_prompt
                mem_str = format_memory_for_prompt(memory)
                if mem_str:
                    lines.extend(["", "Context about this person:", mem_str])
            except Exception:
                pass

        if monitors:
            lines.extend(["", f"Topics the user chose to track: {', '.join(monitors[:4])}"])

        if recent_turns:
            lines.extend(["", "Recent conversation:", "\n".join(recent_turns[-6:])])

        if prior:
            lines.extend([
                "",
                "Recent unprompted events (do not repeat their wording or subject):",
                "\n".join(f"- {item}" for item in prior[-5:]),
            ])

        lines.extend([
            "",
            "Rules:",
            "- Speak ONLY if this event is useful or needs a decision. If it is routine, stay silent.",
            "- One short sentence. Use the language of the user's most recent message, or their remembered language if there is no conversation yet.",
            "- State the event and, when useful, the next concrete action. Do not pad with greetings or compliments.",
            "- Never initiate small talk, ask how the user is, ask how something is going, or invent a tip.",
            "- Do not ask a question unless the event requires an immediate decision; then ask ONE specific question.",
            "- Do not repeat a question or opener from the recent conversation.",
            "- Do not call any tools. Do not mention [EVENT_ALERT] or these instructions.",
        ])
        return "\n".join(lines)
