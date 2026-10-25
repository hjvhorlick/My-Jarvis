"""Routing decision for every desktop-microphone frame.

This module is deliberately pure (no numpy, no Qt, no sounddevice, no Gemini)
so the exact gating that decides whether your voice reaches JARVIS can be unit
tested. ``main.py``'s audio callback asks :func:`route_frame` what to do with
each frame; this file is the single source of truth for those gates.

Gates, in order:

1. Wake-word sleep — while JARVIS is asleep the frame goes to the local wake
   detector instead of a transcription route. External applications (a
   hand-tracking board, any plugin) play no part here: their lifecycles are
   independent of the microphone and must never gate it.
2. Mute — the user's explicit mic mute.
3. Phone mic active — the remote dashboard mic has priority.
4. JARVIS speaking — frames are dropped while JARVIS's own voice is playing
   (echo protection). The speaking flag is guaranteed to clear: the local
   speech worker pairs on_start/on_done under a watchdog, and the Gemini
   playback loop clears it on turn completion.
5. Transcription route — local Whisper when it is ready, otherwise the
   connected Gemini session, otherwise an explicit "drop" with the reason so
   the caller can surface it instead of failing silently.
"""
from __future__ import annotations

# Actions returned by route_frame()
WAKE = "wake"        # feed the wake-word detector
LOCAL = "local"      # local Whisper transcription
GEMINI = "gemini"    # stream to the Gemini Live session
IDLE = "idle"        # dropped, expected/recoverable (mute, phone, echo guard)
DROP = "drop"        # dropped, NOT expected — the caller should tell the user why


def route_frame(
    *,
    wake_enabled: bool,
    awake: bool,
    wake_detector_ready: bool,
    speaking: bool,
    muted: bool,
    phone_active: bool,
    local_stt_ready: bool,
    session_connected: bool,
) -> tuple[str, str]:
    """Decide what happens to one microphone frame.

    Returns ``(action, detail)``. ``detail`` is a short machine-readable reason
    used for diagnostics; it is never shown raw to the user.
    """
    # 1. Wake gate. While asleep, audio must never leave the machine, so the
    #    frame is fed only to the local detector. If the detector is not
    #    actually running there is nothing that can hear "Hey Jarvis" — the
    #    caller logs that stalled state; the real fix is in main.py, which
    #    refuses to auto-sleep without a ready detector.
    if wake_enabled and not awake:
        if wake_detector_ready:
            return WAKE, "asleep:feeding-detector"
        return WAKE, "asleep:detector-not-ready"

    # 2-4. Expected, user-visible states.
    if muted:
        return IDLE, "muted"
    if phone_active:
        return IDLE, "phone-mic-active"
    if speaking:
        return IDLE, "jarvis-speaking"

    # 5. A real transcription route.
    if local_stt_ready:
        return LOCAL, "ok"
    if session_connected:
        return GEMINI, "local-stt-not-ready"
    return DROP, "local-stt-not-ready+gemini-offline"


class DropStreak:
    """Tracks a run of dropped frames and emits one message per streak.

    The mic callback runs on a real-time audio thread; it must never log per
    frame (that alone stalls some host APIs) and must never spam. This helper
    converts thousands of dropped frames into exactly two events per outage:
    one "voice input is not being processed" and, later, one "recovered".
    """

    def __init__(self) -> None:
        self.active = False
        self.frames = 0

    def record(self, action: str) -> str | None:
        """Feed one routing action; returns a message when a streak starts."""
        if action != DROP:
            ended = self.active
            self.active = False
            self.frames = 0
            return "recover" if ended else None
        self.frames += 1
        if not self.active:
            self.active = True
            return (
                "Voice input is not being processed yet: local speech "
                "recognition is still loading and the Gemini session is "
                "offline. Spoken requests will work once either one is ready."
            )
        return None
