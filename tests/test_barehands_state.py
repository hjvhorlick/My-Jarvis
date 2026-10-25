import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

bh = importlib.import_module("plugins.barehands")


class FakePlayer:
    def __init__(self):
        self.states = []

    def set_state(self, state, *args, **kwargs):
        self.states.append(state)


class BarehandsStartupStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The module starts a 6-second autostart probe at import. Keep it from
        # touching the temporary board directory during a longer test run.
        cls._orig_cfg = bh._cfg
        bh._cfg = lambda key, default=None: (
            False if key == "autostart" else cls._orig_cfg(key, default)
        )

    @classmethod
    def tearDownClass(cls):
        bh._cfg = cls._orig_cfg

    def test_attach_mirrors_live_state_without_a_board_tool_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_text("# fake board\n", encoding="utf-8")
            saved = {
                "dir": bh._BH_DIR,
                "state": bh._STATE,
                "last": bh._LAST_STATE,
                "hooked": bh._hooked,
                "heartbeat": bh._HEARTBEAT_STARTED,
            }
            bh._BH_DIR = root
            bh._STATE = root / "state"
            bh._LAST_STATE = "idle"
            bh._hooked = False
            bh._HEARTBEAT_STARTED = False
            try:
                player = FakePlayer()
                with patch.object(bh, "_start_state_heartbeat", lambda: None), \
                     patch.object(bh, "_autostart", lambda: None):
                    bh.attach(player)

                state_file = bh._STATE / "state"
                self.assertTrue(state_file.exists())
                self.assertEqual(state_file.read_text(encoding="utf-8"), "idle")

                player.set_state("LISTENING")
                self.assertEqual(state_file.read_text(encoding="utf-8"), "listening")
                self.assertEqual(bh._LAST_STATE, "listening")

                player.set_state("SPEAKING")
                self.assertEqual(state_file.read_text(encoding="utf-8"), "speaking")

                player.set_state("SLEEPING")
                self.assertEqual(state_file.read_text(encoding="utf-8"), "idle")
                self.assertEqual(player.states, [
                    "LISTENING", "SPEAKING", "SLEEPING"
                ])
            finally:
                bh._BH_DIR = saved["dir"]
                bh._STATE = saved["state"]
                bh._LAST_STATE = saved["last"]
                bh._hooked = saved["hooked"]
                bh._HEARTBEAT_STARTED = saved["heartbeat"]

    def test_board_auto_starts_by_default(self):
        fields = {field["key"]: field for field in bh.PLUGIN_SETTINGS["fields"]}
        self.assertTrue(fields["autostart"]["default"])

    def test_normaliser_accepts_both_ui_and_ring_states(self):
        self.assertEqual(bh._normalise_ring_state("THINKING"), "thinking")
        self.assertEqual(bh._normalise_ring_state("listening"), "listening")
        self.assertEqual(bh._normalise_ring_state("MUTED"), "idle")


if __name__ == "__main__":
    unittest.main()
