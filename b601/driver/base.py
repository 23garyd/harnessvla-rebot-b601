"""Driver interface for the reBot B601-RS, and the safety-enforcing wrapper.

Two implementations sit behind `Driver`:
  - `MockDriver`   (b601/driver/mock.py) — no hardware, used by the whole test
                    suite so every test runs with the arm unpowered
  - `B601Driver`   (b601/driver/b601.py) — the vendor SDK, added on Day 2

`SafeDriver` wraps EITHER of them and is the only thing the rest of the
codebase is allowed to hold. It routes Cartesian motion through
b601.safety.limits.check_command and refuses to move after a fault until
explicitly cleared. Primitives, planner and policy all talk to SafeDriver.

WHAT THIS DOES NOT COVER (stated here rather than implied, per the risk log):
`safe_home()` is NOT path-checked. Homing is a joint-space trajectory whose
intermediate poses this layer never sees, and a Cartesian per-waypoint step
limit would reject legitimate homing while proving nothing about the path
taken. Checking only its destination would be worse: coverage that looks real.
Its bounded contract — approved home configuration, joint velocity and
acceleration caps, trajectory monitoring, timeout, verified terminal joint
state — belongs with the vendor driver and is a Day-2 deliverable. Until then
`safe_home` is fault-latched and audited, not validated.
"""
import math
from abc import ABC, abstractmethod

from b601.safety.limits import SafetyViolation, check_command


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
    def safe_home(self):
        """Return to the documented home pose at low speed."""


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

    def _actuate(self, what, call):
        """Run a hardware call, latching a fault if it does not complete.

        FAIL CLOSED. A driver exception means the motion did not finish as
        commanded, so the arm is not where the last command said it was — and
        check_step measures the next waypoint from eef_pose(). Continuing
        would check the next command against a stale reading. BaseException,
        not Exception: an operator Ctrl-C mid-motion leaves the arm in the
        same uncertain state as a driver failure.
        """
        try:
            return call()
        except BaseException as exc:
            self._faulted = f"hardware fault during {what}: {exc}"
            raise

    def joint_state(self):
        return self._d.joint_state()

    def eef_pose(self):
        return self._d.eef_pose()

    def move_to(self, xyz, speed=None):
        self._require_ok()
        speed = self.limits.max_cartesian_speed if speed is None else speed
        # Bounded on BOTH sides and required finite. Checking only the upper
        # bound let NaN through (it fails every comparison) and negatives too,
        # whose meaning is a vendor-SDK guess we must never take.
        if (isinstance(speed, bool) or not isinstance(speed, (int, float))
                or not math.isfinite(speed) or speed <= 0):
            self._faulted = f"speed {speed!r} is not a positive finite value"
            raise SafetyViolation("cartesian speed invalid", speed)
        if speed > self.limits.max_cartesian_speed:
            self._faulted = f"speed {speed} over limit"
            raise SafetyViolation("cartesian speed over limit", speed)
        try:
            distance = check_command(
                self._d.eef_pose(), xyz, self.workspace, self.limits,
                joint_velocities=self._d.joint_state().get("velocities"))
        except SafetyViolation as exc:
            # Latch the fault: whatever produced this command is not trusted
            # to produce the next one either.
            self._faulted = exc.reason
            raise
        self._actuate("move_to", lambda: self._d.move_to(xyz, speed))
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
        self._actuate("set_gripper", lambda: self._d.set_gripper(force))

    def enable(self):
        self._d.enable()

    def disable(self):
        """Always permitted, even when faulted — disabling must never be
        blocked by the fault state that makes you want to disable."""
        self._d.disable()

    def safe_home(self):
        """Return to the documented home pose. NOT path-checked — see the
        module docstring for why, and for the Day-2 contract that must exist
        before this is used under power. It is counted (it moves the arm) and
        fault-latched (it can fail like any other motion)."""
        self._require_ok()
        self._actuate("safe_home", self._d.safe_home)
        self.motions += 1
