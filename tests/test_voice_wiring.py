"""End-to-end wiring checks for the voice paths (source level).

main.py cannot be imported without PyQt6/PortAudio, so — like the repo's
existing conversation tests — these pin the wiring by reading the real source
that ships, asserting the behavioural contract required after the voice
regressions:

1. local requests are routed locally before Gemini and spoken through the
   local voice service, with text always kept;
2. a failed local voice NEVER pretends to have spoken — its specific error is
   surfaced once;
3. the ✋ interrupt releases both the Gemini audio queue and the local voice;
4. a missing output device degrades to text-only instead of tearing the
   session down (the old code reconnected forever with a dead mic).
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main_source() -> str:
    return (ROOT / "main.py").read_text(encoding="utf-8")


class LocalFirstRoutingWiring(unittest.TestCase):
    def test_known_requests_are_routed_locally_before_gemini(self):
        src = main_source()
        handler = src[src.index("async def _handle_user_text"):]
        router_at = handler.index("handle_local_request, text")
        self.assertLess(router_at, handler.index("send_client_content"),
                        "the local router must run before anything is sent to Gemini")

    def test_local_reply_is_spoken_and_also_logged(self):
        src = main_source()
        handler = src[src.index("async def _handle_user_text"):]
        local_branch = handler[handler.index("if local is not None:"):]
        self.assertIn('self.ui.write_log(f"{self._asst_name}: {local.text}")', local_branch)
        self.assertIn("self._speak_local(local.text)", local_branch)
        self.assertIn("return", local_branch)

    def test_unmatched_requests_go_to_the_live_session(self):
        src = main_source()
        handler = src[src.index("async def _handle_user_text"):]
        self.assertIn("if not self.session:", handler)
        self.assertIn("send_client_content", handler)

    def test_speak_local_surfaces_a_specific_error_once(self):
        src = main_source()
        speak_local = src[src.index("def _speak_local"):src.index("def _on_text_command")]
        self.assertIn("last_error", speak_local)
        self.assertIn("_last_tts_notice", speak_local,
                      "the same failure must not spam the log for every reply")
        self.assertIn("write_log", speak_local)

    def test_gemini_unavailable_message_is_kept(self):
        self.assertIn('Gemini is not connected', main_source())


class LocalVoiceServiceWiring(unittest.TestCase):
    def test_speaker_is_created_with_device_and_log_wiring(self):
        src = main_source()
        self.assertIn("output_device_provider=self._local_output_device", src)
        self.assertIn("logger=self._log_local_speech", src)

    def test_output_device_resolution_never_raises_into_the_speech_worker(self):
        src = main_source()
        resolver = src[src.index("def _local_output_device"):]
        self.assertIn("audio_devices.resolve(get_output_device(), \"output\")", resolver)
        self.assertIn("except Exception:\n            return None", resolver)

    def test_console_marker_is_local_voice(self):
        src = main_source()
        self.assertIn('print(f"[local-voice] {message}")', src)
        # The old marker must not linger anywhere.
        self.assertNotIn("[LocalSpeech]", src)

    def test_local_voice_starts_automatically_at_app_startup(self):
        src = main_source()
        self.assertIn("self._local_speaker.start()", src)

    def test_interrupt_also_silences_the_local_voice(self):
        src = main_source()
        interrupt = src[src.index("def interrupt(self)"):src.index("def speak(self, text: str):")]
        self.assertIn("self._local_speaker.cancel()", interrupt)

    def test_startup_status_speaks_through_the_local_path(self):
        src = main_source()
        startup = src[src.index("async def _send_startup_status"):src.index(
            "# ── Session memory")]
        self.assertIn("self._speak_local(line)", startup)

    def test_speaker_verifies_before_reporting_ready(self):
        core_src = (ROOT / "core" / "local_speech.py").read_text(encoding="utf-8")
        self.assertIn("verified with a real synthesis", core_src)
        self.assertIn("_rms_16bit", core_src)


class OutputDeviceResilienceWiring(unittest.TestCase):
    def test_missing_output_device_degrades_to_text_only_not_reconnect_loop(self):
        src = main_source()
        play = src[src.index("async def _play_audio"):src.index(
            "# ── Startup status")]
        self.assertIn("No usable audio output device", play)
        self.assertIn("running text-only", play)
        # The old behaviour raised straight out of the TaskGroup, which put
        # JARVIS into an endless reconnect loop with a dead mic.
        self.assertNotIn("            if _spk_dev is None:\n                raise", play)

    def test_chosen_speaker_still_falls_back_to_default(self):
        src = main_source()
        play = src[src.index("async def _play_audio"):src.index(
            "# ── Startup status")]
        self.assertIn("using system default", play)


class ReconnectStabilityWiring(unittest.TestCase):
    def test_mic_survives_gemini_reconnects(self):
        # The mic task is created once, outside the reconnect loop.
        src = main_source()
        run_src = src[src.index("async def run(self):"):]
        loop_src = run_src[run_src.index("while True:"):]
        self.assertNotIn("create_task(self._listen_audio())", loop_src)

    def test_stale_gemini_audio_is_discarded_when_local_stt_becomes_ready(self):
        src = main_source()
        loader = src[src.index("async def _load_local_voice"):src.index(
            "def _queue_live_audio")]
        self.assertIn("get_nowait()", loader)

    def test_phone_audio_routes_to_local_stt_when_available(self):
        src = main_source()
        relay = src[src.index("async def _relay_phone_audio"):src.index(
            "def _on_phone_connected")]
        self.assertIn("self._enqueue_local_audio", relay)


if __name__ == "__main__":
    unittest.main()
