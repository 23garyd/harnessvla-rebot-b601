"""Load the camera manifest from b601/setup/cameras.json.

WHY THIS IS A GUARD AND NOT A CONVENIENCE. A wrong safety limit is caught by a
guard on the next command. A wrong camera configuration is caught by nobody: it
becomes a permanent property of 120-200 teleop episodes that cannot be
regenerated. `experiment_registry.md` states the consequence — a changed
serial, mount, exposure or resolution is a new experiment version and
invalidates the episodes recorded under the old one.

`pin_check.sh` has gated CAMERA_SERIALS since Day 0, but `probe.camera_serials`
reads exactly one field per entry. Everything else the plan requires of the
manifest — model, mount, resolution, frame rate, fixed exposure — was
documentation. This is what makes it data.

Same rule as `b601.safety.config` and the pin probes: anything that cannot be
fully validated is an ERROR, never a fallback to a default. A manifest that
fails to load must stop the session, because the alternative is recording under
a configuration nobody chose.

WHAT THIS DOES NOT COVER, stated here rather than discovered later:

  - It does not talk to a camera. Nothing here confirms the listed serial is
    present, that the device path resolves, or that the sensor accepted the
    requested mode. A camera can silently deliver a different resolution than
    it was asked for; only capture proves otherwise.
  - It does not validate `exposure` numerically beyond "a positive number".
    The value is in each driver's native units — microseconds for RealSense,
    device-defined steps for UVC — so it is RECORDED, not interpreted. Two
    cameras with the same integer are not equally exposed.
  - It does not check timestamp alignment. Agreeing on a nominal frame rate is
    not the same as delivering aligned frames; that is `b601.cameras.sync`.
  - It does not know whether the mounts are physically where they claim. A
    manifest calling the fixed camera `wrist` parses cleanly and points grasp
    verification at a sensor 0.8 m from the fingers.
"""
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CAMERAS = Path(__file__).resolve().parents[1] / "setup" / "cameras.json"

# Mount is not decorative. Sim finding 4 measured a policy reporting a lift it
# had not made, and recorded that a fixed camera at 0.8 m cannot resolve
# whether an object is between the fingers. Which camera is which decides
# whether Day-16 verification has a usable input at all.
MOUNTS = ("wrist", "fixed")

_REQUIRED = ("name", "serial", "model", "mount", "device", "format",
             "width", "height", "fps", "exposure")
_DIMENSIONS = ("width", "height", "fps")

# JSON carries no comments and `probe.camera_serials` fixed this file's shape on
# Day 0, so provenance needs a home. `limits.yaml` marks its provisional values
# in comments; without somewhere to say the same thing here, a measured value
# and a placeholder become indistinguishable.
_TOP_LEVEL = ("cameras", "_note")


class CameraManifestError(Exception):
    """The camera manifest could not be loaded. Never swallow this."""


@dataclass(frozen=True)
class Camera:
    """One capture stream, as recorded. `name` becomes the dataset
    observation key `observation.images.<name>`."""
    name: str
    serial: str
    model: str
    mount: str
    device: str
    format: str
    width: int
    height: int
    fps: int
    exposure: float


def _text(entry, key, where):
    value = entry[key]
    if not isinstance(value, str) or not value.strip():
        raise CameraManifestError(
            f"{where}: {key} must be a non-empty string, got {value!r}")
    return value


def _dimension(entry, key, where):
    value = entry[key]
    # bool is an int subclass, and `True` as a width is a bug, not a 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise CameraManifestError(
            f"{where}: {key} must be a whole number, got {value!r} — a "
            f"fractional resolution or frame rate is not reproducible")
    if value <= 0:
        raise CameraManifestError(
            f"{where}: {key} must be positive, got {value}")
    return value


def _entry(raw, index, where):
    if not isinstance(raw, dict):
        raise CameraManifestError(
            f"{where}: cameras[{index}] must be a mapping, got "
            f"{type(raw).__name__}")
    for key in _REQUIRED:
        if key not in raw:
            raise CameraManifestError(
                f"{where}: cameras[{index}] missing '{key}'")
    for key in raw:
        if key not in _REQUIRED:
            raise CameraManifestError(
                f"{where}: cameras[{index}] has unknown key '{key}' — a "
                f"mistyped field is not applied, and would be silently absent "
                f"from the record; expected {list(_REQUIRED)}")

    name = _text(raw, "name", where)
    # The name is interpolated into `observation.images.<name>`. A dot nests
    # the key somewhere unintended, a space is not addressable, and a leading
    # digit is not a valid identifier to the tooling that consumes it.
    if not name.isidentifier():
        raise CameraManifestError(
            f"{where}: cameras[{index}] name {name!r} is not usable as a "
            f"dataset key; it is interpolated into observation.images.<name>")

    mount = _text(raw, "mount", where)
    if mount not in MOUNTS:
        raise CameraManifestError(
            f"{where}: cameras[{index}] mount {mount!r} is not one of "
            f"{list(MOUNTS)}")

    exposure = raw["exposure"]
    # calibration_report.md requires FIXED exposure. Auto-exposure makes
    # ambient light a hidden variable that drifts within a session and across
    # sessions, and afterwards it is indistinguishable from policy error — the
    # same shape of defect as the sim track's stale reference coordinate.
    if isinstance(exposure, bool) or not isinstance(exposure, (int, float)):
        raise CameraManifestError(
            f"{where}: cameras[{index}] exposure must be a fixed number, got "
            f"{exposure!r}; automatic exposure is not recordable state")
    if exposure <= 0:
        raise CameraManifestError(
            f"{where}: cameras[{index}] exposure must be positive, got "
            f"{exposure}")

    return Camera(
        name=name,
        serial=_text(raw, "serial", where),
        model=_text(raw, "model", where),
        mount=mount,
        device=_text(raw, "device", where),
        # Measured on this machine: the top camera offers 640x480 at 30 fps in
        # MJPG (lossy) and at 25 fps in YUYV (uncompressed). Same camera, same
        # resolution, permanently different image quality in the dataset.
        format=_text(raw, "format", where),
        **{key: _dimension(raw, key, where) for key in _DIMENSIONS},
        exposure=float(exposure),
    )


def load_cameras(path=None):
    """-> tuple of Camera from `path`, default b601/setup/cameras.json.

    Raises CameraManifestError on anything it cannot fully validate.
    """
    path = Path(path) if path is not None else DEFAULT_CAMERAS
    if not path.is_file():
        raise CameraManifestError(f"camera manifest not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except ValueError as exc:
        raise CameraManifestError(f"{path}: not valid JSON: {exc}") from exc

    if not isinstance(raw, dict) or "cameras" not in raw:
        raise CameraManifestError(f"{path}: missing 'cameras' key")
    for key in raw:
        if key not in _TOP_LEVEL:
            raise CameraManifestError(
                f"{path}: unknown top-level key '{key}'; expected "
                f"{list(_TOP_LEVEL)} — 'cameras' misspelt must not read as an "
                f"empty manifest")
    entries = raw["cameras"]
    if not isinstance(entries, list):
        raise CameraManifestError(
            f"{path}: 'cameras' must be a list, got {type(entries).__name__}")
    if not entries:
        # An empty manifest pins an empty serial set, which compares equal to
        # itself forever while nothing at all is being recorded.
        raise CameraManifestError(f"{path}: lists no cameras")

    cameras = tuple(_entry(e, i, path) for i, e in enumerate(entries))

    for field, label in (("serial", "duplicate serial"),
                         ("name", "duplicate name")):
        values = [getattr(c, field) for c in cameras]
        for value in values:
            if values.count(value) > 1:
                raise CameraManifestError(
                    f"{path}: {label} {value!r}; "
                    + ("serials identify the physical configuration"
                       if field == "serial" else
                       "names become dataset keys, so one camera would "
                       "silently overwrite the other for every frame"))

    # Recording a 15 fps stream beside a 30 fps one bakes a permanent 33 ms
    # ambiguity into every observation, and the policy consumes the streams as
    # one synchronous observation. Frame rate is frozen at record time, so this
    # has to fail before the first episode rather than surface in an audit.
    rates = {c.fps for c in cameras}
    if len(rates) > 1:
        detail = ", ".join(f"{c.name}={c.fps}" for c in cameras)
        raise CameraManifestError(
            f"{path}: cameras disagree on frame rate ({detail}); every stream "
            f"must be recorded at one rate")
    return cameras


def by_mount(cameras, mount):
    """-> the single Camera at `mount`. Raises if absent or ambiguous.

    Consumers ask for "the wrist camera", never "index 1": reordering the file
    must not silently repoint grasp verification at a camera that cannot
    resolve the fingers. Returning None would let a verifier run against
    nothing and report a grasp it never saw.
    """
    if mount not in MOUNTS:
        raise CameraManifestError(
            f"unknown mount {mount!r}; expected one of {list(MOUNTS)}")
    found = [c for c in cameras if c.mount == mount]
    if not found:
        raise CameraManifestError(
            f"no camera is mounted {mount!r}; there is no fallback sensor")
    if len(found) > 1:
        raise CameraManifestError(
            f"{len(found)} cameras claim mount {mount!r}: "
            f"{[c.name for c in found]}")
    return found[0]


def record_fps(cameras):
    """-> the single frame rate every stream is recorded at.

    `load_cameras` has already refused a manifest where these disagree, so this
    is the one rate the dataset has.
    """
    if not cameras:
        raise CameraManifestError("no cameras")
    rates = {c.fps for c in cameras}
    if len(rates) > 1:
        raise CameraManifestError(f"cameras disagree on frame rate: {rates}")
    return next(iter(rates))
