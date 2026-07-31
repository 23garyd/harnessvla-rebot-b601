"""In-memory B601 stand-in, so the test suite runs with the arm unpowered.

Deliberately NOT a physics simulator. It models exactly what the safety and
integration tests need to assert:
  - pose and joint state that respond to commands
  - a command log, so tests can check WHAT was sent, not just that nothing threw
  - injectable faults, so fault handling is tested without breaking hardware
  - an optional grasp outcome, so the Day-16 verification/retry logic can be
    exercised against empty grasps before a real gripper ever closes

If a test needs behaviour this does not model, add it here rather than
reaching for the real arm — the point is that CI never needs hardware.
"""
from b601.driver.base import Driver

HOME = (0.30, 0.00, 0.35)


class MockDriver(Driver):
    def __init__(self, start=HOME, n_joints=6, grasp_succeeds=True):
        self._pose = tuple(start)
        self._positions = [0.0] * n_joints
        self._velocities = [0.0] * n_joints
        self._gripper = 0.0
        self.enabled = False
        self.commands = []          # full audit trail of what was sent
        self.fault_on_next_move = None
        self.fault_on_next_gripper = None
        self.fault_on_next_home = None
        self.home_result = HOME
        self.grasp_succeeds = grasp_succeeds
        self.holding = False

    # --- Driver interface -------------------------------------------------
    def joint_state(self):
        return {"positions": list(self._positions),
                "velocities": list(self._velocities)}

    def eef_pose(self):
        return self._pose

    def move_to(self, xyz, speed):
        if self.fault_on_next_move is not None:
            fault, self.fault_on_next_move = self.fault_on_next_move, None
            self.commands.append(("move_to", tuple(xyz), speed, "FAULT"))
            raise RuntimeError(f"mock hardware fault: {fault}")
        self.commands.append(("move_to", tuple(xyz), speed))
        self._pose = tuple(xyz)

    def set_gripper(self, force):
        if self.fault_on_next_gripper is not None:
            fault, self.fault_on_next_gripper = (
                self.fault_on_next_gripper, None)
            self.commands.append(("set_gripper", force, "FAULT"))
            raise RuntimeError(f"mock hardware fault: {fault}")
        self.commands.append(("set_gripper", force))
        self._gripper = force
        # Closing on a graspable object: holding iff the scenario says so.
        if force > 0.5:
            self.holding = self.grasp_succeeds
        else:
            self.holding = False

    def enable(self):
        self.commands.append(("enable",))
        self.enabled = True

    def disable(self):
        self.commands.append(("disable",))
        self.enabled = False

    def safe_home(self, max_joint_velocity, timeout_s):
        if self.fault_on_next_home is not None:
            fault, self.fault_on_next_home = self.fault_on_next_home, None
            self.commands.append(
                ("safe_home", max_joint_velocity, timeout_s, "FAULT"))
            raise RuntimeError(f"mock hardware fault: {fault}")
        self.commands.append(("safe_home", max_joint_velocity, timeout_s))
        self._pose = tuple(self.home_result)

    # --- test helpers -----------------------------------------------------
    def set_velocities(self, velocities):
        """Force a joint-velocity reading, to exercise the velocity guard."""
        self._velocities = list(velocities)

    def last(self, kind=None):
        for c in reversed(self.commands):
            if kind is None or c[0] == kind:
                return c
        return None
