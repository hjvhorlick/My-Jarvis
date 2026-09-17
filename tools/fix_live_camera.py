#!/usr/bin/env python3
"""One-time repair for JARVIS Linux live-camera rendering.

The live camera view was pushing ~30 JPEG/QPixmap updates per second into the
Qt GUI. On low-power systems this can backlog the GUI event queue and make the
camera panel appear black even though the webcam itself is healthy.

This script makes the live stream producer bounded and GUI-friendly:
- max 10 FPS
- only one queued GUI frame at a time
- single-frame OpenCV buffer where supported
- cheap QPixmap scaling instead of SmoothTransformation

Run once from the JARVIS repository root. It edits ui.py in place and creates
ui.py.jarvis-camera-backup before changing it.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui.py"
BACKUP = ROOT / "ui.py.jarvis-camera-backup"

text = UI.read_text(encoding="utf-8")
original = text

# 1) Add a bounded GUI-frame state next to the existing camera stop event.
old = '        self._cam_stop = threading.Event()\n\n        # Camera preview overlay'
new = '''        self._cam_stop = threading.Event()\n        # Keep the Qt event queue bounded: the camera thread must never queue\n        # unlimited JPEG frames on slower CPUs.\n        self._cam_frame_lock = threading.Lock()\n        self._cam_frame_pending = False\n\n        # Camera preview overlay'''
if old not in text:
    raise SystemExit("Could not find camera state block in ui.py")
text = text.replace(old, new, 1)

# 2) Replace the live-frame slot with bounded-frame handling and cheap scaling.
old = '''    def _on_cam_frame(self, data: bytes) -> None:\n        px = QPixmap()\n        px.loadFromData(data)\n        if not px.isNull():\n            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()\n            if w > 1 and h > 1:\n                self._cam_live_lbl.setPixmap(\n                    px.scaled(w, h,\n                              Qt.AspectRatioMode.KeepAspectRatio,\n                              Qt.TransformationMode.SmoothTransformation)\n                )\n'''
new = '''    def _on_cam_frame(self, data: bytes) -> None:\n        # This slot runs on the Qt GUI thread. Always release the producer's\n        # pending flag, even when decoding/scaling fails.\n        try:\n            px = QPixmap()\n            if not px.loadFromData(data) or px.isNull():\n                return\n            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()\n            if w > 1 and h > 1:\n                self._cam_live_lbl.setPixmap(\n                    px.scaled(w, h,\n                              Qt.AspectRatioMode.KeepAspectRatio,\n                              Qt.TransformationMode.FastTransformation)\n                )\n        finally:\n            with self._cam_frame_lock:\n                self._cam_frame_pending = False\n'''
if old not in text:
    raise SystemExit("Could not find _on_cam_frame block in ui.py")
text = text.replace(old, new, 1)

# 3) Replace the high-rate live loop with a bounded 10 FPS loop.
old = '''            cap = cv2.VideoCapture(cam_idx, backend)\n            if not cap.isOpened():\n                cap = cv2.VideoCapture(0)\n            if not cap.isOpened():\n                return\n            # warm-up frames\n            for _ in range(5):\n                cap.read()\n            while not self._cam_stop.wait(0.033) and cap.isOpened():\n                ret, frame = cap.read()\n                if ret and frame is not None:\n                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])\n                    self._cam_frame_sig.emit(buf.tobytes())\n            cap.release()\n'''
new = '''            cap = cv2.VideoCapture(cam_idx, backend)\n            if not cap.isOpened():\n                cap = cv2.VideoCapture(0)\n            if not cap.isOpened():\n                return\n            # Keep only the newest camera frame in the GUI pipeline. Some Linux\n            # V4L2 drivers support this property; harmless when they do not.\n            try:\n                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)\n            except Exception:\n                pass\n\n            # warm-up frames\n            for _ in range(5):\n                if not cap.read()[0]:\n                    break\n\n            # 10 FPS is plenty for a visual assistant and is dramatically lighter\n            # on the Celeron/low-memory Linux machines this app targets. More\n            # importantly, never queue a second Qt frame while one is waiting.\n            while not self._cam_stop.wait(0.10) and cap.isOpened():\n                ret, frame = cap.read()\n                if not ret or frame is None:\n                    continue\n\n                with self._cam_frame_lock:\n                    if self._cam_frame_pending:\n                        continue\n                    self._cam_frame_pending = True\n\n                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])\n                if not ok:\n                    with self._cam_frame_lock:\n                        self._cam_frame_pending = False\n                    continue\n                self._cam_frame_sig.emit(buf.tobytes())\n            cap.release()\n'''
if old not in text:
    raise SystemExit("Could not find _cam_loop block in ui.py")
text = text.replace(old, new, 1)

if text == original:
    raise SystemExit("No changes made")

shutil.copy2(UI, BACKUP)
UI.write_text(text, encoding="utf-8")
print(f"Fixed live camera stream in {UI}")
print(f"Backup: {BACKUP}")
print("Changes: bounded 10 FPS, one queued GUI frame, V4L2 buffer=1, FastTransformation.")
