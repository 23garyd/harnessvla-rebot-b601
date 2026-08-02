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
# Not shipped here: the URDF lives with the vendor sources. Day 2 places a
# copy or symlink at this path, or points B601_URDF at it.
DEFAULT_URDF = SETUP_DIR / "urdf" / "b601_rs.urdf"


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


def _git_head(path):
    """-> (commit, dirty) for the working tree at `path`."""
    import subprocess
    path = Path(path)
    if not path.is_dir():
        raise ProbeError(f"source directory does not exist: {path}")
    try:
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProbeError(
            f"not a git working tree, so nothing identifies its contents: "
            f"{path}: {exc}") from exc
    return commit, bool(status)


def _find_distribution(name):
    from importlib.metadata import PackageNotFoundError, distribution
    try:
        return distribution(name)
    except PackageNotFoundError as exc:
        raise ProbeError(
            f"distribution {name!r} is not installed for {sys.executable}"
        ) from exc


def distribution_origin(name="lerobot", dist=None, git_head=None, find=None):
    """Identify the CODEBASE behind an installed distribution, not its version.

    A version string cannot distinguish the Seeed lerobot fork from upstream
    HuggingFace — the vendor instructions install the fork and warn against
    upstream, and both report the same `__version__`. An editable install is
    worse: `git pull` changes behaviour with no version movement at all.

    Returns one of:
        pypi:<name>:<version>          installed from an index
        git+<url>@<commit>             installed from a VCS URL (PEP 610)
        editable+git:<commit>          `pip install -e <dir>`
        local+git:<commit>             installed from a local directory

    An uncommitted working tree RAISES. Recording "dirty" and later verifying
    "dirty" compares equal while the contents differ, which is a gate that
    passes without checking anything.
    """
    import json as _json
    dist = dist if dist is not None else (find or _find_distribution)(name)
    git_head = git_head or _git_head

    raw = dist.read_text("direct_url.json")
    if not raw:
        return f"pypi:{name}:{dist.version}"

    try:
        info = _json.loads(raw)
    except ValueError as exc:
        raise ProbeError(
            f"{name}: direct_url.json is malformed: {exc}") from exc

    url = info.get("url", "")
    vcs = info.get("vcs_info")
    if vcs:
        commit = vcs.get("commit_id")
        if not commit:
            raise ProbeError(
                f"{name}: installed from {url} with no recorded commit")
        return f"{vcs.get('vcs', 'vcs')}+{url}@{commit}"

    if not url.startswith("file://"):
        raise ProbeError(f"{name}: cannot identify origin {url!r}")
    source = url[len("file://"):]
    commit, dirty = git_head(source)
    if dirty:
        raise ProbeError(
            f"{name}: the source tree at {source} has uncommitted changes, so "
            f"no commit identifies what is installed. Commit or stash before "
            f"recording pins — a dirty tree cannot be pinned.")
    editable = bool(info.get("dir_info", {}).get("editable"))
    return f"{'editable' if editable else 'local'}+git:{commit}"


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


def urdf_sha256(path=None):
    """Content hash of the kinematic description.

    The URDF is experiment state in the same way the cameras are: every pose
    the safety layer checks is FK over it, so a re-export moves workspace
    containment, step distance and home arrival at once, silently. It lives
    with the vendor sources rather than in this repository, which is exactly
    why a hash is the only thing that notices it changing.
    """
    path = Path(path) if path else DEFAULT_URDF
    if not path.is_file():
        raise ProbeError(
            f"URDF missing: {path}. Point B601_URDF at the vendor "
            f"description (see docs/reference_material.md)")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def urdf_ee_frame(path=None):
    """The end-effector frame the driver solves for.

    Read from the driver rather than typed a second time here: a pin that can
    drift from the value in use is not a pin. A different frame is a different
    arm as far as every guard is concerned.
    """
    from b601.driver.b601 import URDF_EE_FRAME
    if not URDF_EE_FRAME:
        raise ProbeError("b601.driver.b601.URDF_EE_FRAME is empty")
    return URDF_EE_FRAME


def calibration_sha256(path=None):
    path = Path(path) if path else DEFAULT_CALIBRATION
    if not path.is_file():
        raise ProbeError(f"calibration file missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _origin_probe(name):
    if not name:
        raise ProbeError(
            "distribution-origin needs a distribution name, e.g. "
            "`probe.py distribution-origin placo`")
    return distribution_origin(name)


_PROBES = {
    "python-executable": python_executable,
    "lerobot-version": lambda a: lerobot_version(),
    "lerobot-origin": lambda a: distribution_origin("lerobot"),
    "distribution-origin": _origin_probe,
    "urdf-sha256": urdf_sha256,
    "urdf-ee-frame": urdf_ee_frame,
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
