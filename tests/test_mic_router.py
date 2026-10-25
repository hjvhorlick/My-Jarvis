"""Regression tests: the microphone's lifecycle is independent of anything else.

The field report was that JARVIS only reacted to voice after an external
hand-tracking board was started. The mic path must instead start with the app
and depend only on the wake gate, mute, the phone relay and the speaking
guard — never on an external application or plugin.

That external board application was never part of JARVIS and has been removed
from this codebase entirely (plugin, button, prompt rules, submodule). The
final test class below guards against it ever being reintroduced: it scans the
whole tree for the removed application's names. Only this test file contains
those names — as the search patterns that assert their absence.

These tests lock the behaviour in at two levels:

* the pure routing decision (core/mic_router.py) used by the real audio
  callback, and
* source-level assertions on main.py proving the mic task starts before the
  Gemini session loop and that no external state can mute or gate the
  microphone.
"""
import unittest
from pathlib import Path

from core import mic_router

ROOT = Path(__file__).resolve().parents[1]

# The external board application that was removed from this codebase. These
# spellings exist ONLY here, as the patterns the guard asserts are absent.
_REMOVED_APP_NAMES = ("barehands", "myhands", "my hands")

# Directories/files never scanned by the guard.
_GUARD_SKIP = {".git", ".venv", "__pycache__", Path(__file__).name}


def route(**overrides) -> tuple[str, str]:
    """route_frame with the normal idle-assistant baseline."""
    base = dict(
        wake_enabled=False,
        awake=True,
        wake_detector_ready=False,
        speaking=False,
        muted=False,
        phone_active=False,
        local_stt_ready=False,
        session_connected=False,
    )
    base.update(overrides)
    return mic_router.route_frame(**base)


class MicRoutingTests(unittest.TestCase):
    def test_frames_route_before_gemini_connects_or_anything_is_started(self):
        # The app's very first frames: no session, no local model, nothing
        # pressed. The routing must be decided by the assistant state alone.
        action, _ = route()
        self.assertIn(action, (mic_router.LOCAL, mic_router.GEMINI, mic_router.DROP))

    def test_local_stt_route_wins_when_ready(self):
        self.assertEqual(route(local_stt_ready=True)[0], mic_router.LOCAL)

    def test_gemini_fallback_while_local_model_loads(self):
        self.assertEqual(route(session_connected=True)[0], mic_router.GEMINI)

    def test_no_route_is_an_explicit_drop_not_silence(self):
        action, detail = route()
        self.assertEqual(action, mic_router.DROP)
        self.assertIn("gemini-offline", detail)

    def test_speaking_guard_drops_frames(self):
        self.assertEqual(route(local_stt_ready=True, speaking=True),
                         (mic_router.IDLE, "jarvis-speaking"))

    def test_mute_drops_frames(self):
        self.assertEqual(route(local_stt_ready=True, muted=True),
                         (mic_router.IDLE, "muted"))

    def test_phone_mic_has_priority(self):
        self.assertEqual(route(local_stt_ready=True, phone_active=True),
                         (mic_router.IDLE, "phone-mic-active"))

    def test_asleep_feeds_detector_and_never_leaves_the_machine(self):
        self.assertEqual(
            route(wake_enabled=True, awake=False, wake_detector_ready=True),
            (mic_router.WAKE, "asleep:feeding-detector"),
        )

    def test_asleep_without_detector_reports_the_stall(self):
        # The old trap: wake mode on, detector missing, JARVIS asleep —
        # nothing could ever hear "Hey Jarvis" again. This must be visible.
        action, detail = route(wake_enabled=True, awake=False,
                               wake_detector_ready=False)
        self.assertEqual(action, mic_router.WAKE)
        self.assertEqual(detail, "asleep:detector-not-ready")

    def test_external_applications_do_not_exist_in_the_routing_inputs(self):
        import inspect

        params = inspect.signature(mic_router.route_frame).parameters
        for forbidden in ("board", "plugin", "external"):
            self.assertNotIn(forbidden, params)


class DropStreakTests(unittest.TestCase):
    def test_one_message_per_outage_and_a_recovery_message(self):
        streak = mic_router.DropStreak()
        first = streak.record(mic_router.DROP)
        self.assertTrue(first)
        for _ in range(1000):
            self.assertIsNone(streak.record(mic_router.DROP))
        self.assertEqual(streak.record(mic_router.LOCAL), "recover")
        self.assertFalse(streak.active)

    def test_recovery_only_after_a_real_outage(self):
        streak = mic_router.DropStreak()
        self.assertIsNone(streak.record(mic_router.LOCAL))
        self.assertIsNone(streak.record(mic_router.IDLE))


class MicStartupOrderTests(unittest.TestCase):
    """Source-level guarantees about main.py's startup order."""

    def setUp(self):
        self.source = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_mic_opens_before_the_gemini_session_loop(self):
        run_src = self.source[self.source.index("async def run(self):"):]
        mic_at = run_src.index("mic_task = asyncio.create_task(self._listen_audio())")
        loop_at = run_src.index("while True:\n", mic_at)
        self.assertLess(mic_at, loop_at,
                        "the microphone task must start before the session loop")

    def test_mic_task_is_reported_on_failure(self):
        self.assertIn("mic_task.add_done_callback(self._report_mic_failure)",
                      self.source)

    def test_routing_goes_through_mic_router(self):
        self.assertIn("mic_router.route_frame(", self.source)
        self.assertIn("from core                      import mic_router", self.source)

    def test_no_external_application_is_referenced_in_the_audio_path(self):
        # AST-based: comments may discuss history; executable code must not
        # reference it. Every Name/Attribute identifier in the mic path is
        # checked.
        import ast

        listen_src = self.source[
            self.source.index("async def _listen_audio(self):"):
            self.source.index("async def _receive_audio(self):")
        ]
        tree = ast.parse(listen_src)
        identifiers = {
            node.id.lower()
            for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr.lower()
            for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for forbidden in _REMOVED_APP_NAMES + ("board", "plugin"):
            self.assertFalse(
                any(forbidden in ident for ident in identifiers),
                f"the mic path must not reference '{forbidden}' in code",
            )

    def test_wake_auto_sleep_requires_a_ready_detector(self):
        watch_src = self.source[
            self.source.index("async def _run_sleep_watch(self)"):self.source.index(
                "# ── Wake word: UI callbacks")
        ]
        self.assertIn("if not (det and det.ready):", watch_src)
        self.assertIn("auto-sleep is paused", watch_src)

    def test_autosleep_trap_message_explains_listening_stays_on(self):
        self.assertIn("listening stays on", self.source)


class RemovedApplicationGuardTests(unittest.TestCase):
    """The removed external board application must stay removed.

    Its names must not appear anywhere in the shipped application — code,
    prompts, docs, config or tests. (This test file is the one exception: the
    names appear here only as the search patterns.)
    """

    def test_no_removed_application_names_anywhere(self):
        offenders: list[str] = []
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in _GUARD_SKIP for part in rel.parts):
                continue
            if rel.parts[0] in _GUARD_SKIP:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for name in _REMOVED_APP_NAMES:
                if name in text:
                    offenders.append(f"{rel} contains {name!r}")
        self.assertEqual(offenders, [], 
                         "the removed external application leaked back in:\n"
                         + "\n".join(offenders))

    def test_no_hand_tracking_board_plugin_or_button_remains(self):
        self.assertEqual(list((ROOT / "plugins").glob("*arehands*")), [])
        ui_src = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn("_bh_toggle", ui_src)
        self.assertNotIn("BAREHANDS_BTN", ui_src)


if __name__ == "__main__":
    unittest.main()
