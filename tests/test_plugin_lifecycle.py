import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import plugin_loader

_GOOD = '''
PLUGIN = {
    "name": "good_probe",
    "description": "A valid test plugin.",
    "parameters": {"type": "OBJECT", "properties": {}},
}
ATTACHED = None

def run(parameters):
    return "ok"

def attach(player=None):
    global ATTACHED
    ATTACHED = player
'''

_BAD = '''
PLUGIN = {
    "name": "bad_probe",
    "description": "A plugin whose attach hook fails.",
    "parameters": {"type": "OBJECT", "properties": {}},
}

def run(parameters):
    return "ok"

def attach():
    raise RuntimeError("intentional test failure")
'''

_NOARG = '''
PLUGIN = {
    "name": "noarg_probe",
    "description": "A plugin with a no-argument attach hook.",
    "parameters": {"type": "OBJECT", "properties": {}},
}
CALLED = False

def run(parameters):
    return "ok"

def attach():
    global CALLED
    CALLED = True
'''


class PluginAttachTests(unittest.TestCase):
    def setUp(self):
        self._modules = (
            "plugins.a_good", "plugins.b_bad", "plugins.c_noarg",
        )
        for name in self._modules:
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in self._modules:
            sys.modules.pop(name, None)

    def test_attach_runs_at_startup_and_isolates_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a_good.py").write_text(_GOOD, encoding="utf-8")
            (folder / "b_bad.py").write_text(_BAD, encoding="utf-8")
            (folder / "c_noarg.py").write_text(_NOARG, encoding="utf-8")
            logs = []
            with patch.object(plugin_loader, "get_plugin_enabled", return_value=True):
                registry = plugin_loader.discover_plugins(
                    folder, core_tool_names=set(), logger=logs.append
                )
                player = object()
                registry.attach(player)

            self.assertIs(sys.modules["plugins.a_good"].ATTACHED, player)
            self.assertTrue(sys.modules["plugins.c_noarg"].CALLED)
            self.assertTrue(
                any("bad_probe" in line and "attach()" in line for line in logs)
            )
            self.assertEqual(set(registry._plugins), {
                "good_probe", "bad_probe", "noarg_probe"
            })


if __name__ == "__main__":
    unittest.main()
