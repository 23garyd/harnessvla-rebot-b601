"""Pin probes: read the values that pin_check.sh gates on.

These live in Python rather than in shell heredocs so they can be unit-tested,
and so a path is resolved against a known anchor instead of whatever directory
the operator happened to be standing in.

DESIGN RULE, learned the hard way: a probe that cannot determine its value
RAISES. It never returns a placeholder. The earlier version fell back to
`|| echo UNKNOWN`, which meant a broken probe recorded UNKNOWN at --record
time and computed UNKNOWN at verify time — the gate passed while checking
nothing at all. A pin gate that silently degrades to a no-op is worse than no
gate, because it is trusted.
"""
import hashlib
import json
import sys
from pathlib import Path

SETUP_DIR = Path(__file__).resolve().parent
REPO = SETUP_DIR.parents[1]
DEFAULT_CAMERAS = SETUP_DIR / "cameras.json"
DEFAULT_CALIBRATION = SETUP_DIR / "calibration.json"


class ProbeError(RuntimeError):
    """A pin value could not be determined. Never swallow this."""


def lerobot_version():
    """Version of lerobot as importable by THIS interpreter.

    Which interpreter runs this is the whole point: pin_check.sh must invoke
    the repository venv, not an ambient python that may belong to a different
    environment entirely.
    """
    try:
        import lerobot
    except ImportError as exc:
        raise ProbeError(
            f"lerobot is not importable by {sys.executable}: {exc}") from exc
    version = getattr(lerobot, "__version__", None)
    if not version:
        raise ProbeError(f"lerobot at {lerobot.__file__} exposes no __version__")
    return version


def python_executable(path=None):
    """Path of the interpreter running this probe.

    The interpreter is a pin in its own right: every other value here is
    "as seen by THIS python", so recording under one environment and verifying
    under another compares two installations and calls the result agreement.
    B601_PY makes that override legitimate and easy, which is exactly why it
    has to be gated rather than merely noted.

    NOT resolved through symlinks: a venv's bin/python points at the system
    interpreter, so resolving would report the same path for two different
    environments — the opposite of what this pin is for.
    """
    if not sys.executable:
        raise ProbeError(
            "this interpreter reports no sys.executable; it cannot be pinned")
    return sys.executable


def camera_serials(path=None):
    """Sorted, comma-joined camera serials from the camera manifest.

    Anchored at b601/setup/cameras.json unless overridden — NOT resolved
    against the caller's cwd.
    """
    path = Path(path) if path else DEFAULT_CAMERAS
    if not path.is_file():
        raise ProbeError(f"camera manifest missing: {path}")
    try:
        cameras = json.loads(path.read_text())["cameras"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProbeError(f"camera manifest malformed: {path}: {exc}") from exc
    if not cameras:
        raise ProbeError(f"camera manifest lists no cameras: {path}")
    serials = []
    for i, cam in enumerate(cameras):
        serial = cam.get("serial") if isinstance(cam, dict) else None
        if not serial:
            raise ProbeError(f"camera manifest entry {i} has no serial: {path}")
        serials.append(str(serial))
    if len(set(serials)) != len(serials):
        raise ProbeError(f"camera manifest has duplicate serials: {path}")
    return ",".join(sorted(serials))


def calibration_sha256(path=None):
    path = Path(path) if path else DEFAULT_CALIBRATION
    if not path.is_file():
        raise ProbeError(f"calibration file missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


_PROBES = {
    "python-executable": python_executable,
    "lerobot-version": lambda a: lerobot_version(),
    "camera-serials": camera_serials,
    "calibration-sha256": calibration_sha256,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 1 or argv[0] not in _PROBES:
        print(f"usage: probe.py {{{'|'.join(_PROBES)}}} [path]", file=sys.stderr)
        return 64
    try:
        print(_PROBES[argv[0]](argv[1] if len(argv) > 1 else None))
    except ProbeError as exc:
        print(f"PROBE FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
