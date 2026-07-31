"""Workspace and motion limits for the reBot B601-RS.

THE RULE: every commanded motion passes through check_command() before it
reaches the driver. Nothing bypasses this — not the planner, not a primitive,
not the frozen ACT policy. A policy that emits an out-of-bounds action is a
policy whose action gets rejected, not a policy that moves the arm there.

Everything here is pure: no hardware, no I/O, no global state. That is
deliberate — the whole safety layer must be testable with the arm unpowered,
which is when you actually want to be testing it.

Limits are DATA (b601/setup/limits.yaml), not constants baked into code, so a
limit change is a reviewable diff with an experiment-registry entry rather
than an edit buried in a function.
"""
from dataclasses import dataclass


class SafetyViolation(Exception):
    """Raised when a command would leave the safe envelope.

    Carries the reason and the offending value so the caller can log a
    diagnosable artifact rather than a bare traceback.
    """

    def __init__(self, reason, detail=None):
        super().__init__(reason if detail is None else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Workspace:
    """Axis-aligned box in robot base frame, metres. Half-open on purpose:
    a command exactly on the boundary is ACCEPTED, one beyond is rejected."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def contains(self, xyz):
        x, y, z = xyz
        return (self.x_min <= x <= self.x_max
                and self.y_min <= y <= self.y_max
                and self.z_min <= z <= self.z_max)


@dataclass(frozen=True)
class MotionLimits:
    max_joint_velocity: float      # rad/s, per joint
    max_cartesian_speed: float     # m/s, EEF
    max_step_distance: float       # m, per commanded waypoint
    max_gripper_force: float       # normalised 0-1


def check_pose(xyz, workspace):
    """Reject a target pose outside the workspace box."""
    if len(xyz) != 3:
        raise SafetyViolation("pose must be (x, y, z)", xyz)
    if any(v != v for v in xyz):                      # NaN never compares true
        raise SafetyViolation("pose contains NaN", xyz)
    if not workspace.contains(xyz):
        raise SafetyViolation("pose outside workspace", xyz)


def check_step(current_xyz, target_xyz, limits):
    """Reject a single waypoint that jumps further than max_step_distance.

    This is the guard against a policy emitting a wild action: a large jump is
    refused outright rather than clamped, because a clamped wild action is
    still a wild action pointing somewhere we did not intend.
    """
    d = sum((a - b) ** 2 for a, b in zip(current_xyz, target_xyz)) ** 0.5
    if d > limits.max_step_distance:
        raise SafetyViolation(
            "step exceeds max_step_distance",
            f"{d:.4f} m > {limits.max_step_distance:.4f} m")
    return d


def check_joint_velocity(velocities, limits):
    for i, v in enumerate(velocities):
        if v != v:
            raise SafetyViolation("joint velocity is NaN", f"joint {i}")
        if abs(v) > limits.max_joint_velocity:
            raise SafetyViolation(
                "joint velocity over limit",
                f"joint {i}: |{v:.4f}| > {limits.max_joint_velocity:.4f} rad/s")


def check_gripper(force, limits):
    if force != force:
        raise SafetyViolation("gripper force is NaN", force)
    if not 0.0 <= force <= limits.max_gripper_force:
        raise SafetyViolation(
            "gripper force out of range",
            f"{force} not in [0, {limits.max_gripper_force}]")


def check_command(current_xyz, target_xyz, workspace, limits,
                  joint_velocities=None, gripper_force=None):
    """The single chokepoint. Raises SafetyViolation, or returns the step
    distance in metres.

    Order matters: pose validity first (cheapest, catches NaN and gross
    errors), then step size, then per-joint velocity, then gripper.
    """
    check_pose(target_xyz, workspace)
    distance = check_step(current_xyz, target_xyz, limits)
    if joint_velocities is not None:
        check_joint_velocity(joint_velocities, limits)
    if gripper_force is not None:
        check_gripper(gripper_force, limits)
    return distance
