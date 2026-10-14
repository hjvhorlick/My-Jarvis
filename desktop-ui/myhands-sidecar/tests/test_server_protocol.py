from server import _set_scene


class SceneRecorder:
    def __init__(self):
        self.objects = None

    def set_scene(self, objects):
        self.objects = objects


def test_scene_protocol_registers_bounded_objects():
    session = SceneRecorder()
    _set_scene(session, {
        "type": "scene",
        "objects": [{"id": "glass-card", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25, "z": 10}],
    })

    assert session.objects is not None
    assert len(session.objects) == 1
    obj = session.objects[0]
    assert (obj.id, obj.x, obj.y, obj.w, obj.h, obj.z) == ("glass-card", 0.1, 0.2, 0.3, 0.25, 10)


def test_scene_protocol_rejects_objects_outside_camera_bounds():
    session = SceneRecorder()
    _set_scene(session, {
        "objects": [{"id": "outside", "x": 0.9, "y": 0.1, "w": 0.2, "h": 0.2}],
    })

    assert session.objects is None


def test_scene_protocol_rejects_malformed_snapshots_without_partial_update():
    session = SceneRecorder()
    _set_scene(session, {
        "objects": [
            {"id": "valid", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
            {"id": "invalid", "x": 0, "y": 0, "w": 0, "h": 0.2},
        ],
    })

    assert session.objects is None
