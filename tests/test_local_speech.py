"""Regression tests for the local voice service (core/local_speech.py).

The field failure: JARVIS printed "could not speak" style notices forever —
a voice was listed but never actually spoken, and no one checked that speech
really starts and finishes. These tests pin the contract:

* an engine is used only after a REAL synthesis is verified (bytes, not a
  voice-list entry);
* on_start/on_done are always paired — the mic gate can never be left shut
  behind a stuck "speaking" flag;
* a stalled engine hits the watchdog, is retired, and the failure message is
  specific and actionable;
* when no engine exists the reply is NOT spoken (no fake success), and the
  error says exactly what to install — the app never installs system packages
  by itself.
"""
import ast
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

from core import local_speech as ls

ROOT = Path(__file__).resolve().parents[1]


def _wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not cond():
        time.sleep(0.02)
    return bool(cond())


def make_speaker(**kwargs):
    defaults = dict(
        logger=lambda m: None,
        player=lambda samples, rate, device=None: None,
    )
    defaults.update(kwargs)
    return ls.LocalSpeaker(**defaults)


class FakeBackend:
    """Records calls; synthesises fake non-silent audio."""

    def __init__(self, name="fake engine", fail_verify=None, fail_speak=None,
                 stall_speak=False, samples=None):
        self.name = name
        self.fail_verify = fail_verify
        self.fail_speak = fail_speak
        self.stall_speak = stall_speak
        self.verify_calls = 0
        self.spoken = []
        self.samples = samples or _loud_samples()

    def describe(self):
        return self.name

    def verify(self, rate_hint, timeout):
        self.verify_calls += 1
        if self.fail_verify:
            raise ls.BackendError(self.fail_verify)

    def speak(self, text, timeout):
        if self.stall_speak:
            time.sleep(timeout + 5)   # ignored: the worker abandons this thread
        if self.fail_speak:
            raise ls.BackendError(self.fail_speak)
        self.spoken.append(text)
        return (self.samples, 22050)


def _loud_samples():
    import array

    return array.array("h", [(1200 if i % 2 == 0 else -1200) for i in range(2205)])


class SilenceStub:
    """An engine that 'succeeds' but produces silence — must be rejected."""

    def __init__(self):
        self.verify_calls = 0

    def describe(self):
        return "silent engine"

    def verify(self, rate_hint, timeout):
        self.verify_calls += 1
        if self.verify_calls == 1:
            raise ls.BackendError("synthesis produced silence — the engine is not usable")

    def speak(self, text, timeout):
        raise ls.BackendError("synthesis produced silence")


class BackendSelectionTests(unittest.TestCase):
    def test_first_verified_engine_is_used(self):
        good = FakeBackend("good engine")
        with patch.object(ls, "_candidate_backends", lambda: [good]):
            spk = make_speaker()
            spk.start()
            self.assertTrue(spk.speak("hello"))
            deadline = time.time() + 5
            while time.time() < deadline and not good.spoken:
                time.sleep(0.02)
            self.assertEqual(good.spoken, ["hello"])
            self.assertTrue(spk.ready)
            self.assertEqual(spk.status_line(), "good engine")

    def test_silent_engine_is_rejected_and_next_engine_is_used(self):
        silent = SilenceStub()
        good = FakeBackend("good engine")
        with patch.object(ls, "_candidate_backends", lambda: [silent, good]):
            spk = make_speaker()
            spk.start()
            deadline = time.time() + 5
            while time.time() < deadline and spk._backend is not good:
                time.sleep(0.02)
            self.assertIs(spk._backend, good)
            self.assertGreaterEqual(silent.verify_calls, 1)

    def test_no_engine_means_failed_and_specific_error(self):
        def candidates():
            return [FakeBackend("broken", fail_verify="no such engine")]

        with patch.object(ls, "_candidate_backends", lambda: candidates()):
            spk = make_speaker()
            spk.start()
            deadline = time.time() + 5
            while time.time() < deadline and not spk.failed:
                time.sleep(0.02)
            self.assertTrue(spk.failed)
            self.assertFalse(spk.ready)
            self.assertFalse(spk.speak("anything"))
            self.assertIn("engine", spk.last_error.lower())

    def test_speak_before_verification_queues_and_does_not_lose_text(self):
        good = FakeBackend("good engine")
        with patch.object(ls, "_candidate_backends", lambda: [good]):
            spk = make_speaker()
            spk.start()
            # speak() returns True immediately even while selection runs; the
            # text must reach the engine once verified.
            self.assertTrue(spk.speak("queued early"))
            deadline = time.time() + 5
            while time.time() < deadline and not good.spoken:
                time.sleep(0.02)
            self.assertEqual(good.spoken, ["queued early"])


class SpeakingContractTests(unittest.TestCase):
    def test_on_start_and_on_done_are_always_paired(self):
        good = FakeBackend("good engine")
        events = []
        with patch.object(ls, "_candidate_backends", lambda: [good]):
            spk = make_speaker(
                on_start=lambda: events.append("start"),
                on_done=lambda: events.append("done"),
            )
            spk.start()
            spk.speak("pair me")
            _wait_until(lambda: len(good.spoken) == 1)
            _wait_until(lambda: events == ["start", "done"])
            self.assertEqual(events, ["start", "done"])

    def test_failed_speech_still_fires_on_done(self):
        bad = FakeBackend("bad engine", fail_speak="driver exploded")
        events = []
        with patch.object(ls, "_candidate_backends", lambda: [bad]):
            spk = make_speaker(
                on_start=lambda: events.append("start"),
                on_done=lambda: events.append("done"),
            )
            spk.start()
            _wait_until(lambda: spk._backend is bad)
            spk.speak("will fail")
            _wait_until(lambda: events == ["start", "done"])
            self.assertEqual(events, ["start", "done"])
            self.assertIn("could not speak", spk.last_error)
            self.assertIn("driver exploded", spk.last_error)

    def test_stalled_engine_hits_the_watchdog_and_releases_the_mic(self):
        stall = FakeBackend("stalling engine", stall_speak=True)
        events = []
        with patch.object(ls, "_candidate_backends", lambda: [stall]):
            spk = make_speaker(
                on_start=lambda: events.append("start"),
                on_done=lambda: events.append("done"),
            )
            spk.start()
            _wait_until(lambda: spk._backend is stall)
            spk._utterance_timeout = lambda text: 0.5   # tighten the watchdog
            spk.speak("stuck")
            _wait_until(lambda: events == ["start", "done"], timeout=5)
            self.assertEqual(events, ["start", "done"])
            self.assertIn("stalled", spk.last_error.lower())
            # The wedged engine must be retired so later utterances retry
            # selection instead of queueing behind the stall forever.
            self.assertIsNone(spk._backend)

    def test_retired_engine_recovers_on_next_utterance(self):
        flaky = FakeBackend("flaky", fail_speak="one bad day")
        good = FakeBackend("steady engine")
        candidates = [flaky, good]
        with patch.object(ls, "_candidate_backends", lambda: list(candidates)):
            spk = make_speaker()
            spk.start()
            _wait_until(lambda: spk._backend is flaky)
            spk.speak("break it")
            _wait_until(lambda: spk._backend is good)
            spk.speak("and recover")
            _wait_until(lambda: good.spoken == ["and recover"])
            self.assertEqual(good.spoken, ["and recover"])


class CancellationTests(unittest.TestCase):
    def test_cancel_drops_queued_replies_and_keeps_service_alive(self):
        good = FakeBackend("good engine")
        done = threading.Event()
        with patch.object(ls, "_candidate_backends", lambda: [good]):
            spk = make_speaker(on_done=lambda: done.set())
            spk.start()
            _wait_until(lambda: spk._backend is good)
            spk.speak("first")
            done.wait(5)
            spk.speak("queued one")
            spk.speak("queued two")
            spk.cancel()
            _wait_until(lambda: spk._queue.qsize() == 0)
            self.assertFalse(spk.failed)
            self.assertTrue(spk.speak("still working"))
            _wait_until(lambda: "still working" in good.spoken)


class InstallAdviceTests(unittest.TestCase):
    def test_linux_advice_names_the_exact_requirement(self):
        with patch.object(ls.sys, "platform", "linux"):
            advice = "\n".join(ls.LocalSpeaker._install_advice())
        self.assertIn("espeakng-loader", advice)
        self.assertIn("sudo apt install espeak-ng", advice)
        self.assertIn("not allowed to install system packages by itself", advice)
        self.assertIn("text in the chat", advice)

    def test_ui_error_is_single_line_and_actionable(self):
        with patch.object(ls.sys, "platform", "linux"):
            err = ls.LocalSpeaker._ui_error()
        self.assertLessEqual(len(err.lines()) if hasattr(err, "lines") else len(err.splitlines()), 3)
        self.assertIn("espeakng-loader", err)


class DefaultPlayerTests(unittest.TestCase):
    def _install_fake_audio_stack(self):
        """Stub numpy + sounddevice inside the player's import scope."""
        import types

        calls = []

        class FakeArray(list):
            def astype(self, _dtype):
                return FakeArray(self)

            def __truediv__(self, scalar):
                return FakeArray(v / scalar for v in self)

        fake_np = types.ModuleType("numpy")
        fake_np.zeros = lambda n, dtype=None: FakeArray([0.0] * n)
        fake_np.frombuffer = lambda b, dtype=None: FakeArray([0] * (len(b) // 2))
        fake_np.float32 = "float32"
        fake_np.int16 = "int16"

        fake_sd = types.ModuleType("sounddevice")
        fake_sd.play = lambda audio, rate, device=None: calls.append(
            ("play", len(audio), rate, device)
        )
        fake_sd.wait = lambda: calls.append(("wait",))

        return calls, fake_np, fake_sd

    def test_player_wakes_the_output_before_speaking(self):
        # PipeWire suspends idle outputs; the first utterance after idle can
        # be swallowed. The player must open the device (silent burst + gap)
        # before the real audio — observed live on an Ubuntu laptop.
        import array as _array

        import sys

        calls, fake_np, fake_sd = self._install_fake_audio_stack()
        old = {k: sys.modules.get(k) for k in ("numpy", "sounddevice")}
        sys.modules["numpy"] = fake_np
        sys.modules["sounddevice"] = fake_sd
        try:
            samples = _array.array("h", [1000, -1000] * 50)
            ls._default_player(samples, 22050, device=None)
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["play", "wait", "play", "wait"])
        # First burst is the 60 ms wake-up silence, then the speech itself.
        self.assertEqual(calls[0][1], int(22050 * 0.06))
        self.assertEqual(calls[2][1], 100)

    def test_player_still_speaks_if_the_wake_up_fails(self):
        import array as _array

        import sys
        import types

        calls, fake_np, fake_sd = self._install_fake_audio_stack()

        attempts = []

        def broken_play(audio, rate, device=None):
            attempts.append(len(audio))
            if len(attempts) == 1:   # the wake-up burst fails
                raise OSError("device unavailable")
            calls.append(("play", len(audio), rate, device))

        fake_sd.play = broken_play
        old = {k: sys.modules.get(k) for k in ("numpy", "sounddevice")}
        sys.modules["numpy"] = fake_np
        sys.modules["sounddevice"] = fake_sd
        try:
            samples = _array.array("h", [1000, -1000] * 50)
            ls._default_player(samples, 22050)
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["play", "wait"])


if __name__ == "__main__":
    unittest.main()
