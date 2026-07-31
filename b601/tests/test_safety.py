"""Safety-layer tests. All run with the arm unpowered — that is the point.

These are the highest-consequence tests in the repo: a false PASS here is how
hardware gets damaged. Prefer over-specifying behaviour to leaving it implied.
"""
import pytest

from b601.driver.base import SafeDriver
from b601.driver.mock import MockDriver
from b601.safety.limits import (MotionLimits, SafetyViolation, Workspace,
                                check_cartesian_speed, check_command,
                                check_gripper,
                                check_joint_velocity, check_pose, check_step,
                                check_timeout)

# SYNTHETIC fixture, deliberately not loaded from b601/setup/limits.yaml.
# These tests exercise the guard LOGIC, so they must not change meaning when
# Day-2 measurement replaces the shipped envelope — a test whose in-bounds
# pose silently becomes out-of-bounds is a test that stopped asserting what it
# says. The shipped file is loaded and validated in test_limits_config.py.
WS = Workspace(x_min=0.15, x_max=0.55, y_min=-0.30, y_max=0.30,
               z_min=0.02, z_max=0.50)
LIM = MotionLimits(max_joint_velocity=1.0, max_cartesian_speed=0.25,
                   max_step_distance=0.15, max_gripper_force=1.0)


def safe(**kw):
    d = MockDriver(**kw)
    return d, SafeDriver(d, WS, LIM)


class UnsafeHomeVelocityMock(MockDriver):
    def safe_home(self, max_joint_velocity, timeout_s):
        super().safe_home(max_joint_velocity, timeout_s)
        self.set_velocities([9.0, 0, 0, 0, 0, 0])


# --- pure limit checks ----------------------------------------------------

def test_pose_inside_workspace_is_accepted():
    check_pose((0.30, 0.0, 0.20), WS)


@pytest.mark.parametrize("xyz", [
    (0.10, 0.0, 0.20),    # x below
    (0.60, 0.0, 0.20),    # x above
    (0.30, -0.40, 0.20),  # y below
    (0.30, 0.40, 0.20),   # y above
    (0.30, 0.0, 0.00),    # z below table
    (0.30, 0.0, 0.60),    # z above
])
def test_pose_outside_workspace_is_rejected(xyz):
    with pytest.raises(SafetyViolation, match="outside workspace"):
        check_pose(xyz, WS)


def test_boundary_pose_is_accepted_not_rejected():
    """Half-open by design: exactly on the limit is legal, beyond is not."""
    check_pose((WS.x_min, WS.y_min, WS.z_min), WS)
    check_pose((WS.x_max, WS.y_max, WS.z_max), WS)


def test_nan_pose_is_rejected():
    """NaN never compares true, so a naive bounds check silently ACCEPTS it."""
    with pytest.raises(SafetyViolation, match="NaN"):
        check_pose((float("nan"), 0.0, 0.2), WS)


def test_step_within_limit_returns_distance():
    d = check_step((0.30, 0.0, 0.20), (0.35, 0.0, 0.20), LIM)
    assert d == pytest.approx(0.05)


def test_large_step_is_rejected_not_clamped():
    """A wild action is refused. Clamping it would still aim somewhere we
    never intended, which is the more dangerous failure."""
    with pytest.raises(SafetyViolation, match="max_step_distance"):
        check_step((0.30, 0.0, 0.20), (0.50, 0.0, 0.20), LIM)


def test_joint_velocity_over_limit_is_rejected():
    with pytest.raises(SafetyViolation, match="joint velocity over limit"):
        check_joint_velocity([0.1, 0.2, 5.0, 0.0, 0.0, 0.0], LIM)


def test_nan_joint_velocity_is_rejected():
    with pytest.raises(SafetyViolation, match="NaN"):
        check_joint_velocity([0.1, float("nan")], LIM)


@pytest.mark.parametrize("force", [-0.1, 1.5, float("nan")])
def test_bad_gripper_force_is_rejected(force):
    with pytest.raises(SafetyViolation):
        check_gripper(force, LIM)


@pytest.mark.parametrize("speed", [
    -0.01, 0.0, float("nan"), float("inf"), True, "fast",
])
def test_invalid_cartesian_speed_is_rejected(speed):
    with pytest.raises(SafetyViolation, match="cartesian speed"):
        check_cartesian_speed(speed, LIM)


@pytest.mark.parametrize("timeout", [
    -1.0, 0.0, float("nan"), float("inf"), True, "soon",
])
def test_invalid_home_timeout_is_rejected(timeout):
    with pytest.raises(SafetyViolation, match="safe_home timeout"):
        check_timeout(timeout, "safe_home")


def test_valid_home_timeout_is_normalized_to_float():
    timeout = check_timeout(12, "safe_home")
    assert timeout == 12.0
    assert isinstance(timeout, float)


def test_check_command_runs_every_guard():
    with pytest.raises(SafetyViolation, match="outside workspace"):
        check_command((0.30, 0.0, 0.20), (0.90, 0.0, 0.20), WS, LIM)
    with pytest.raises(SafetyViolation, match="max_step_distance"):
        check_command((0.30, 0.0, 0.20), (0.50, 0.0, 0.20), WS, LIM)
    with pytest.raises(SafetyViolation, match="joint velocity"):
        check_command((0.30, 0.0, 0.20), (0.33, 0.0, 0.20), WS, LIM,
                      joint_velocities=[9.0])


# --- SafeDriver enforcement ----------------------------------------------

def test_safe_move_reaches_the_driver():
    mock, sd = safe()
    sd.move_to((0.35, 0.0, 0.35))
    assert mock.last("move_to")[1] == (0.35, 0.0, 0.35)
    assert sd.motions == 1


def test_unsafe_move_never_reaches_the_driver():
    """The whole point of the chokepoint."""
    mock, sd = safe()
    with pytest.raises(SafetyViolation):
        sd.move_to((0.95, 0.0, 0.35))
    assert mock.last("move_to") is None, "unsafe command was forwarded!"


def test_violation_latches_a_fault_and_blocks_later_moves():
    """A source that emitted one bad command is not trusted for the next."""
    mock, sd = safe()
    with pytest.raises(SafetyViolation):
        sd.move_to((0.95, 0.0, 0.35))
    assert sd.faulted is not None
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.move_to((0.32, 0.0, 0.35))      # a perfectly legal move
    assert mock.last("move_to") is None


def test_fault_must_be_cleared_explicitly():
    _, sd = safe()
    with pytest.raises(SafetyViolation):
        sd.move_to((0.95, 0.0, 0.35))
    assert sd.clear_fault() is not None
    assert sd.faulted is None
    sd.move_to((0.32, 0.0, 0.35))          # now allowed


def test_disable_works_even_when_faulted():
    """Disabling must never be blocked by the fault that makes you want it."""
    mock, sd = safe()
    with pytest.raises(SafetyViolation):
        sd.move_to((0.95, 0.0, 0.35))
    sd.disable()
    assert mock.enabled is False


def test_speed_over_cartesian_limit_is_rejected():
    mock, sd = safe()
    with pytest.raises(SafetyViolation, match="cartesian speed"):
        sd.move_to((0.32, 0.0, 0.35), speed=10.0)
    assert mock.last("move_to") is None


def test_speed_defaults_to_the_configured_maximum():
    mock, sd = safe()
    sd.move_to((0.32, 0.0, 0.35))
    assert mock.last("move_to")[2] == LIM.max_cartesian_speed


@pytest.mark.parametrize("speed", [
    -0.01, 0.0, float("nan"), float("inf"), True, "fast",
])
def test_invalid_speed_never_reaches_driver(speed):
    mock, sd = safe()
    with pytest.raises(SafetyViolation, match="cartesian speed"):
        sd.move_to((0.32, 0.0, 0.35), speed=speed)
    assert mock.last("move_to") is None
    assert sd.faulted is not None


def test_valid_cartesian_speed_is_normalized_and_forwarded():
    mock, sd = safe()
    sd.move_to((0.32, 0.0, 0.35), speed=0.10)
    assert mock.last("move_to")[2] == pytest.approx(0.10)


def test_high_joint_velocity_blocks_the_move():
    mock, sd = safe()
    mock.set_velocities([9.0, 0, 0, 0, 0, 0])
    with pytest.raises(SafetyViolation, match="joint velocity"):
        sd.move_to((0.32, 0.0, 0.35))
    assert mock.last("move_to") is None


def test_bad_gripper_force_never_reaches_the_driver():
    mock, sd = safe()
    with pytest.raises(SafetyViolation):
        sd.set_gripper(5.0)
    assert mock.last("set_gripper") is None


def test_hardware_move_fault_latches_and_blocks_next_motion():
    mock, sd = safe()
    mock.fault_on_next_move = "joint 3 overcurrent"
    with pytest.raises(RuntimeError, match="overcurrent"):
        sd.move_to((0.32, 0.0, 0.35))
    assert "move_to failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.move_to((0.33, 0.0, 0.35))
    assert len([c for c in mock.commands if c[0] == "move_to"]) == 1


def test_hardware_gripper_fault_latches_and_blocks_next_actuation():
    mock, sd = safe()
    mock.fault_on_next_gripper = "gripper bus fault"
    with pytest.raises(RuntimeError, match="bus fault"):
        sd.set_gripper(0.5)
    assert "set_gripper failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.set_gripper(0.4)


@pytest.mark.parametrize("timeout", [
    -1.0, 0.0, float("nan"), float("inf"), True, "soon",
])
def test_invalid_home_timeout_never_reaches_driver(timeout):
    mock, sd = safe()
    with pytest.raises(SafetyViolation, match="safe_home timeout"):
        sd.safe_home(timeout_s=timeout)
    assert mock.last("safe_home") is None
    assert sd.faulted is not None


def test_safe_home_forwards_velocity_and_normalized_timeout_bounds():
    mock, sd = safe(start=(WS.x_max, 0.0, 0.35))
    sd.safe_home(timeout_s=12)
    assert mock.last("safe_home") == (
        "safe_home", LIM.max_joint_velocity, 12.0)
    assert isinstance(mock.last("safe_home")[2], float)


def test_safe_home_uses_default_timeout_bound():
    mock, sd = safe()
    sd.safe_home()
    assert mock.last("safe_home") == (
        "safe_home", LIM.max_joint_velocity, 30.0)


def test_safe_home_fault_latches_and_blocks_later_motion():
    mock, sd = safe()
    mock.fault_on_next_home = "home switch fault"
    with pytest.raises(RuntimeError, match="switch fault"):
        sd.safe_home(timeout_s=12.0)
    assert "safe_home failed" in sd.faulted
    with pytest.raises(SafetyViolation, match="faulted"):
        sd.move_to((0.32, 0.0, 0.35))
    assert mock.last("safe_home") == (
        "safe_home", LIM.max_joint_velocity, 12.0, "FAULT")


def test_safe_home_rejects_invalid_pose_precondition_without_raw_motion():
    mock, sd = safe(start=(float("nan"), 0.0, 0.35))
    with pytest.raises(SafetyViolation, match="NaN"):
        sd.safe_home(timeout_s=12.0)
    assert mock.last("safe_home") is None
    assert sd.faulted is not None


def test_safe_home_rejects_invalid_velocity_precondition_without_raw_motion():
    mock, sd = safe()
    mock.set_velocities([9.0, 0, 0, 0, 0, 0])
    with pytest.raises(SafetyViolation, match="joint velocity"):
        sd.safe_home(timeout_s=12.0)
    assert mock.last("safe_home") is None
    assert sd.faulted is not None


def test_safe_home_rejects_invalid_pose_postcondition():
    mock, sd = safe()
    mock.home_result = (float("nan"), 0.0, 0.35)
    with pytest.raises(SafetyViolation, match="NaN"):
        sd.safe_home(timeout_s=12.0)
    assert sd.faulted is not None
    assert sd.motions == 0


def test_safe_home_rejects_invalid_velocity_postcondition():
    mock = UnsafeHomeVelocityMock()
    sd = SafeDriver(mock, WS, LIM)
    with pytest.raises(SafetyViolation, match="joint velocity"):
        sd.safe_home(timeout_s=12.0)
    assert sd.faulted is not None
    assert sd.motions == 0


def test_safe_home_counts_successful_motion():
    _, sd = safe()
    sd.safe_home(timeout_s=12.0)
    assert sd.motions == 1


def test_mock_models_empty_grasp_for_the_day16_verifier():
    """Day-16 needs induced empty grasps; this is how they get induced with
    no hardware and no risk."""
    mock, sd = safe(grasp_succeeds=False)
    sd.set_gripper(0.8)
    assert mock.holding is False
    mock2, sd2 = safe(grasp_succeeds=True)
    sd2.set_gripper(0.8)
    assert mock2.holding is True
