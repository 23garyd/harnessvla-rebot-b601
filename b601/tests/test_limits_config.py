"""The safety envelope is DATA — these tests make that true rather than aspirational.

`limits.py` has always said limits live in `b601/setup/limits.yaml`, but until
this loader existed nothing read the file. Day-2 measurement would have
replaced the provisional numbers in the YAML and changed nothing at all, which
is the quietest possible way for a safety envelope to be wrong.

So: the file is loaded, and it is VALIDATED. A missing key, a typo'd key or an
inverted bound aborts at load time. A safety envelope that fails to parse must
never degrade into a default one — the same rule the pin probes learned.
"""
import pytest
import yaml

from b601.safety.config import DEFAULT_LIMITS, SafetyConfigError, load_limits
from b601.safety.limits import MotionLimits, Workspace

SHIPPED = DEFAULT_LIMITS


def write(tmp_path, mapping):
    p = tmp_path / "limits.yaml"
    p.write_text(yaml.safe_dump(mapping))
    return p


def valid():
    return {
        "workspace": {"x_min": 0.15, "x_max": 0.55, "y_min": -0.30,
                      "y_max": 0.30, "z_min": 0.02, "z_max": 0.50},
        "motion": {"max_joint_velocity": 1.0, "max_cartesian_speed": 0.25,
                   "max_step_distance": 0.15, "max_gripper_force": 1.0},
    }


# --- the shipped envelope -------------------------------------------------

def test_shipped_limits_file_loads_and_is_the_source_of_truth():
    """The file the robot will actually run against must parse."""
    ws, lim = load_limits(SHIPPED)
    assert isinstance(ws, Workspace) and isinstance(lim, MotionLimits)
    raw = yaml.safe_load(SHIPPED.read_text())
    assert ws.x_min == raw["workspace"]["x_min"]
    assert lim.max_step_distance == raw["motion"]["max_step_distance"]


def test_default_path_is_anchored_at_the_repo_not_the_cwd(tmp_path, monkeypatch):
    """Anchored at b601/setup/, like the pin probes — a caller standing in
    another directory must not silently load a different envelope, or none."""
    monkeypatch.chdir(tmp_path)
    assert load_limits() == load_limits(SHIPPED)


# --- structural validation ------------------------------------------------

def test_missing_file_raises_rather_than_defaulting():
    with pytest.raises(SafetyConfigError, match="not found"):
        load_limits("b601/setup/no_such_limits.yaml")


@pytest.mark.parametrize("section,key", [
    ("workspace", "z_max"),
    ("motion", "max_gripper_force"),
])
def test_missing_key_is_rejected(tmp_path, section, key):
    cfg = valid()
    del cfg[section][key]
    with pytest.raises(SafetyConfigError, match=key):
        load_limits(write(tmp_path, cfg))


def test_unknown_key_is_rejected(tmp_path):
    """A typo'd limit is a limit that is not being applied; silently ignoring
    it is how you believe you set a cap that does not exist."""
    cfg = valid()
    cfg["motion"]["max_joint_velocty"] = 0.5
    with pytest.raises(SafetyConfigError, match="max_joint_velocty"):
        load_limits(write(tmp_path, cfg))


def test_missing_section_is_rejected(tmp_path):
    cfg = valid()
    del cfg["motion"]
    with pytest.raises(SafetyConfigError, match="motion"):
        load_limits(write(tmp_path, cfg))


def test_non_numeric_value_is_rejected(tmp_path):
    cfg = valid()
    cfg["workspace"]["x_max"] = "0.55"
    with pytest.raises(SafetyConfigError, match="x_max"):
        load_limits(write(tmp_path, cfg))


# --- sanity invariants ----------------------------------------------------

@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_inverted_bounds_are_rejected(tmp_path, axis):
    cfg = valid()
    cfg["workspace"][f"{axis}_min"], cfg["workspace"][f"{axis}_max"] = (
        cfg["workspace"][f"{axis}_max"], cfg["workspace"][f"{axis}_min"])
    with pytest.raises(SafetyConfigError, match=f"{axis}_min"):
        load_limits(write(tmp_path, cfg))


def test_workspace_floor_below_the_table_is_rejected(tmp_path):
    """z_min < 0 is the table surface or below it."""
    cfg = valid()
    cfg["workspace"]["z_min"] = -0.05
    with pytest.raises(SafetyConfigError, match="z_min"):
        load_limits(write(tmp_path, cfg))


@pytest.mark.parametrize("key", ["max_joint_velocity", "max_cartesian_speed",
                                 "max_step_distance", "max_gripper_force"])
def test_non_positive_motion_limit_is_rejected(tmp_path, key):
    cfg = valid()
    cfg["motion"][key] = 0.0
    with pytest.raises(SafetyConfigError, match=key):
        load_limits(write(tmp_path, cfg))


def test_gripper_force_above_normalised_range_is_rejected(tmp_path):
    cfg = valid()
    cfg["motion"]["max_gripper_force"] = 1.5
    with pytest.raises(SafetyConfigError, match="max_gripper_force"):
        load_limits(write(tmp_path, cfg))


def test_nan_limit_is_rejected(tmp_path):
    """NaN passes every naive comparison, exactly as in check_pose."""
    p = tmp_path / "limits.yaml"
    p.write_text(yaml.safe_dump(valid()).replace("0.15", ".nan"))
    with pytest.raises(SafetyConfigError, match="NaN"):
        load_limits(p)
