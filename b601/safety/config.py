"""Load the safety envelope from b601/setup/limits.yaml.

`limits.py` stays pure — no I/O, no paths, no file formats — so this is where
the data becomes objects. Keeping the split means the guard logic can be
reasoned about and tested without a filesystem, while the numbers it enforces
remain a reviewable diff rather than constants buried in code.

THE RULE: everything that constructs a SafeDriver gets its Workspace and
MotionLimits from here. Hand-constructing limits in production code puts the
robot under an envelope that no one reviewed and that limits.yaml does not
describe. (Tests may construct synthetic limits — they are exercising the
guard logic, not the envelope.)

A malformed file is an ERROR, never a fallback to defaults. The pin probes
learned this the expensive way: a check that degrades quietly is trusted while
checking nothing. An envelope that fails to load must stop the run.

Validation covers the failures that are silent at runtime:
  - unknown key        a typo'd limit is a limit that is not being applied
  - missing key        a cap you believe exists but does not
  - inverted bounds    an empty workspace accepts nothing, or worse, is read
                       as permissive by later code
  - z_min below 0      the table surface; nothing legal lives underneath it
  - non-positive cap   a zero speed limit is not "no motion", it is a bug
  - NaN                passes every naive comparison, as check_pose documents
"""
import math
from pathlib import Path

import yaml

from b601.safety.limits import HomeContract, MotionLimits, Workspace

DEFAULT_LIMITS = Path(__file__).resolve().parents[1] / "setup" / "limits.yaml"

_WORKSPACE_KEYS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
_MOTION_KEYS = ("max_joint_velocity", "max_cartesian_speed",
                "max_step_distance", "max_gripper_force")
_HOME_KEYS = ("xyz", "tolerance_m")


class SafetyConfigError(Exception):
    """The safety envelope could not be loaded. Never swallow this."""


def _section(raw, name, keys, where):
    if not isinstance(raw, dict) or name not in raw:
        raise SafetyConfigError(f"{where}: missing '{name}' section")
    section = raw[name]
    if not isinstance(section, dict):
        raise SafetyConfigError(
            f"{where}: '{name}' must be a mapping, got "
            f"{type(section).__name__}")
    for key in keys:
        if key not in section:
            raise SafetyConfigError(f"{where}: {name} missing '{key}'")
    for key in section:
        if key not in keys:
            raise SafetyConfigError(
                f"{where}: {name} has unknown key '{key}' — a mistyped limit "
                f"is not applied; expected {list(keys)}")
    values = {}
    for key in keys:
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SafetyConfigError(
                f"{where}: {name}.{key} must be a number, got {value!r}")
        if math.isnan(value):
            raise SafetyConfigError(f"{where}: {name}.{key} is NaN")
        if math.isinf(value):
            raise SafetyConfigError(f"{where}: {name}.{key} is infinite")
        values[key] = float(value)
    return values


def _check_workspace(ws, where):
    for axis in ("x", "y", "z"):
        lo, hi = ws[f"{axis}_min"], ws[f"{axis}_max"]
        if lo >= hi:
            raise SafetyConfigError(
                f"{where}: workspace {axis}_min ({lo}) must be below "
                f"{axis}_max ({hi})")
    if ws["z_min"] < 0.0:
        raise SafetyConfigError(
            f"{where}: workspace z_min ({ws['z_min']}) is at or below the "
            f"table surface; the floor must clear it")


def _check_motion(motion, where):
    for key, value in motion.items():
        if value <= 0.0:
            raise SafetyConfigError(
                f"{where}: motion.{key} must be positive, got {value}")
    if motion["max_gripper_force"] > 1.0:
        raise SafetyConfigError(
            f"{where}: motion.max_gripper_force is normalised to [0, 1], got "
            f"{motion['max_gripper_force']}")


def load_limits(path=None):
    """-> (Workspace, MotionLimits) from `path`, default b601/setup/limits.yaml.

    Raises SafetyConfigError on anything it cannot fully validate.
    """
    path = Path(path) if path is not None else DEFAULT_LIMITS
    if not path.is_file():
        raise SafetyConfigError(f"safety limits not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise SafetyConfigError(f"{path}: not valid YAML: {exc}") from exc

    workspace = _section(raw, "workspace", _WORKSPACE_KEYS, path)
    motion = _section(raw, "motion", _MOTION_KEYS, path)
    _check_workspace(workspace, path)
    _check_motion(motion, path)
    return Workspace(**workspace), MotionLimits(**motion)


def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafetyConfigError(f"{where} must be a number, got {value!r}")
    if math.isnan(value):
        raise SafetyConfigError(f"{where} is NaN")
    if math.isinf(value):
        raise SafetyConfigError(f"{where} is infinite")
    return float(value)


def load_home(path=None):
    """-> HomeContract from `path`, default b601/setup/limits.yaml.

    Separate from load_limits() on purpose: a Cartesian-only consumer must not
    start failing because homing is misconfigured, and safe_home refuses to
    run at all without this, so the two failure modes stay distinguishable.
    """
    path = Path(path) if path is not None else DEFAULT_LIMITS
    if not path.is_file():
        raise SafetyConfigError(f"safety limits not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise SafetyConfigError(f"{path}: not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "home" not in raw:
        raise SafetyConfigError(f"{path}: missing 'home' section")
    section = raw["home"]
    if not isinstance(section, dict):
        raise SafetyConfigError(
            f"{path}: 'home' must be a mapping, got {type(section).__name__}")
    for key in _HOME_KEYS:
        if key not in section:
            raise SafetyConfigError(f"{path}: home missing '{key}'")
    for key in section:
        if key not in _HOME_KEYS:
            raise SafetyConfigError(
                f"{path}: home has unknown key '{key}'; expected "
                f"{list(_HOME_KEYS)}")

    xyz = section["xyz"]
    if isinstance(xyz, (str, bytes)) or not isinstance(xyz, (list, tuple)):
        raise SafetyConfigError(
            f"{path}: home.xyz must be a list of three numbers, got {xyz!r}")
    if len(xyz) != 3:
        raise SafetyConfigError(
            f"{path}: home.xyz must have three axes, got {len(xyz)}")
    xyz = tuple(_number(v, f"{path}: home.xyz[{i}]") for i, v in enumerate(xyz))

    tolerance = _number(section["tolerance_m"], f"{path}: home.tolerance_m")
    if tolerance <= 0.0:
        raise SafetyConfigError(
            f"{path}: home.tolerance_m must be positive, got {tolerance}")

    # A home the arm may not legally occupy makes every other guard
    # unreachable — the first move away from it is already a violation.
    workspace, _ = load_limits(path)
    if not workspace.contains(xyz):
        raise SafetyConfigError(
            f"{path}: home.xyz {xyz} is outside the workspace")
    # An arrival radius that spans the box accepts any terminal pose at all.
    span = min(workspace.x_max - workspace.x_min,
               workspace.y_max - workspace.y_min,
               workspace.z_max - workspace.z_min)
    if tolerance >= span / 2:
        raise SafetyConfigError(
            f"{path}: home.tolerance_m {tolerance} is not meaningfully "
            f"tighter than the workspace (smallest half-span {span / 2})")
    return HomeContract(xyz=xyz, tolerance_m=tolerance)


def main(argv=None):
    """`python -m b601.safety.config [path]` — validate an envelope before use.

    Day 2 replaces every provisional number in limits.yaml with a measured
    one. Run this on the edited file before the first powered motion.
    """
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        ws, lim = load_limits(argv[0] if argv else None)
        home = load_home(argv[0] if argv else None)
    except SafetyConfigError as exc:
        print(f"SAFETY CONFIG INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"workspace x[{ws.x_min}, {ws.x_max}] y[{ws.y_min}, {ws.y_max}] "
          f"z[{ws.z_min}, {ws.z_max}] m")
    print(f"motion    joint<={lim.max_joint_velocity} rad/s, "
          f"eef<={lim.max_cartesian_speed} m/s, "
          f"step<={lim.max_step_distance} m, "
          f"grip<={lim.max_gripper_force}")
    print(f"home      {home.xyz} +/- {home.tolerance_m} m")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
