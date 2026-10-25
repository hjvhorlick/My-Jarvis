"""Regression tests for the dashboard (webapp) voice paths.

The dashboard is the interface the user actually talks through, so the
browser page itself must satisfy the two original requirements:

1. listening starts when the page opens — no button, and nothing else in the
   app may gate the microphone;
2. replies are SPOKEN, not just shown in the chat — with a real verification
   that speech started, an honest specific message when the browser cannot
   speak, and no stale queue of old replies.

These tests pin that behaviour at source level (the repo's established
pattern for browser files, which cannot be imported into CPython).
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "static" / "app.html"


def app_source() -> str:
    return APP.read_text(encoding="utf-8")


class AutoListeningTests(unittest.TestCase):
    def test_listening_starts_when_the_page_opens(self):
        src = app_source()
        self.assertIn("doMic(false)", src,
                      "the page must start listening automatically on load")

    def test_mic_start_is_not_gated_by_any_other_feature(self):
        # The auto-start call must sit at top level, unconditional — inside
        # no "if some feature is on" block.
        import re

        src = app_source()
        start_block = src[src.rindex("Listening starts by itself"):]
        self.assertIn("if (navigator.mediaDevices?.getUserMedia) doMic(false);", start_block)
        # The only condition is browser capability, not app state. Word-boundary
        # match so "dashboard" does not count as the removed board feature.
        for word in ("board", "plugin", "tracking"):
            self.assertIsNone(
                re.search(rf"\b{word}\b", start_block, re.IGNORECASE),
                f"the auto-start block must not reference '{word}'",
            )

    def test_voice_link_reconnects_itself_after_a_drop(self):
        src = app_source()
        self.assertIn("Voice link dropped — reconnecting…", src)
        self.assertIn("setTimeout(() => doMic(false), _reconnectDelay)", src)
        self.assertIn("Math.min(10000, _reconnectDelay * 2)", src)

    def test_manual_stop_disables_reconnect_until_the_user_returns(self):
        src = app_source()
        self.assertIn("_userStopped = true;", src)     # on manual stop
        self.assertIn("_userStopped = false;", src)    # re-armed on live open
        self.assertIn("if (!_userStopped && _authToken) {", src)

    def test_mic_stream_and_context_survive_reconnects(self):
        # Reuse, not recreation: no re-permission prompts, instant reconnect.
        src = app_source()
        self.assertIn("let stream = _micStm;", src)
        self.assertIn("let ctx = _audioCtx;", src)

    def test_suspended_audio_context_asks_for_one_tap_not_silence(self):
        src = app_source()
        self.assertIn("_showTapToStart()", src)
        self.assertIn("Tap once to start listening", src)


class SpokenRepliesTests(unittest.TestCase):
    def test_jarvis_replies_are_spoken_in_the_dashboard(self):
        src = app_source()
        append_block = src[src.index("function append(speaker, text)"):src.index(
            "function sys(text)")]
        self.assertIn("speakReply(text)", append_block)

    def test_speech_start_is_verified_not_assumed(self):
        # The old failure mode: a voice listed but never spoken, forever.
        src = app_source()
        self.assertIn("u.onstart", src)
        self.assertIn("never began speaking", src)
        self.assertIn("3000", src)   # start-verification timeout

    def test_failure_messages_are_specific_and_honest(self):
        src = app_source()
        self.assertIn("no speech voice", src)
        self.assertIn("Browser speech failed", src)
        self.assertIn("the computer's own speakers", src)

    def test_no_stale_queue_of_old_replies(self):
        # A new reply must cancel whatever is still queued, never queue up.
        src = app_source()
        speak_block = src[src.index("function speakReply"):]
        self.assertIn("speechSynthesis.cancel()", speak_block)

    def test_speaker_toggle_persists_across_reloads(self):
        src = app_source()
        self.assertIn('localStorage.getItem("jarvis_speak")', src)
        self.assertIn('localStorage.setItem("jarvis_speak"', src)

    def test_audio_unlocks_on_the_first_user_gesture(self):
        # Browsers block audio until a gesture; the page must self-unlock.
        src = app_source()
        self.assertIn("pointerdown", src)
        self.assertIn("_ttsUnlocked", src)


class DashboardHygieneTests(unittest.TestCase):
    # The removed external application's names, assembled from fragments so
    # this file never itself contains the spellings (the repo-wide guard
    # asserts their absence).
    _FORBIDDEN = (
        "bare" + "hands",
        "my" + "hands",
        "my " + "hands",
    )

    def test_no_removed_application_references(self):
        text = app_source().lower()
        for forbidden in self._FORBIDDEN:
            self.assertNotIn(forbidden, text)

    def test_login_page_stays_untouched_by_voice_autostart(self):
        # Auto-listening belongs to the authenticated app page only.
        login = (ROOT / "dashboard" / "static" / "login.html").read_text(encoding="utf-8")
        self.assertNotIn("getUserMedia", login)
        self.assertNotIn("doMic", login)


if __name__ == "__main__":
    unittest.main()
