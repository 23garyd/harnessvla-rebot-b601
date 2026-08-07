"""The recording command's camera config is DERIVED, never typed twice.

`lerobot-record` takes `--robot.cameras` as JSON. Hand-writing it would create a
second description of the cameras alongside `cameras.json`, and the two would
drift — at which point the manifest documents a configuration no episode was
recorded under, and `CAMERA_SERIALS` pins something that was not used.

Same rule as `URDF_EE_FRAME`, which is read from the driver rather than written
into the pin a second time: a value that can disagree with the one in use is not
a pin.

The camera NAMES matter most. They become LeRobot observation keys, and through
them the dataset feature names — `observation.images.agentview`. They are fixed
at record time and renaming them later invalidates every episode.
"""
import pytest

from b601.cameras.config import load_cameras
from b601.cameras.lerobot_config import LerobotConfigError, cameras_arg


def test_the_manifest_names_become_the_observation_keys():
    arg = cameras_arg(load_cameras())
    assert set(arg) == {"agentview", "eye_in_hand"}


def test_the_uvc_camera_maps_to_the_opencv_backend_by_stable_path():
    """index_or_path, not an index: /dev/videoN renumbers across replugs, and
    it demonstrably did on this machine — the D405 and the webcam swapped
    ranges twice in one day."""
    cam = cameras_arg(load_cameras())["agentview"]
    assert cam["type"] == "opencv"
    assert cam["index_or_path"].startswith("/dev/v4l/by-id/")
    assert (cam["width"], cam["height"], cam["fps"]) == (640, 480, 30)


def test_the_realsense_maps_to_the_d405_colour_backend_by_serial():
    """Addressed by serial because its by-id path is not stable: the D405
    presents a different USB descriptor on USB 2 than on USB 3."""
    cam = cameras_arg(load_cameras())["eye_in_hand"]
    assert cam["type"] == "realsense_d405_color"
    assert cam["serial_number_or_name"] == "353322271941"
    assert (cam["width"], cam["height"], cam["fps"]) == (640, 480, 30)


def test_every_field_comes_from_the_manifest(tmp_path):
    """Change the manifest, and the recording command changes with it."""
    import json
    from b601.cameras.config import load_cameras as load
    raw = json.loads((__import__("pathlib").Path(
        "b601/setup/cameras.json")).read_text())
    for entry in raw["cameras"]:
        entry["width"], entry["height"], entry["fps"] = 320, 240, 15
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(raw))
    arg = cameras_arg(load(p))
    assert all((c["width"], c["height"], c["fps"]) == (320, 240, 15)
               for c in arg.values())


def test_an_unknown_backend_raises_rather_than_guessing(tmp_path):
    """A backend nobody mapped must not silently produce an opencv config
    pointed at a RealSense serial."""
    import json
    from b601.cameras.config import Camera
    bogus = Camera(name="x", serial="1", model="m", mount="fixed", device="/d",
                   format="MJPG", backend="v4l2", width=640, height=480,
                   fps=30, exposure=1.0, gain=1.0)
    bogus = type(bogus)(**{**bogus.__dict__, "backend": "gstreamer"})
    with pytest.raises(LerobotConfigError, match="gstreamer"):
        cameras_arg([bogus])


def test_the_json_round_trips_through_the_shell_argument():
    """It is passed on a command line, so it must survive json.dumps/loads."""
    import json
    arg = cameras_arg(load_cameras())
    assert json.loads(json.dumps(arg)) == arg


# --- the pixel format must survive the derivation -------------------------

def test_the_manifest_format_becomes_the_opencv_fourcc():
    """FOUND ON HARDWARE, and it was a straight omission on my part.

    Without fourcc, OpenCV negotiates the camera's default — YUYV — and this
    camera caps at 25 fps in YUYV at 640x480 while offering 30 only in MJPG.
    lerobot-record then aborted with 'failed to set fps=30 (actual_fps=25.0)'.

    The manifest has recorded `format` from the start precisely because it is
    record-time state: same camera, same resolution, permanently different
    image quality and frame rate. Deriving the config and then dropping that
    field recreated exactly the drift the derivation exists to prevent."""
    cam = cameras_arg(load_cameras())["agentview"]
    assert cam["fourcc"] == "MJPG"


def test_the_realsense_colour_stream_format_is_carried_too():
    """Same reasoning; rgb8 happens to be the default, which is why an
    omission here would have gone unnoticed rather than failing loudly."""
    cam = cameras_arg(load_cameras())["eye_in_hand"]
    assert cam["color_stream_format"] == "rgb8"


def test_a_format_change_in_the_manifest_reaches_the_argument(tmp_path):
    import json
    from pathlib import Path
    from b601.cameras.config import load_cameras as load
    raw = json.loads(Path("b601/setup/cameras.json").read_text())
    for entry in raw["cameras"]:
        if entry["backend"] == "v4l2":
            entry["format"] = "YUYV"
            entry["fps"] = 25
        else:
            entry["fps"] = 25
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(raw))
    assert cameras_arg(load(p))["agentview"]["fourcc"] == "YUYV"
