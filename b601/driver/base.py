"""Driver interface for the reBot B601-RS, and the safety-enforcing wrapper.

Two implementations sit behind `Driver`:
  - `MockDriver`   (b601/driver/mock.py) — no hardware, used by the whole test
                    suite so every test runs with the arm unpowered
  - `B601Driver`   (b601/driver/b601.py) — the vendor SDK, added on Day 2

`SafeDriver` wraps EITHER of them and is the only thing the rest of the
codebase is allowed to hold. It routes Cartesian moves through
b601.safety.limits.check_command, enforces a separate bounded joint-space
homing contract, and refuses to move after a fault until explicitly cleared.
Primitives, planner and policy all talk to SafeDriver, so every motion reaches
the appropriate safety boundary.
"""
from abc import ABC, abstractmethod

from b601.safety.limits import (SafetyViolation, check_cartesian_speed,
                                check_command, check_joint_state, check_pose,
                                check_timeout)


class Driver(ABC):
    """Minimal surface the rest of the system depends on. Keep it small —
    every method here is one more thing the mock must model faithfully."""

    @abstractmethod
    def joint_state(self):
        """-> dict with 'positions', 'velocities' (both sequences of float)."""

    @abstractmethod
    def eef_pose(self):
        """-> (x, y, z) in robot base frame, metres."""

    @abstractmethod
    def move_to(self, xyz, speed):
        """Blocking move to a Cartesian target. Raises on hardware fault."""

    @abstractmethod
    def set_gripper(self, force):
        """0.0 = fully open, 1.0 = maximum commanded close force."""

    @abstractmethod
    def enable(self):
        ...

    @abstractmethod
    def disable(self):
        ...

    @abstractmethod
    def safe_home(self, max_joint_velocity, timeout_s):
        """Execute the approved bounded homing route and stop on timeout."""


class SafeDriver:
    """Safety chokepoint. Not a subclass of Driver on purpose: it must not be
    substitutable for a raw driver, or someone could pass a raw one where a
    checked one is required and nothing would complain.
    """

    def __init__(self, driver, workspace, limits):
        self._d = driver
        self.workspace = workspace
        self.limits = limits
        self._faulted = None
        self.motions = 0

    @property
    def faulted(self):
        return self._faulted

    def clear_fault(self):
        """Deliberately explicit: a fault requires a human decision to clear.
        Auto-clearing is how a robot repeats the motion that just faulted."""
        previous, self._faulted = self._faulted, None
        return previous

    def _require_ok(self):
        if self._faulted is not None:
            raise SafetyViolation("driver is faulted; clear_fault() first",
                                  self._faulted)

    def _actuate(self, operation, function, *args):
        try:
            return function(*args)
        except BaseException as exc:
            self._faulted = (
                f"{operation} failed: {type(exc).__name__}: {exc}")
            raise

    def _read_state(self, operation, function):
        try:
            return function()
        except BaseException as exc:
            self._faulted = (
                f"{operation} failed: {type(exc).__name__}: {exc}")
            raise

    def joint_state(self):
        return self._d.joint_state()

    def eef_pose(self):
        return self._d.eef_pose()

    def move_to(self, xyz, speed=None):
        self._require_ok()
        speed = self.limits.max_cartesian_speed if speed is None else speed
        try:
            speed = check_cartesian_speed(speed, self.limits)
            joint_velocities = check_joint_state(
                self._read_state("move_to joint_state", self._d.joint_state),
                self.limits)
            distance = check_command(
                self._read_state("move_to eef_pose", self._d.eef_pose),
                xyz, self.workspace, self.limits,
                joint_velocities=joint_velocities)
        except SafetyViolation as exc:
            # Latch the fault: whatever produced this command is not trusted
            # to produce the next one either.
            self._faulted = exc.reason
            raise
        self._actuate("move_to", self._d.move_to, xyz, speed)
        self.motions += 1
        return distance

    def set_gripper(self, force):
        self._require_ok()
        from b601.safety.limits import check_gripper
        try:
            check_gripper(force, self.limits)
        except SafetyViolation as exc:
            self._faulted = exc.reason
            raise
        self._actuate("set_gripper", self._d.set_gripper, force)

    def enable(self):
        self._require_ok()
        self._actuate("enable", self._d.enable)

    def disable(self):
        """Always permitted, even when faulted — disabling must never be
        blocked by the fault state that makes you want to disable."""
        self._d.disable()

    def safe_home(self, timeout_s=30.0):
        self._require_ok()
        try:
            timeout_s = check_timeout(timeout_s, "safe_home")
            check_pose(
                self._read_state(
                    "safe_home pre eef_pose", self._d.eef_pose),
                self.workspace)
            check_joint_state(
                self._read_state(
                    "safe_home pre joint_state", self._d.joint_state),
                self.limits)
        except SafetyViolation as exc:
            self._faulted = exc.reason
            raise
        self._actuate(
            "safe_home", self._d.safe_home,
            self.limits.max_joint_velocity, timeout_s)
        try:
            check_pose(
                self._read_state(
                    "safe_home post eef_pose", self._d.eef_pose),
                self.workspace)
            check_joint_state(
                self._read_state(
                    "safe_home post joint_state", self._d.joint_state),
                self.limits)
        except SafetyViolation as exc:
            self._faulted = f"safe_home postcondition: {exc.reason}"
            raise
        self.motions += 1
