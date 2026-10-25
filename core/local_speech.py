"""Small non-blocking wrapper around the operating system's local TTS voice."""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class LocalSpeaker:
    """Speak short local responses without making a Gemini request.

    ``pyttsx3`` is initialized and used on one dedicated worker thread because
    SAPI and the eSpeak driver are thread-affine on some operating systems.
    """

    def __init__(self, on_start: Callable[[], None] | None = None,
                 on_done: Callable[[], None] | None = None,
                 logger: Callable[[str], None] = print):
        self._on_start = on_start
        self._on_done = on_done
        self._logger = logger
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=12)
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="JarvisLocalSpeech"
        )
        self._started = False
        self._failed = False

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and not self._failed

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._thread.start()

    def speak(self, text: str) -> bool:
        """Queue speech and return immediately; false if TTS is unavailable/full."""
        text = " ".join(str(text or "").split()).strip()
        if not text or self._failed:
            return False
        self.start()
        try:
            self._queue.put_nowait(text)
            return True
        except queue.Full:
            self._logger("Local speech queue is full; skipping this spoken response.")
            return False

    def stop(self) -> None:
        if self._started:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def _run(self) -> None:
        engine = None
        try:
            import pyttsx3
            engine = pyttsx3.init()
            try:
                rate = engine.getProperty("rate")
                engine.setProperty("rate", max(145, min(185, int(rate * 1.05))))
            except Exception:
                pass
            self._ready.set()
            self._logger("Local speech ready (system voice).")
        except Exception as exc:
            self._failed = True
            self._ready.set()
            self._logger(f"Local speech unavailable: {exc}")
            return

        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                if self._on_start:
                    self._on_start()
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                self._logger(f"Local speech failed: {exc}")
            finally:
                if self._on_done:
                    try:
                        self._on_done()
                    except Exception:
                        pass
