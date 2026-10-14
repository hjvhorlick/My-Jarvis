import time

from myhands.browser_camera import BrowserFrameCamera
from myhands.gestures import Observation
from myhands.session import MyHandsSession


class FakeTracker:
    def __init__(self):
        self.closed = False

    def process(self, _frame):
        landmarks = tuple((0.1 + index / 100, 0.2 + index / 120, 0.0) for index in range(21))
        return [Observation(landmarks=landmarks, score=0.97, label="Right")]

    def close(self):
        self.closed = True


def wait_for_event(session, event_type, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for _sequence, event in session.events_after(0):
            if event["type"] == event_type:
                return event
        time.sleep(0.01)
    return None


def test_session_streams_real_landmarks_from_webview_frames():
    camera = BrowserFrameCamera()
    tracker = FakeTracker()
    session = MyHandsSession(camera, lambda: tracker, idle_off_s=30)
    session.start()
    camera.submit_frame(b"in-memory frame")

    event = wait_for_event(session, "hand_landmarks")
    session.stop("user")

    assert event is not None
    assert event["frame_seq"] == 1
    assert len(event["hands"]) == 1
    assert event["hands"][0]["label"] == "Right"
    assert event["hands"][0]["score"] == 0.97
    assert len(event["hands"][0]["landmarks"]) == 21
    assert tracker.closed
