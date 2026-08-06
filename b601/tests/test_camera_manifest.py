"""The camera manifest is experiment state, and it is fixed at record time.

`experiment_registry.md` is explicit that the version axis here is physical as
well as software: a changed camera serial, mount, exposure or resolution is a
new experiment version and invalidates the episodes recorded under the old one.
`pin_check.sh` already gates CAMERA_SERIALS — but until this loader existed the
only field anything read was `serial`. Resolution, frame rate and exposure were
documentation.

That matters more here than for limits.yaml, because a wrong limit is caught by
a guard and a wrong camera configuration is caught by nobody. It becomes a
property of 120-200 irreplaceable teleop episodes.

So the manifest is loaded, and it is VALIDATED, on the same rule the safety
envelope and the pin probes follow: anything that cannot be fully validated is
an error, never a default. Two checks here are specific to this project rather
than generic hygiene, and both are commented where they are enforced:
mismatched frame rates and automatic exposure.
"""
import json

import pytest

from b601.cameras.config import (DEFAULT_CAMERAS, Camera, CameraManifestError,
                                 load_cameras)

SHIPPED = DEFAULT_CAMERAS


def write(tmp_path, mapping):
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(mapping))
    return p


def valid():
    """Two cameras, the configuration this project actually runs."""
    return {
        "cameras": [
            {"name": "agentview", "serial": "DSJ-250318-J",
             "model": "Microdia DSJ-2062-309", "mount": "fixed",
             "device": "/dev/v4l/by-id/usb-DSJ-250318-J_DSJ-2062-309-video-index0",
             "format": "MJPG", "backend": "v4l2",
             "width": 640, "height": 480, "fps": 30,
             "exposure": 156, "gain": 1},
            {"name": "eye_in_hand", "serial": "353322271941",
             "model": "Intel RealSense D405", "mount": "wrist",
             "device": "353322271941",
             "format": "rgb8", "backend": "realsense",
             "width": 640, "height": 480, "fps": 30,
             "exposure": 8000, "gain": 16},
        ]
    }


# --- the shipped manifest -------------------------------------------------

def test_shipped_manifest_loads_and_is_the_source_of_truth():
    """The file the recording session will actually run against must parse."""
    cameras = load_cameras(SHIPPED)
    assert all(isinstance(c, Camera) for c in cameras)
    raw = json.loads(SHIPPED.read_text())["cameras"]
    assert len(cameras) == len(raw)
    assert [c.name for c in cameras] == [e["name"] for e in raw]


def test_default_path_is_anchored_at_the_repo_not_the_cwd(tmp_path, monkeypatch):
    """Anchored at b601/setup/, like the safety envelope and the pin probes.
    A caller standing in another directory must not silently load a different
    camera configuration, or none."""
    monkeypatch.chdir(tmp_path)
    assert load_cameras() == load_cameras(SHIPPED)


def test_shipped_manifest_stays_readable_by_the_existing_pin_probe():
    """`probe.camera_serials` has gated CAMERA_SERIALS since Day 0 and reads
    this same file. Enriching the entries must not break the gate that already
    depends on them — the probe would start raising, and pin_check.sh treats a
    failed probe as fatal."""
    from b601.setup.probe import camera_serials
    serials = camera_serials(SHIPPED)
    expected = sorted(c.serial for c in load_cameras(SHIPPED))
    assert serials == ",".join(expected)


# --- structural validation ------------------------------------------------

def test_missing_file_raises_rather_than_defaulting():
    with pytest.raises(CameraManifestError, match="not found"):
        load_cameras("b601/setup/no_such_cameras.json")


def test_malformed_json_raises(tmp_path):
    p = tmp_path / "cameras.json"
    p.write_text("{not json")
    with pytest.raises(CameraManifestError, match="not valid JSON"):
        load_cameras(p)


def test_missing_cameras_key_raises(tmp_path):
    with pytest.raises(CameraManifestError, match="cameras"):
        load_cameras(write(tmp_path, {"camera": []}))


def test_empty_camera_list_raises(tmp_path):
    """A manifest listing no cameras would pin an empty serial set, which
    compares equal to itself forever while nothing is being recorded."""
    with pytest.raises(CameraManifestError, match="no cameras"):
        load_cameras(write(tmp_path, {"cameras": []}))


@pytest.mark.parametrize("key", ["name", "serial", "model", "mount", "format",
                                "backend", "width", "height", "fps",
                                "exposure", "gain"])
def test_missing_required_key_is_rejected(tmp_path, key):
    cfg = valid()
    del cfg["cameras"][0][key]
    with pytest.raises(CameraManifestError, match=key):
        load_cameras(write(tmp_path, cfg))


def test_unknown_key_is_rejected(tmp_path):
    """Same rule as the safety envelope: a mistyped field is a field that is
    not being applied, and here it would be silently absent from the record."""
    cfg = valid()
    cfg["cameras"][0]["framerate"] = 30
    with pytest.raises(CameraManifestError, match="framerate"):
        load_cameras(write(tmp_path, cfg))


# --- identity -------------------------------------------------------------

def test_duplicate_serial_is_rejected(tmp_path):
    cfg = valid()
    cfg["cameras"][1]["serial"] = cfg["cameras"][0]["serial"]
    with pytest.raises(CameraManifestError, match="duplicate serial"):
        load_cameras(write(tmp_path, cfg))


def test_duplicate_name_is_rejected(tmp_path):
    """Names become dataset observation keys. Two cameras under one key means
    one silently overwrites the other for every frame of every episode."""
    cfg = valid()
    cfg["cameras"][1]["name"] = cfg["cameras"][0]["name"]
    with pytest.raises(CameraManifestError, match="duplicate name"):
        load_cameras(write(tmp_path, cfg))


@pytest.mark.parametrize("name", ["observation.images", "top view", "", "2cam"])
def test_name_unusable_as_a_dataset_key_is_rejected(tmp_path, name):
    """The name is interpolated into `observation.images.<name>`. A dot nests a
    key somewhere unintended, a space is not addressable, and a leading digit
    is not a valid identifier in the tooling that consumes it."""
    cfg = valid()
    cfg["cameras"][0]["name"] = name
    with pytest.raises(CameraManifestError, match="name"):
        load_cameras(write(tmp_path, cfg))


def test_unknown_mount_is_rejected(tmp_path):
    """Mount is not decorative: sim finding 4 turns on it. The wrist camera is
    the only sensor that can verify a grasp, so which camera is which decides
    whether Day-16 verification has an input at all."""
    cfg = valid()
    cfg["cameras"][0]["mount"] = "overhead"
    with pytest.raises(CameraManifestError, match="mount"):
        load_cameras(write(tmp_path, cfg))


# --- capture settings -----------------------------------------------------

@pytest.mark.parametrize("key", ["width", "height", "fps"])
@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_capture_dimension_is_rejected(tmp_path, key, bad):
    cfg = valid()
    for cam in cfg["cameras"]:
        cam[key] = bad
    with pytest.raises(CameraManifestError, match=key):
        load_cameras(write(tmp_path, cfg))


@pytest.mark.parametrize("key", ["width", "height", "fps"])
def test_non_integer_capture_dimension_is_rejected(tmp_path, key):
    """Half a pixel or 14.5 fps is a configuration nobody can reproduce."""
    cfg = valid()
    for cam in cfg["cameras"]:
        cam[key] = 15.5
    with pytest.raises(CameraManifestError, match=key):
        load_cameras(write(tmp_path, cfg))


def test_mismatched_frame_rates_are_rejected(tmp_path):
    """THE CHECK THIS MODULE EXISTS FOR.

    Measured on this machine: the D405 negotiated USB 2.1 and was verified at
    480x270/15, while the top RGB verified 1280x720/30. Recording a 15 fps
    stream alongside a 30 fps one bakes a permanent 33 ms ambiguity into every
    observation of every episode, and ACT consumes the streams as one
    synchronous observation. Frame rate is frozen at record time, so this must
    fail before the first episode, not be discovered in the dataset audit.
    """
    cfg = valid()
    cfg["cameras"][1]["fps"] = 15
    with pytest.raises(CameraManifestError, match="frame rate"):
        load_cameras(write(tmp_path, cfg))


@pytest.mark.parametrize("bad", ["auto", None])
def test_automatic_exposure_is_rejected(tmp_path, bad):
    """`calibration_report.md` requires FIXED exposure. Auto-exposure makes
    ambient lighting a hidden variable that varies within a session and across
    sessions, and it is indistinguishable from policy error afterwards — the
    same shape of defect as the sim track's stale reference coordinate."""
    cfg = valid()
    cfg["cameras"][0]["exposure"] = bad
    with pytest.raises(CameraManifestError, match="exposure"):
        load_cameras(write(tmp_path, cfg))


def test_gain_must_be_recorded_too(tmp_path):
    """Once auto-exposure is off, gain stops adapting and freezes at whatever
    value auto-exposure happened to leave behind. Unrecorded, that is the same
    hidden variable as auto-exposure itself: it changes image noise and
    brightness between sessions and is invisible afterwards."""
    cfg = valid()
    cfg["cameras"][0]["gain"] = "auto"
    with pytest.raises(CameraManifestError, match="gain"):
        load_cameras(write(tmp_path, cfg))


def test_unknown_backend_is_rejected(tmp_path):
    """The driver stack is recorded, not inferred from the model string. It
    decides which controls exist and what "auto exposure off" even means — 1
    (Manual Mode) on V4L2, 0 on RealSense — so guessing it from a product name
    would silently apply the wrong value to the wrong camera."""
    cfg = valid()
    cfg["cameras"][0]["backend"] = "opencv"
    with pytest.raises(CameraManifestError, match="backend"):
        load_cameras(write(tmp_path, cfg))


def test_pixel_format_is_required_to_be_named(tmp_path):
    """Measured on this machine: the top camera offers 640x480 at 30 fps in
    MJPG (lossy) and at 25 fps in YUYV (uncompressed). Same camera, same
    resolution, permanently different image quality in the dataset. The format
    is therefore record-time state, not a capture detail."""
    cfg = valid()
    cfg["cameras"][0]["format"] = ""
    with pytest.raises(CameraManifestError, match="format"):
        load_cameras(write(tmp_path, cfg))


# --- top-level provenance -------------------------------------------------

def test_a_provenance_note_is_allowed_at_the_top_level(tmp_path):
    """JSON has no comments, and `probe.camera_serials` fixed this file's
    format on Day 0. `limits.yaml` marks its provisional values in comments;
    this manifest needs somewhere to say the same thing, or the distinction
    between a measured value and a placeholder is lost."""
    cfg = valid()
    cfg["_note"] = "PROVISIONAL pending the Day-3 capture session"
    assert len(load_cameras(write(tmp_path, cfg))) == 2


def test_unknown_top_level_key_is_rejected(tmp_path):
    """`cameras` misspelt at the top level must not read as an empty manifest."""
    cfg = valid()
    cfg["camera_list"] = []
    with pytest.raises(CameraManifestError, match="camera_list"):
        load_cameras(write(tmp_path, cfg))


# --- accessors ------------------------------------------------------------

def test_wrist_and_fixed_are_addressable_by_mount(tmp_path):
    """Consumers ask for "the wrist camera", not "index 1" — an ordering
    change in the file must not silently repoint grasp verification at the
    camera that cannot resolve the fingers."""
    from b601.cameras.config import by_mount
    cameras = load_cameras(write(tmp_path, valid()))
    assert by_mount(cameras, "wrist").name == "eye_in_hand"
    assert by_mount(cameras, "fixed").name == "agentview"


def test_asking_for_an_absent_mount_raises(tmp_path):
    """Day-16 verification has no fallback sensor. Returning None would let a
    verifier run against nothing and report a grasp it never saw."""
    from b601.cameras.config import by_mount
    cfg = valid()
    del cfg["cameras"][1]
    cameras = load_cameras(write(tmp_path, cfg))
    with pytest.raises(CameraManifestError, match="wrist"):
        by_mount(cameras, "wrist")


def test_record_fps_is_the_single_agreed_rate(tmp_path):
    from b601.cameras.config import record_fps
    assert record_fps(load_cameras(write(tmp_path, valid()))) == 30
