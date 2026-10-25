"""JARVIS local voice service — speaks local replies without a model call.

This is the "local voice service" whose health messages appear on the server
console marked ``[local-voice]`` (main.py mirrors them into the on-screen log).
It exists so everyday answers ("It's 3:07 PM.", "Opening Gmail.") are spoken
even when the Gemini session is down, and so JARVIS's startup line never
depends on a cloud round-trip.

Design rules (learned from the field failure this module was rewritten for):

* A voice that merely APPEARS in a voice list is not a working voice. The
  service verifies a real synthesis at startup — audio bytes that are actually
  produced — before it reports ready, and every spoken reply is watched from
  start to finish.
* A hung speech engine must never wedge the assistant. Every utterance runs
  under a watchdog; if it cannot finish, the failure is reported with a
  specific, actionable message and the worker moves on. ``on_start`` and
  ``on_done`` are always paired, so the microphone is never left muted behind
  a stuck "speaking" flag.
* On Linux the engines are probed in order of reliability: the eSpeak NG
  shared library (system install, or the bundled ``espeakng-loader`` pip
  package — no system packages needed), the ``espeak-ng``/``espeak`` command,
  ``spd-say`` (speech-dispatcher), and only then ``pyttsx3``. If nothing can
  speak, the error says exactly what to install — it never pretends to have
  spoken, and it never installs anything itself.
"""
from __future__ import annotations

import array
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections.abc import Callable

__all__ = ["LocalSpeaker", "BackendError"]

# Console prefix for every message this service prints. This is the marker
# the UI text promises ("messages are in the server console, marked
# [local-voice]") — keep it stable.
CONSOLE_PREFIX = "[local-voice]"

# Short phrase used to verify an engine before JARVIS trusts it.
_PROBE_TEXT = "Voice check complete."

# espeak_OUTPUT_FORMAT / espeak_POSITION_TYPE constants (from speak_lib.h)
_AUDIO_OUTPUT_RETRIEVAL = 1
_ESPEAK_CHARS_AUTO = 0x0001
_ESPEAK_RATE = 1  # espeakRATE parameter id

# Once the eSpeak shared library has been initialised inside this process it
# cannot be initialised again (same limitation pyttsx3's espeak driver has).
# If a lib backend dies we must not retry it — the CLI takes over instead.
_ESPEAK_LIB_SPENT = False


class BackendError(Exception):
    """A speech backend could not produce (or finish) audio."""


def _rms_16bit(samples: array.array) -> float:
    """Loudness of int16 samples without requiring numpy (probe-time check)."""
    n = len(samples)
    if not n:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / n) ** 0.5


def _default_logger(message: str) -> None:
    print(f"{CONSOLE_PREFIX} {message}")


class _EspeakLibBackend:
    """eSpeak NG through its shared library, synthesising to PCM in-process.

    Chosen first on Linux because it has no subprocess latency and, with the
    ``espeakng-loader`` wheel, needs no system package at all.
    """

    def __init__(self) -> None:
        self._lib = None
        self._rate = 0
        self._chunks: list[array.array] | None = None
        self._callback_ref = None  # keep alive: ctypes callbacks are freed otherwise
        self._lock = threading.Lock()
        self._bundled = False

    # -- loading ------------------------------------------------------------
    def _load(self) -> None:
        import ctypes

        candidates: list[str] = [
            "libespeak-ng.so.1",
            "libespeak.so.1",
            "/usr/local/lib/libespeak-ng.so.1",
        ]
        data_path: bytes | None = None
        lib = None
        for path in candidates:
            try:
                lib = ctypes.cdll.LoadLibrary(path)
                break
            except OSError:
                continue
        if lib is None:
            try:
                import espeakng_loader  # bundled engine (pip), no system package

                lib = ctypes.CDLL(str(espeakng_loader.get_library_path()))
                data_path = str(espeakng_loader.get_data_path()).encode()
                self._bundled = True
            except Exception:
                raise BackendError(
                    "the eSpeak NG shared library was not found "
                    "(looked for libespeak-ng.so.1, libespeak.so.1 and the "
                    "espeakng-loader package)"
                )
        self._lib = lib
        self._data_path = data_path

    def describe(self) -> str:
        if self._lib is None:
            return "eSpeak NG (library)"
        return (
            "eSpeak NG (bundled library — espeakng-loader)"
            if self._bundled
            else "eSpeak NG (system library)"
        )

    # -- engine lifecycle ---------------------------------------------------
    def verify(self, rate_hint: float, timeout: float) -> None:
        """Initialise the library and prove a real synthesis yields audio."""
        global _ESPEAK_LIB_SPENT
        if _ESPEAK_LIB_SPENT:
            raise BackendError("eSpeak library already used once in this process")
        import ctypes

        self._load()
        lib = self._lib
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.espeak_Initialize.restype = ctypes.c_int
        self._rate = lib.espeak_Initialize(
            _AUDIO_OUTPUT_RETRIEVAL, 0, self._data_path, 0
        )
        if self._rate <= 0:
            raise BackendError("espeak_Initialize failed (engine exists but will not start)")
        _ESPEAK_LIB_SPENT = True

        synth_cb = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
        )
        lib.espeak_SetSynthCallback.argtypes = [synth_cb]
        lib.espeak_SetSynthCallback.restype = None
        self._callback_ref = synth_cb(self._on_audio)
        lib.espeak_SetSynthCallback(self._callback_ref)

        try:
            lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
            lib.espeak_SetVoiceByName(b"en-gb")
        except Exception:
            pass
        try:
            lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
            lib.espeak_SetParameter(_ESPEAK_RATE, 175, 0)
        except Exception:
            pass

        self._probe(0.0, timeout)

    def _probe(self, rate_hint: float, timeout: float) -> None:
        chunks = self._synthesize(_PROBE_TEXT, timeout)
        if _rms_16bit(chunks) < 200.0:
            raise BackendError("synthesis produced silence — the engine is not usable")

    # -- synthesis ----------------------------------------------------------
    def _on_audio(self, wav, numsamples, _events) -> int:
        if self._chunks is not None and wav and numsamples > 0:
            self._chunks.extend(array.array("h", (wav[i] for i in range(numsamples))))
        return 0

    def _synthesize(self, text: str, timeout: float) -> array.array:
        """Synthesise to int16 PCM; raises BackendError on failure/timeout."""
        import ctypes

        assert self._lib is not None
        chunks: array.array = array.array("h")
        result: dict = {}

        def run() -> None:
            try:
                with self._lock:  # espeak synthesis is not re-entrant
                    self._chunks = chunks
                    data = text.encode("utf-8")
                    rc = self._lib.espeak_Synth(
                        data, len(data) + 1, 0, 1, 0,
                        _ESPEAK_CHARS_AUTO, None, None,
                    )
                    self._lib.espeak_Synchronize()
                    self._chunks = None
                result["rc"] = rc
            except Exception as exc:  # pragma: no cover - defensive
                result["error"] = exc

        worker = threading.Thread(target=run, daemon=True, name="espeak-synth")
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise BackendError(
                f"eSpeak NG did not finish within {timeout:.0f}s — engine is stalled"
            )
        if "error" in result:
            raise BackendError(f"eSpeak NG synthesis failed: {result['error']}")
        if result.get("rc", 0) != 0:
            raise BackendError(f"eSpeak NG synthesis returned error code {result['rc']}")
        return chunks

    def speak(self, text: str, timeout: float) -> tuple[array.array, int] | None:
        """Synthesise and return (pcm16 samples, sample_rate) for playback."""
        return self._synthesize(text, timeout), self._rate


class _EspeakCliBackend:
    """``espeak-ng`` / ``espeak`` command line, rendering to a temp WAV file.

    The subprocess timeout makes a stalled engine impossible to miss.
    """

    def __init__(self, exe: str) -> None:
        self._exe = exe
        self._rate = 22050

    def describe(self) -> str:
        return f"eSpeak NG (command: {os.path.basename(self._exe)})"

    def verify(self, rate_hint: float, timeout: float) -> None:
        pcm, rate = self._synthesize(_PROBE_TEXT, timeout)
        if _rms_16bit(pcm) < 200.0:
            raise BackendError("synthesis produced silence — the engine is not usable")
        self._rate = rate

    def _synthesize(self, text: str, timeout: float) -> tuple[array.array, int]:
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis-tts-")
        os.close(fd)
        try:
            try:
                subprocess.run(
                    [self._exe, "-v", "en-gb", "-b", "1", "-w", path, "--stdin"],
                    input=text.encode("utf-8"),
                    timeout=timeout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except subprocess.TimeoutExpired:
                raise BackendError(
                    f"{os.path.basename(self._exe)} did not finish within {timeout:.0f}s"
                )
            except subprocess.CalledProcessError as exc:
                raise BackendError(
                    f"{os.path.basename(self._exe)} exited with code {exc.returncode}"
                )
            with wave.open(path, "rb") as wav:
                rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())
            return array.array("h", frames), rate
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"could not read synthesized audio: {exc}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def speak(self, text: str, timeout: float) -> tuple[array.array, int] | None:
        return self._synthesize(text, timeout)


class _SpdSayBackend:
    """speech-dispatcher via ``spd-say``. It plays the audio itself, so there
    are no samples to return — verification means the process ran and finished
    cleanly, which is exactly the "speaking started and finished" contract."""

    def __init__(self, exe: str) -> None:
        self._exe = exe

    def describe(self) -> str:
        return "speech-dispatcher (spd-say; playback by the system speech service)"

    def verify(self, rate_hint: float, timeout: float) -> None:
        self.speak(_PROBE_TEXT, timeout)

    def speak(self, text: str, timeout: float) -> None:
        try:
            subprocess.run(
                [self._exe, "-w", "-r", "20", text],
                timeout=timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except subprocess.TimeoutExpired:
            raise BackendError(
                f"spd-say did not finish within {timeout:.0f}s — speech-dispatcher "
                "may not be running; try: systemctl --user start speech-dispatcher"
            )
        except subprocess.CalledProcessError as exc:
            raise BackendError(
                f"spd-say exited with code {exc.returncode} — is the "
                "speech-dispatcher service installed and running?"
            )


class _PyttsxBackend:
    """pyttsx3 — the system voice wrapper (SAPI on Windows, NSSpeech on macOS,
    eSpeak driver on Linux). Kept last on Linux because its engine is
    thread-affine and can stall silently; the watchdog catches that."""

    def __init__(self) -> None:
        self._engine = None

    def describe(self) -> str:
        return "system voice (pyttsx3)"

    def _init(self) -> None:
        if self._engine is not None:
            return
        import pyttsx3

        self._engine = pyttsx3.init()
        try:
            rate = self._engine.getProperty("rate")
            self._engine.setProperty("rate", max(145, min(185, int(rate * 1.05))))
        except Exception:
            pass

    def _run_say(self, text: str, timeout: float) -> None:
        engine = self._engine
        assert engine is not None
        engine.say(text)
        engine.runAndWait()

    def verify(self, rate_hint: float, timeout: float) -> None:
        self._init()
        # A real probe through the same say/runAndWait path used for replies.
        engine = self._engine
        assert engine is not None
        engine.say(_PROBE_TEXT)
        engine.runAndWait()

    def speak(self, text: str, timeout: float) -> None:
        self._run_say(text, timeout)


def _candidate_backends() -> list:
    """Engine candidates, most reliable first for this operating system."""
    espeak_exe = shutil.which("espeak-ng") or shutil.which("espeak")
    spd_exe = shutil.which("spd-say")
    lib = _EspeakLibBackend()
    cli = _EspeakCliBackend(espeak_exe) if espeak_exe else None
    spd = _SpdSayBackend(spd_exe) if spd_exe else None
    pyttsx = _PyttsxBackend()
    if sys.platform == "win32" or sys.platform == "darwin":
        ordered = [pyttsx, lib, cli, spd]
    else:  # Linux: library → CLI → speech-dispatcher → pyttsx3 last
        ordered = [lib, cli, spd, pyttsx]
    return [b for b in ordered if b is not None]


def _default_player(samples: array.array, rate: int, device=None) -> None:
    """Play int16 mono PCM through sounddevice (same stack as Gemini audio).

    Wakes the output first: desktop sound servers (PipeWire on modern Linux)
    suspend idle outputs, and on some machines the first short utterance after
    an idle period is silently swallowed while the sink wakes up. A 60 ms
    silent burst plus a small gap opens the device so the real audio plays
    from its first syllable.
    """
    import numpy as np
    import sounddevice as sd

    try:
        silence = np.zeros(int(rate * 0.06), dtype=np.float32)
        sd.play(silence, rate, device=device)
        sd.wait()
        time.sleep(0.05)
    except Exception:
        pass  # the wake-up is best-effort; the real play below still runs

    audio = np.frombuffer(samples.tobytes(), dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, rate, device=device)
    sd.wait()


class LocalSpeaker:
    """Queue-driven local speech with verified engines and a watchdog.

    Two threads keep the guarantees straight:

    * ``JarvisLocalVoice`` (the public worker) owns ordering, watchdogs and
      the on_start/on_done callbacks. It never blocks forever, so the mic
      gate driven by those callbacks always opens again.
    * ``JarvisVoiceEngine`` owns the actual engine. Some engines (pyttsx3's
      SAPI/eSpeak drivers) are thread-affine, so all engine calls run on this
      one thread for their whole life. If an utterance stalls past its
      watchdog, the thread is abandoned and a fresh one is created for the
      next engine — the queue never stays wedged behind a hung engine.

    Public API (unchanged contract used by main.py):
      start()                 idempotent; begins engine selection in background
      speak(text) -> bool     queue a reply; False when speech is unavailable
      stop()
      ready                   True once an engine has been verified
      on_start / on_done      always paired, even on engine failure or timeout
    """

    def __init__(
        self,
        on_start: Callable[[], None] | None = None,
        on_done: Callable[[], None] | None = None,
        logger: Callable[[str], None] | None = None,
        player: Callable[..., None] | None = None,
        output_device_provider: Callable[[], object] | None = None,
        probe_timeout: float = 15.0,
    ) -> None:
        self._on_start = on_start
        self._on_done = on_done
        self._logger = logger or _default_logger
        self._player = player or _default_player
        self._device_provider = output_device_provider
        self._probe_timeout = probe_timeout
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=12)
        self._engine_queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._engine_thread: threading.Thread | None = None
        self._started = False
        self._backend = None
        self._failed = False
        self._selecting = threading.Event()
        self._last_error = ""
        self._warned_no_engine = False
        self._retired: set[str] = set()
    @property
    def ready(self) -> bool:
        return self._backend is not None and not self._failed

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def last_error(self) -> str:
        return self._last_error

    def status_line(self) -> str:
        if self._backend is not None:
            return self._backend.describe()
        if self._failed:
            return "no working speech engine"
        return "checking…"

    # ── logging helpers ─────────────────────────────────────────────────────
    def _log(self, message: str) -> None:
        try:
            self._logger(message)
        except Exception:
            pass

    def _set_error(self, message: str) -> None:
        self._last_error = message
        self._log(message)

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._started:
            self._started = True
            self._selecting.set()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="JarvisLocalVoice"
            )
            self._thread.start()

    def stop(self) -> None:
        if self._started:
            for q in (self._queue, self._engine_queue):
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    def cancel(self) -> None:
        """Best-effort interruption (✋ button): drop queued replies and
        silence playback immediately. Unlike :meth:`stop` the service stays
        alive for the next reply. The engine call itself is left to finish or
        hit its watchdog — safe for thread-affine engines."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    # ── public speak ────────────────────────────────────────────────────────
    def speak(self, text: str) -> bool:
        """Queue speech and return immediately.

        False means the text will NOT be spoken: no verified engine is
        available (``last_error`` then holds a specific, actionable reason).
        The caller must keep showing the reply as text in that case.
        """
        text = " ".join(str(text or "").split()).strip()
        if not text:
            return False
        if self._failed:
            return False
        self.start()
        try:
            self._queue.put_nowait(text)
            return True
        except queue.Full:
            self._log("speech queue is full — skipping this spoken reply")
            return False

    # ── engine thread ───────────────────────────────────────────────────────
    def _ensure_engine_thread(self) -> None:
        if self._engine_thread is None or not self._engine_thread.is_alive():
            self._engine_thread = threading.Thread(
                target=self._engine_loop, daemon=True, name="JarvisVoiceEngine"
            )
            self._engine_thread.start()

    def _engine_loop(self) -> None:
        """Runs every engine call for its lifetime (thread-affine engines)."""
        while True:
            job = self._engine_queue.get()
            if job is None:
                break
            kind, backend, text, timeout, device, done_evt, outcome = job
            try:
                if kind == "verify":
                    backend.verify(175.0, timeout)
                    outcome["ok"] = True
                else:
                    produced = backend.speak(text, timeout)
                    if produced is None:
                        outcome["self_played"] = True   # spd-say / pyttsx3 played it
                    else:
                        samples, rate = produced
                        if _rms_16bit(samples) < 50.0:
                            outcome["error"] = "engine produced silence"
                        else:
                            self._player(samples, rate, device=device)
                            outcome["played"] = True
            except BackendError as exc:
                outcome["error"] = str(exc)
            except Exception as exc:
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                done_evt.set()

    def _call_engine(self, backend, kind: str, text: str, timeout: float, device) -> dict:
        """Run one job on the engine thread under a watchdog. Never blocks
        longer than ``timeout``; returns the job's outcome dict."""
        self._ensure_engine_thread()
        done_evt = threading.Event()
        outcome: dict = {}
        try:
            self._engine_queue.put_nowait(
                (kind, backend, text, timeout, device, done_evt, outcome)
            )
        except Exception as exc:
            return {"error": f"internal queue failure: {exc}"}
        if not done_evt.wait(timeout):
            # The engine thread is wedged mid-job. Leave it to die on its own
            # (daemon) and replace it — the next job must not queue behind it.
            self._engine_thread = None
            return {"error": f"engine stalled past the {timeout:.0f}s watchdog"}
        return outcome

    # ── worker ──────────────────────────────────────────────────────────────
    def _run(self) -> None:
        self._activate_backend()
        self._selecting.clear()
        while True:
            text = self._queue.get()
            if text is None:
                break
            if self._backend is None and not self._failed:
                # The previous engine was retired mid-session — probe the
                # remaining candidates before giving up on this utterance.
                self._activate_backend()
            if self._backend is None:
                continue
            self._speak_now(text)

    def _activate_backend(self) -> bool:
        """Probe candidate engines until one really speaks. Never raises."""
        for backend in _candidate_backends():
            name = backend.describe()
            if name in self._retired:
                continue   # it already failed a real utterance this session
            self._log(f"checking speech engine: {name} …")
            outcome = self._call_engine(backend, "verify", "", self._probe_timeout, None)
            if "ok" not in outcome:
                reason = outcome.get("error", "verification did not run")
                self._log(f"engine not usable: {name} — {reason}")
                continue
            self._backend = backend
            self._failed = False
            self._warned_no_engine = False
            self._log(
                f"local voice ready — {name}{self._describe_output()} "
                "(verified with a real synthesis)"
            )
            return True

        self._backend = None
        self._failed = True
        advice = self._install_advice()
        self._last_error = self._ui_error()
        if not self._warned_no_engine:
            self._warned_no_engine = True
            for line in advice:
                self._log(line)
        return False

    @staticmethod
    def _ui_error() -> str:
        """One-line, specific reason shown in the on-screen log when speech
        is unavailable. Points at the console for the full instructions."""
        if sys.platform == "win32":
            return ("Local voice unavailable: the Windows SAPI speech engine "
                    "(pyttsx3) did not start. Replies continue as text.")
        if sys.platform == "darwin":
            return ("Local voice unavailable: the macOS speech engine "
                    "(pyttsx3) did not start. Replies continue as text.")
        return ("Local voice unavailable: no usable speech engine on this "
                "computer — run: pip install espeakng-loader   (or: sudo apt "
                "install espeak-ng), then restart JARVIS. Full details are in "
                "the console, marked [local-voice].")

    def _describe_output(self) -> str:
        """Human-readable output destination for the status line."""
        if isinstance(self._backend, _SpdSayBackend):
            return ""  # speech-dispatcher owns playback; already in its name
        try:
            device = (
                self._device_provider()
                if self._device_provider is not None
                else None
            )
            import sounddevice as sd

            if device is None:
                default = sd.query_devices(kind="output")
                return f" · out: system default ({default['name']})"
            info = sd.query_devices(device)
            return f" · out: {info['name']}"
        except Exception as exc:
            return f" · out: unknown ({type(exc).__name__})"

    @staticmethod
    def _install_advice() -> list[str]:
        """Specific, honest instructions. The app never changes the system
        itself — the exact command is offered and the user decides."""
        if sys.platform == "win32":
            return [
                "No working speech engine for local replies. The Windows SAPI "
                "voice (pyttsx3) failed to start. Replies continue as text in "
                "the chat."
            ]
        if sys.platform == "darwin":
            return [
                "No working speech engine for local replies. The macOS speech "
                "voice (pyttsx3) failed to start. Replies continue as text in "
                "the chat."
            ]
        return [
            "No working speech engine is installed, so local replies cannot be "
            "spoken. Fixes, in order of preference:",
            "  1) pip install espeakng-loader        (no system packages needed)",
            "  2) sudo apt install espeak-ng          (Debian/Ubuntu)",
            "     sudo dnf install espeak-ng          (Fedora)",
            "JARVIS is not allowed to install system packages by itself — run "
            "one of the above, then restart JARVIS.",
            "Until then every reply still appears as text in the chat.",
        ]

    # ── one utterance ───────────────────────────────────────────────────────
    def _utterance_timeout(self, text: str) -> float:
        # eSpeak speaks ~14 chars/s at rate 175; be generous, then cap.
        return float(min(180.0, max(10.0, 6.0 + len(text) / 9.0)))

    def _speak_now(self, text: str) -> None:
        backend = self._backend
        timeout = self._utterance_timeout(text)
        device = None
        if self._device_provider is not None:
            try:
                device = self._device_provider()
            except Exception:
                device = None

        try:
            if self._on_start:
                self._on_start()
        except Exception:
            pass

        outcome = self._call_engine(backend, "speak", text, timeout, device)

        try:
            if self._on_done:
                self._on_done()
        except Exception:
            pass

        if "error" in outcome:
            self._set_error(
                f"could not speak: {outcome['error']} — engine was "
                f"{backend.describe()}"
            )
            self._retire_backend()
        else:
            self._last_error = ""

    def _retire_backend(self) -> None:
        """Retire an engine that passed verification but failed a real
        utterance. Its name is skipped from later re-selection so the next
        candidate gets a turn instead of flapping on the same broken engine."""
        self._retired.add(self._backend.describe() if self._backend else "")
        self._backend = None
        self._failed = False  # a later utterance may activate the next engine


# ── manual self-check ────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover - manual verification entry point
    # Run from the repo root:  python -m core.local_speech
    # Verifies a real engine and plays audio through the normal output path.
    print(f"{CONSOLE_PREFIX} self-check — verifying a real engine and playing audio…")
    finished = threading.Event()

    def done() -> None:
        finished.set()

    speaker = LocalSpeaker(
        on_start=lambda: print(f"{CONSOLE_PREFIX} speech started."),
        on_done=done,
        logger=lambda m: print(f"{CONSOLE_PREFIX} {m}"),
    )
    speaker.start()
    ok = speaker.speak(
        "JARVIS local voice self check. "
        "If you can hear this, the local voice service works."
    )
    if not ok:
        print(f"{CONSOLE_PREFIX} speak() returned False — no engine available.")
        print(f"{CONSOLE_PREFIX} last error: {speaker.last_error}")
        sys.exit(1)
    if not finished.wait(120):
        print(f"{CONSOLE_PREFIX} speech never signalled completion — NOT fixed.")
        sys.exit(1)
    print(f"{CONSOLE_PREFIX} status: {speaker.status_line()}")
    if speaker.last_error:
        print(f"{CONSOLE_PREFIX} last error: {speaker.last_error}")
        sys.exit(1)
    print(f"{CONSOLE_PREFIX} self-check passed.")
