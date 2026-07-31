"""Workspace and motion limits for the reBot B601-RS.

THE RULE: every commanded Cartesian waypoint passes through check_command()
before it reaches the driver. Bounded joint-space homing has its own
precondition, velocity, timeout, and postcondition checks. Nothing bypasses
the appropriate boundary — not the planner, not a primitive, not the frozen
ACT policy. A policy that emits an out-of-bounds action is a policy whose
action gets rejected, not a policy that moves the arm there.

Everything here is pure: no hardware, no I/O, no global state. That is
deliberate — the whole safety layer must be testable with the arm unpowered,
which is when you actually want to be testing it.

Limits are DATA (b601/setup/limits.yaml), not constants baked into code, so a
limit change is a reviewable diff with an experiment-registry entry rather
than an edit buried in a function. `b601.safety.config.load_limits()` is what
reads that file and the only sanctioned way to build the envelope in
production code — this module stays pure so the guards can be tested without
a filesystem, but "the limits live in YAML" is only true because something
loads it.
"""
import math
import numbers
from collections.abc import Mapping, Sequence
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


def check_cartesian_speed(speed, limits):
    if (isinstance(speed, bool)
            or not isinstance(speed, numbers.Real)
            or not math.isfinite(speed)
            or speed <= 0.0
            or speed > limits.max_cartesian_speed):
        raise SafetyViolation(
            "cartesian speed out of range",
            f"{speed!r} not finite and in (0, {limits.max_cartesian_speed}]")
    return float(speed)


def check_timeout(timeout_s, operation):
    if (isinstance(timeout_s, bool)
            or not isinstance(timeout_s, numbers.Real)
            or not math.isfinite(timeout_s)
            or timeout_s <= 0.0):
        raise SafetyViolation(
            f"{operation} timeout out of range",
            f"{timeout_s!r} must be finite and positive")
    return float(timeout_s)


def check_pose(xyz, workspace):
    """Reject a target pose outside the workspace box."""
    try:
        xyz = tuple(xyz)
    except Exception as exc:
        raise SafetyViolation("pose must be (x, y, z)", xyz) from exc
    if len(xyz) != 3:
        raise SafetyViolation("pose must be (x, y, z)", xyz)
    if any(isinstance(v, bool) or not isinstance(v, numbers.Real)
           for v in xyz):
        raise SafetyViolation("pose must contain finite numbers", xyz)
    if any(math.isnan(v) for v in xyz):
        raise SafetyViolation("pose contains NaN", xyz)
    if any(not math.isfinite(v) for v in xyz):
        raise SafetyViolation("pose must contain finite numbers", xyz)
    if not workspace.contains(xyz):
        raise SafetyViolation("pose outside workspace", xyz)
    return xyz


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
    try:
        velocities = tuple(velocities)
    except Exception as exc:
        raise SafetyViolation(
            "joint velocity state must be a numeric sequence",
            velocities) from exc
    for i, v in enumerate(velocities):
        if isinstance(v, bool) or not isinstance(v, numbers.Real):
            raise SafetyViolation(
                "joint velocity must be finite",
                f"joint {i}: {v!r}")
        if math.isnan(v):
            raise SafetyViolation("joint velocity is NaN", f"joint {i}")
        if not math.isfinite(v):
            raise SafetyViolation(
                "joint velocity must be finite",
                f"joint {i}: {v!r}")
        if abs(v) > limits.max_joint_velocity:
            raise SafetyViolation(
                "joint velocity over limit",
                f"joint {i}: |{v:.4f}| > {limits.max_joint_velocity:.4f} rad/s")
    return velocities


def check_joint_state(state, limits):
    if (not isinstance(state, Mapping)
            or "positions" not in state
            or "velocities" not in state):
        raise SafetyViolation(
            "joint state must provide positions and velocities", state)
    positions = state["positions"]
    velocities = state["velocities"]
    if (isinstance(positions, (str, bytes))
            or not isinstance(positions, Sequence)
            or isinstance(velocities, (str, bytes))
            or not isinstance(velocities, Sequence)):
        raise SafetyViolation(
            "joint state positions and velocities must be sequences", state)
    if not positions or not velocities:
        raise SafetyViolation("joint state must not be empty", state)
    if len(positions) != len(velocities):
        raise SafetyViolation(
            "joint state positions and velocities must have equal length",
            f"{len(positions)} positions, {len(velocities)} velocities")
    return check_joint_velocity(velocities, limits)


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
    current_xyz = check_pose(current_xyz, workspace)
    target_xyz = check_pose(target_xyz, workspace)
    distance = check_step(current_xyz, target_xyz, limits)
    if joint_velocities is not None:
        check_joint_velocity(joint_velocities, limits)
    if gripper_force is not None:
        check_gripper(gripper_force, limits)
    return distance
