import unittest
from pathlib import Path

from actions.proactive import ProactiveEngine

ROOT = Path(__file__).resolve().parents[1]


class ProactiveEngineTests(unittest.TestCase):
    def test_empty_event_cannot_trigger_speech(self):
        engine = ProactiveEngine()
        self.assertTrue(engine.seen(""))
        self.assertTrue(engine.seen("   \n "))
        self.assertEqual(engine.build_alert_prompt(""), "")

    def test_duplicate_events_are_suppressed(self):
        engine = ProactiveEngine()
        event = "[SYSTEM_ALERT] CPU temperature is 91°C"
        self.assertFalse(engine.seen(event))

        engine.remember(event)
        self.assertTrue(engine.seen(event))
        self.assertTrue(engine.seen("  [system_alert]   cpu temperature is 91°C "))
        self.assertFalse(engine.seen("[SYSTEM_ALERT] Disk space is low"))

    def test_alert_prompt_is_short_specific_and_non_conversational(self):
        engine = ProactiveEngine()
        engine.remember("[SYSTEM_ALERT] CPU temperature was high")
        prompt = engine.build_alert_prompt(
            "[MONITOR_ALERT] New AI headline",
            memory={},
            recent_turns=["User: monitor AI news"],
            monitors=["AI news"],
        )
        low = prompt.lower()
        self.assertIn("new ai headline", low)
        self.assertIn("one short sentence", low)
        self.assertIn("never initiate small talk", low)
        self.assertIn("do not repeat", low)
        self.assertIn("cpu temperature was high", low)
        self.assertIn("monitor ai news", low)

    def test_near_duplicate_system_alerts_are_suppressed(self):
        engine = ProactiveEngine()
        engine.remember(
            "[SYSTEM_ALERT] CPU usage has been critically high (91%) for several seconds."
        )
        self.assertTrue(engine.seen(
            "[SYSTEM_ALERT] CPU usage has been critically high (97%) for several seconds."
        ))

    def test_duplicate_expires_after_window(self):
        engine = ProactiveEngine(duplicate_window=0)
        engine.remember("event A")
        self.assertFalse(engine.seen("event A"))

    def test_history_is_bounded(self):
        engine = ProactiveEngine(max_history=2)
        for i in range(5):
            engine.remember(f"event {i}")
        self.assertTrue(engine.seen("event 4"))
        self.assertFalse(engine.seen("event 0"))


class PromptPolicyTests(unittest.TestCase):
    def test_system_prompt_bans_generic_conversation(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8").lower()
        self.assertIn("do not initiate small talk", prompt)
        self.assertIn("never use a canned opener", prompt)
        self.assertIn("one specific question", prompt)
        self.assertIn("silence is the correct response", prompt)
        self.assertIn("if there is no concrete event, stay completely silent", prompt)

    def test_live_startup_is_awake_and_attaches_state_bridge(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("self._awake            = True", source)
        self.assertIn("self._plugin_registry.attach(self.ui)", source)
        self.assertIn('self.ui.write_log("SYS: JARVIS online.")', source)
        self.assertNotIn("tg.create_task(self._run_proactive_mode())", source)


if __name__ == "__main__":
    unittest.main()
