"""Local, isolated My Hands tracker for the Tauri UI.

The WebView owns the webcam and sends downscaled JPEG frames over a local
WebSocket. This service reuses the My Hands gesture/tracking engine, returns
landmarks and gesture events, and never opens a second camera or microphone.
Frames are decoded and kept in memory only.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from myhands.browser_camera import BrowserFrameCamera
from myhands.gestures import Config, GestureEngine, SceneObject
from myhands.session import MyHandsSession
from myhands.tracker import MediaPipeHandTracker

MAX_FRAME_BYTES = 1_000_000
MAX_FRAME_WIDTH = 1280
MAX_FRAME_HEIGHT = 720

app = FastAPI(title="Super AI Agent My Hands service", version="0.1.0")
_session_guard = asyncio.Lock()
_active_session: MyHandsSession | None = None


def _make_session(camera: BrowserFrameCamera) -> MyHandsSession:
    return MyHandsSession(
        camera=camera,
        tracker_factory=lambda: MediaPipeHandTracker(max_hands=2),
        engine=GestureEngine(Config(mirror=True)),
        idle_off_s=600.0,
    )


@app.get("/api/myhands/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "myhands-sidecar"}


@app.get("/api/myhands/status")
def status() -> dict[str, Any]:
    session = _active_session
    if session is None:
        return {"running": False, "camera_on": False, "tracker_available": True}
    return session.status() | {"tracker_available": True}


def _decode_jpeg(data: bytes):
    if not data or len(data) > MAX_FRAME_BYTES:
        return None
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    height, width = frame.shape[:2]
    if width < 2 or height < 2 or width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
        return None
    return frame


def _set_scene(session: MyHandsSession, payload: dict[str, Any]) -> None:
    """Accept a bounded scene snapshot from the UI for existing grab/drag rules."""
    raw_objects = payload.get("objects")
    if not isinstance(raw_objects, list) or len(raw_objects) > 50:
        return
    objects: list[SceneObject] = []
    try:
        for item in raw_objects:
            if not isinstance(item, dict):
                return
            values = (item["id"], item["x"], item["y"], item["w"], item["h"], item.get("z", 0))
            object_id = str(values[0])
            x, y, width, height = (float(value) for value in values[1:5])
            z = int(values[5])
            if (not object_id or len(object_id) > 64 or not all(
                0.0 <= value <= 1.0 for value in (x, y, width, height)
            ) or width == 0.0 or height == 0.0 or x + width > 1.0 or y + height > 1.0):
                return
            objects.append(SceneObject(object_id, x, y, width, height, z))
    except (KeyError, TypeError, ValueError, OverflowError):
        return
    session.set_scene(objects)


@app.websocket("/ws/myhands")
async def myhands_socket(websocket: WebSocket) -> None:
    global _active_session
    await websocket.accept()

    camera = BrowserFrameCamera()
    session = _make_session(camera)
    async with _session_guard:
        if _active_session is not None:
            await websocket.close(code=1013, reason="My Hands is already active in another window")
            return
        _active_session = session

    session.start()
    sender: asyncio.Task | None = None

    async def send_events() -> None:
        last_seq = 0
        while True:
            events = session.events_after(last_seq)
            for sequence, event in events:
                await websocket.send_json({"seq": sequence, "event": event})
                last_seq = sequence
            if not session.running and not events:
                try:
                    await websocket.close(code=1000, reason="My Hands session ended")
                except Exception:
                    pass
                return
            await asyncio.sleep(0.025)

    sender = asyncio.create_task(send_events())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                frame = _decode_jpeg(data)
                if frame is None:
                    await websocket.send_json({
                        "event": {"type": "transport_error", "message": "Invalid camera frame."}
                    })
                    continue
                camera.submit_frame(frame)
                continue

            text = message.get("text")
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("type") == "scene":
                    _set_scene(session, payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        # A dropped UI or frame decoder failure must still release the session/grab.
        pass
    finally:
        await asyncio.to_thread(session.stop, "user")
        if sender is not None:
            try:
                await asyncio.wait_for(sender, timeout=0.5)
            except (asyncio.TimeoutError, Exception):
                sender.cancel()
        async with _session_guard:
            if _active_session is session:
                _active_session = None
