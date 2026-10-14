from myhands.browser_camera import BrowserFrameCamera
from myhands.camera import CameraState


def test_webview_frame_camera_accepts_only_while_running():
    camera = BrowserFrameCamera()
    camera.submit_frame("ignored")
    assert camera.get_frame() is None

    camera.start()
    assert camera.state == CameraState.CONNECTING
    frame = object()
    assert camera.submit_frame(frame)
    result = camera.get_frame()
    assert result is not None
    assert result[0] is frame
    assert result[1] == 1

    camera.stop()
    assert camera.state == CameraState.STOPPED
    assert camera.get_frame() is None
    assert not camera.submit_frame("ignored")


def test_webview_frame_camera_marks_a_stalled_stream():
    now = [10.0]
    camera = BrowserFrameCamera(stall_s=2.0, clock=lambda: now[0])
    camera.start()
    camera.submit_frame("frame")
    assert camera.get_frame() is not None

    now[0] += 2.1
    assert camera.get_frame() is None
    assert camera.state == CameraState.INTERRUPTED
    assert "stopped sending" in camera.status()["message"]
