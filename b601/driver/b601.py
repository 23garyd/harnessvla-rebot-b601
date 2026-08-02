"""The real B601-RS driver: Seeed's LeRobot plugin, adapted to `Driver`.

The vendor stack is joint-space and in DEGREES; this repository's safety layer
is Cartesian, in metres and radians. This module is the whole of that
boundary. It wraps `SeeedB601RSFollower` UNMODIFIED — no fork of the plugin —
and adds forward/inverse kinematics on our side, where the tests are.

Why not inside the plugin: `eef_pose()` is the ground truth the workspace
guard checks against. Computing it in a forked dependency would put
safety-critical code outside `b601/`, outside this suite, and outside the rule
that a limit change is a reviewable diff with a registry entry. It would also
add a third indistinguishable `lerobot-robot-seeed-b601 1.0.0` to a pin gate
that already cannot tell forks apart.

THREE PLUGIN BEHAVIOURS THIS EXISTS TO CONTAIN, all read from its source:

  `safe_zero(exit_on_complete=True)` raises KeyboardInterrupt when it
  SUCCEEDS. That is the default. SafeDriver latches on BaseException, so the
  default would turn every successful home into a latched fault. We always
  pass False.

  `disconnect()` calls `safe_zero()` — disconnecting MOVES the arm. So
  `disable()` maps to `disable_torque()`, never to disconnect: the operation
  you reach for when something is wrong must not command motion.

  `send_action()` CLIPS to the plugin's own `joint_limits` and logs at debug.
  This repository rejects rather than clamps. Keep the plugin's limits WIDER
  than `limits.yaml` so ours bind first; a clip below us is then a bug, not a
  backstop. Unresolved until the limits are measured — see the risk log.

UNVERIFIED ON HARDWARE. Nothing here has run against an arm. The motor-order
assumption below is the most dangerous line in the file.
"""
import math

from b601.driver.base import Driver

# The plugin's motor names, assumed to correspond IN ORDER to the URDF's
# joint1..joint6 that FK/IK are solved over. Nothing enforces this; a wrong
# order produces poses that look plausible and are wrong everywhere except
# home. Confirm it joint-by-joint on Day 2 before trusting any pose.
LEROBOT_MOTOR_ORDER = ("shoulder_pan", "shoulder_lift", "elbow_flex",
                       "wrist_flex", "wrist_yaw", "wrist_roll")

GRIPPER_MOTOR = "gripper"

# From the vendor's config/rebotarm_rs.yaml. The URDF also carries two
# prismatic gripper fingers, which FK of the end-effector frame ignores and
# which must be kept OUT of the solver's joint list.
URDF_ARM_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6")
URDF_EE_FRAME = "gripper_end"


class B601DriverError(RuntimeError):
    """The vendor stack could not satisfy a request. Never swallowed."""


class B601Driver(Driver):
    """Adapter. Construct with an already-configured plugin robot.

    `fk` maps a 6-vector of joint DEGREES to (x, y, z) metres; `ik` maps
    (xyz, current_degrees) to a 6-vector of joint degrees. Both are injected
    so this class is testable without placo, without a URDF and without CAN.
    `from_urdf()` wires up LeRobot's placo-backed RobotKinematics.
    """

    def __init__(self, robot, fk=None, ik=None,
                 motor_order=LEROBOT_MOTOR_ORDER, gripper_travel_deg=None,
                 ik_tolerance_m=1e-4, ik_max_iterations=10):
        self._r = robot
        self._fk = fk
        self._ik = ik
        self.motor_order = tuple(motor_order)
        # A joint solution is only usable if we know where it puts the arm.
        # Measured on the real solver: ONE inverse_kinematics() call leaves up
        # to 0.101 m of residual, converging to zero in three or four. See
        # move_to.
        self.ik_tolerance_m = ik_tolerance_m
        self.ik_max_iterations = ik_max_iterations
        # (open_deg, closed_deg). The force-to-position mapping is measured on
        # hardware; there is no defensible default.
        self.gripper_travel_deg = gripper_travel_deg

    # --- construction -----------------------------------------------------

    @classmethod
    def from_urdf(cls, robot, urdf_path, ee_frame=URDF_EE_FRAME,
                  urdf_joints=URDF_ARM_JOINTS, orientation_weight=0.0, **kw):
        """Wire FK/IK to LeRobot's RobotKinematics (placo).

        Imported lazily: the unpowered suite must not need placo, and this
        repository's own tests inject stubs instead.

        Three things here are not defaults, each verified against the real
        RobotKinematics source rather than assumed:

        `urdf_joints` MUST be passed. Left to its default, RobotKinematics
        takes `robot.joint_names()`, which for this URDF is eight joints —
        joint1..joint6 plus the two prismatic gripper fingers — and it would
        then index a six-element command vector out of range.

        The URDF is staged beside its meshes. RobotKinematics constructs
        `placo.RobotWrapper(urdf_path)` directly, and placo resolves
        `filename="meshes/..."` against the URDF file's own directory; the
        vendor ships it one level below. Unstaged, construction fails.

        `orientation_weight` defaults to 0.0 — POSITION ONLY. The library's
        own default is 0.01, which asks IK to also reach a target orientation;
        `Driver.move_to` carries no orientation, so an identity rotation would
        be silently imposed as a goal and distort every solution.
        """
        import numpy as np

        try:
            from lerobot.model.kinematics import RobotKinematics
        except ImportError as exc:
            raise B601DriverError(
                "lerobot.model.kinematics is unavailable; install "
                '"lerobot[kinematics]" (placo). ' + str(exc)) from exc

        from b601.bringup.kinematics_check import staged_urdf
        with staged_urdf(urdf_path) as staged:
            solver = RobotKinematics(urdf_path=str(staged),
                                     target_frame_name=ee_frame,
                                     joint_names=list(urdf_joints))

        def fk(q_deg):
            T = solver.forward_kinematics(np.asarray(q_deg, dtype=float))
            return (float(T[0, 3]), float(T[1, 3]), float(T[2, 3]))

        def ik(xyz, q0_deg):
            target = np.eye(4)
            target[0, 3], target[1, 3], target[2, 3] = (float(v) for v in xyz)
            solved = solver.inverse_kinematics(
                np.asarray(q0_deg, dtype=float), target,
                orientation_weight=orientation_weight)
            return [float(v) for v in solved]

        return cls(robot, fk=fk, ik=ik, **kw)

    # --- reading ----------------------------------------------------------

    def _require_connected(self):
        if not getattr(self._r, "is_connected", False):
            raise B601DriverError(
                f"{type(self._r).__name__} is not connected; call enable()")

    def snapshot(self):
        """-> (positions_deg, velocities_deg) from ONE observation.

        One read, because joint state and the pose derived from it must
        describe the same instant. Two reads describe two.
        """
        self._require_connected()
        obs = self._r.get_observation()
        positions, velocities = [], []
        for motor in self.motor_order:
            for suffix, sink in ((".pos", positions), (".vel", velocities)):
                key = f"{motor}{suffix}"
                if key not in obs:
                    # The plugin substitutes 0.0 when a motor returns no
                    # state. A zero meaning "no reading" is indistinguishable
                    # from a real zero, and FK would consume it as truth.
                    raise B601DriverError(
                        f"observation has no {key!r}; motors reported: "
                        f"{sorted(k for k in obs if k.endswith(suffix))}")
                sink.append(float(obs[key]))
        return positions, velocities

    def joint_state(self):
        """-> radians and rad/s. The degree boundary ends here."""
        positions_deg, velocities_deg = self.snapshot()
        return {
            "positions": [math.radians(v) for v in positions_deg],
            "velocities": [math.radians(v) for v in velocities_deg],
        }

    def eef_pose(self):
        positions_deg, _ = self.snapshot()
        return self._forward(positions_deg)

    def _forward(self, positions_deg):
        if self._fk is None:
            raise B601DriverError(
                "no kinematics configured: eef_pose() needs a URDF. Build "
                "with B601Driver.from_urdf(robot, urdf_path). Returning a "
                "placeholder would hand the workspace guard a number with no "
                "relationship to the arm.")
        return tuple(self._fk(positions_deg))

    # --- motion -----------------------------------------------------------

    def move_to(self, xyz, speed):
        """Cartesian target -> IK -> joint command.

        `speed` is NOT honoured per command: the plugin's velocity lives in
        its `pos_vel_velocity` config, not in send_action(). SafeDriver has
        already bounded the requested speed; matching the configured value to
        that bound is a Day-2 configuration step, recorded in the runbook.
        """
        if self._ik is None or self._fk is None:
            raise B601DriverError(
                "no kinematics configured: move_to() needs a URDF for both IK "
                "and the FK that verifies its answer. Build with "
                "B601Driver.from_urdf(robot, urdf_path).")
        current_deg, _ = self.snapshot()

        # Solve, then CHECK WHERE THE SOLUTION LANDS. placo's frame task is
        # soft and RobotKinematics solves once: measured on the vendor URDF, a
        # single call left up to 0.101 m of residual on a reachable target.
        # SafeDriver validated the requested pose; sending an unverified
        # solution would send the arm somewhere else entirely.
        target_deg = list(current_deg)
        for _ in range(self.ik_max_iterations):
            try:
                target_deg = list(self._ik(xyz, target_deg))
            except Exception as exc:
                # Nothing is sent. A partially-solved target is not a target.
                raise B601DriverError(
                    f"inverse kinematics failed for {tuple(xyz)}: "
                    f"{exc}") from exc
            if len(target_deg) != len(self.motor_order):
                raise B601DriverError(
                    f"IK returned {len(target_deg)} joints, expected "
                    f"{len(self.motor_order)}")
            achieved = self._forward(target_deg)
            residual = sum((a - b) ** 2
                           for a, b in zip(achieved, xyz)) ** 0.5
            if residual <= self.ik_tolerance_m:
                break
        else:
            # Fail closed. Sending the nearest approximation would be the
            # clamp this repository refuses to do, one layer down.
            raise B601DriverError(
                f"inverse kinematics did not converge on {tuple(xyz)}: "
                f"{residual:.6f} m residual after {self.ik_max_iterations} "
                f"iterations, tolerance {self.ik_tolerance_m:.6f} m. The "
                f"target may be unreachable; nothing was sent.")

        self._r.send_action({f"{m}.pos": float(v)
                             for m, v in zip(self.motor_order, target_deg)})

    def set_gripper(self, force):
        if self.gripper_travel_deg is None:
            raise B601DriverError(
                "no gripper travel configured: the normalised force -> "
                "position mapping is measured on hardware, and guessing it is "
                "how a gripper closes harder than anyone intended. Pass "
                "gripper_travel_deg=(open_deg, closed_deg).")
        open_deg, closed_deg = self.gripper_travel_deg
        position = open_deg + (closed_deg - open_deg) * float(force)
        self._r.send_action({f"{GRIPPER_MOTOR}.pos": position})

    def safe_home(self, max_joint_velocity, timeout_s):
        """Vendor homing. `exit_on_complete=False` is not optional.

        With the default True the plugin raises KeyboardInterrupt on SUCCESS,
        which SafeDriver would latch as a fault.

        Neither `max_joint_velocity` nor `timeout_s` is enforced here: the
        plugin's safe_zero takes neither. They are bounds this layer passes
        down in name only — see the "does not cover" section in driver/base.py
        and the open risk-log entry.
        """
        self._require_connected()
        self._r.safe_zero(exit_on_complete=False)

    # --- power ------------------------------------------------------------

    def enable(self):
        if not getattr(self._r, "is_connected", False):
            self._r.connect(calibrate=True)

    def disable(self):
        """Torque off. NOT disconnect() — that calls safe_zero and moves the
        arm, and the operation you reach for when something is wrong must
        never be the one that commands motion."""
        self._r.disable_torque()
