"""The approved home configuration is data, like the rest of the envelope.

It is loaded separately from load_limits() because it answers a different
question — not "what is the arm allowed to do" but "where does homing have to
end up" — and because safe_home refuses to run without it, while the Cartesian
guards never need it.

Its tolerance is the one number here that Day 2 must set FROM a measurement
rather than before one: an arrival radius tighter than the arm's repeatability
would fault on every successful home, and one much looser would accept a home
that missed.
"""
import pytest
import yaml

from b601.safety.config import (DEFAULT_LIMITS, SafetyConfigError, load_home,
                                load_limits)
from b601.safety.limits import HomeContract


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
        "home": {"xyz": [0.30, 0.00, 0.35], "tolerance_m": 0.02},
    }


def test_shipped_home_loads():
    home = load_home()
    assert isinstance(home, HomeContract)
    raw = yaml.safe_load(DEFAULT_LIMITS.read_text())
    assert list(home.xyz) == raw["home"]["xyz"]
    assert home.tolerance_m == raw["home"]["tolerance_m"]


def test_home_is_anchored_at_the_repo_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_home() == load_home(DEFAULT_LIMITS)


def test_missing_home_section_is_rejected(tmp_path):
    cfg = valid()
    del cfg["home"]
    with pytest.raises(SafetyConfigError, match="home"):
        load_home(write(tmp_path, cfg))


@pytest.mark.parametrize("key", ["xyz", "tolerance_m"])
def test_missing_home_key_is_rejected(tmp_path, key):
    cfg = valid()
    del cfg["home"][key]
    with pytest.raises(SafetyConfigError, match=key):
        load_home(write(tmp_path, cfg))


def test_unknown_home_key_is_rejected(tmp_path):
    cfg = valid()
    cfg["home"]["tolerence_m"] = 0.05
    with pytest.raises(SafetyConfigError, match="tolerence_m"):
        load_home(write(tmp_path, cfg))


@pytest.mark.parametrize("xyz", [[0.30, 0.0], [0.30, 0.0, 0.35, 0.1]])
def test_home_pose_must_have_three_axes(tmp_path, xyz):
    cfg = valid()
    cfg["home"]["xyz"] = xyz
    with pytest.raises(SafetyConfigError, match="xyz"):
        load_home(write(tmp_path, cfg))


def test_home_outside_the_workspace_is_rejected(tmp_path):
    """A home the arm may not legally occupy makes every other guard
    unreachable: the first move out of it would already be a violation."""
    cfg = valid()
    cfg["home"]["xyz"] = [0.95, 0.0, 0.35]
    with pytest.raises(SafetyConfigError, match="outside the workspace"):
        load_home(write(tmp_path, cfg))


@pytest.mark.parametrize("tolerance", [0.0, -0.01])
def test_non_positive_tolerance_is_rejected(tmp_path, tolerance):
    cfg = valid()
    cfg["home"]["tolerance_m"] = tolerance
    with pytest.raises(SafetyConfigError, match="tolerance_m"):
        load_home(write(tmp_path, cfg))


def test_tolerance_larger_than_the_workspace_is_rejected(tmp_path):
    """A tolerance that spans the box accepts any terminal pose at all."""
    cfg = valid()
    cfg["home"]["tolerance_m"] = 5.0
    with pytest.raises(SafetyConfigError, match="tolerance_m"):
        load_home(write(tmp_path, cfg))


def test_nan_tolerance_is_rejected(tmp_path):
    cfg = valid()
    cfg["home"]["tolerance_m"] = float("nan")
    with pytest.raises(SafetyConfigError, match="tolerance_m"):
        load_home(write(tmp_path, cfg))


def test_load_limits_is_unaffected_by_the_home_section(tmp_path):
    """The two loaders stay independent: a Cartesian-only consumer must not
    start failing because homing is misconfigured."""
    cfg = valid()
    cfg["home"]["tolerance_m"] = -1.0
    ws, lim = load_limits(write(tmp_path, cfg))
    assert ws.x_min == 0.15 and lim.max_step_distance == 0.15
