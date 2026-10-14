"""Camera adapter for frames supplied by the Tauri/WebView camera.

The WebView is the sole webcam owner. This adapter lets the existing My Hands
session consume its JPEG frames without opening a second camera device.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .camera import CameraState


class BrowserFrameCamera:
    """Thread-safe latest-frame source compatible with ``MyHandsSession``."""

    def __init__(self, stall_s: float = 2.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._stall_s = stall_s
        self._clock = clock
        self._running = False
        self._frame: Any = None
        self._seq = 0
        self._last_frame_at = 0.0
        self.state = CameraState.NOT_INITIALIZED
        self.message = "waiting for the WebView camera"

    def start(self) -> None:
        with self._lock:
            self._running = True
            self._frame = None
            self._seq = 0
            self._last_frame_at = self._clock()
            self.state = CameraState.CONNECTING
            self.message = "waiting for camera frames"

    def submit_frame(self, frame: Any) -> bool:
        """Publish one decoded BGR frame; frames remain in memory only."""
        with self._lock:
            if not self._running:
                return False
            self._frame = frame
            self._seq += 1
            self._last_frame_at = self._clock()
            self.state = CameraState.ACTIVE
            self.message = "WebView camera active"
            return True

    def get_frame(self) -> tuple[Any, int] | None:
        with self._lock:
            if not self._running or self._frame is None:
                return None
            if self._clock() - self._last_frame_at > self._stall_s:
                self.state = CameraState.INTERRUPTED
                self.message = "WebView camera stopped sending frames"
                return None
            return self._frame, self._seq

    def status(self) -> dict:
        with self._lock:
            if (self._running and self._frame is not None
                    and self._clock() - self._last_frame_at > self._stall_s):
                self.state = CameraState.INTERRUPTED
                self.message = "WebView camera stopped sending frames"
            return {
                "state": self.state.value,
                "message": self.message,
                "frames_total": self._seq,
                "reconnects": 0,
                "opens_total": 0,
                "closes_total": 0,
            }

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._frame = None
            self.state = CameraState.STOPPED
            self.message = "stopped"
