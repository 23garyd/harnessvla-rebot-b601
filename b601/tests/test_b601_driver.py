"""B601Driver: the Seeed LeRobot plugin adapted to our Cartesian Driver.

Tested against a stub robot, never the plugin, so the whole suite still runs
with no hardware, no CAN, no lerobot install. The stub models the plugin's
actual surface — including the three behaviours that will bite in production:

  - observations are FLAT keys in DEGREES (`shoulder_pan.pos`), not an array
  - `safe_zero(exit_on_complete=True)` raises KeyboardInterrupt ON SUCCESS
  - `disconnect()` runs safe_zero, i.e. disconnecting MOVES the arm

Unit boundary: degrees at the vendor edge, radians and metres everywhere
inside. `MotionLimits.max_joint_velocity` is rad/s; the plugin reports deg/s.
Getting that backwards is a 57x error in either direction.
"""
import math

import pytest

from b601.driver.b601 import (LEROBOT_MOTOR_ORDER, B601Driver,
                              B601DriverError)

DEG = LEROBOT_MOTOR_ORDER


class StubRobot:
    """Models the surface of SeeedB601RSFollower, in its units."""

    def __init__(self, positions_deg=None, velocities_deg=None,
                 connected=True):
        self.positions = dict(zip(DEG, positions_deg or [0.0] * 6))
        self.velocities = dict(zip(DEG, velocities_deg or [0.0] * 6))
        self.is_connected = connected
        self.actions = []
        self.calls = []
        self.torque_disabled = False
        self.safe_zero_raises_on_complete = False

    def get_observation(self):
        obs = {}
        for m in DEG:
            obs[f"{m}.pos"] = self.positions[m]
            obs[f"{m}.vel"] = self.velocities[m]
            obs[f"{m}.torque"] = 0.0
        obs["gripper.pos"] = 0.0
        obs["gripper.vel"] = 0.0
        obs["gripper.torque"] = 0.0
        return obs

    def send_action(self, action):
        self.actions.append(dict(action))
        for key, value in action.items():
            motor = key.removesuffix(".pos")
            if motor in self.positions:
                self.positions[motor] = value
        return action

    def safe_zero(self, step_interval_s=0.02, exit_on_complete=True):
        self.calls.append(("safe_zero", exit_on_complete))
        for m in DEG:
            self.positions[m] = 0.0
        if exit_on_complete:
            raise KeyboardInterrupt("safe_zero completed")

    def disable_torque(self):
        self.calls.append(("disable_torque",))
        self.torque_disabled = True

    def connect(self, calibrate=True):
        self.calls.append(("connect", calibrate))
        self.is_connected = True

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.is_connected = False


def flat_fk(q_deg):
    """Stand-in kinematics: 1 degree on joint 0 -> 1 mm in x."""
    return (0.30 + q_deg[0] * 0.001, 0.0, 0.20)


def flat_ik(xyz, q0_deg):
    return [(xyz[0] - 0.30) / 0.001] + list(q0_deg[1:])


def driver(robot=None, **kw):
    robot = robot or StubRobot()
    kw.setdefault("fk", flat_fk)
    kw.setdefault("ik", flat_ik)
    return robot, B601Driver(robot, **kw)


# --- units at the boundary ------------------------------------------------

def test_joint_state_is_returned_in_radians():
    """The plugin reports degrees; MotionLimits is rad/s. One conversion, at
    the edge, so nothing inside ever sees a degree."""
    robot, d = driver(StubRobot(positions_deg=[90, 0, 0, 0, 0, 0],
                                velocities_deg=[57.29578, 0, 0, 0, 0, 0]))
    state = d.joint_state()
    assert state["positions"][0] == pytest.approx(math.pi / 2)
    assert state["velocities"][0] == pytest.approx(1.0, abs=1e-5)


def test_joint_state_preserves_motor_order():
    robot, d = driver(StubRobot(positions_deg=[1, 2, 3, 4, 5, 6]))
    assert d.joint_state()["positions"] == pytest.approx(
        [math.radians(v) for v in (1, 2, 3, 4, 5, 6)])


def test_a_missing_motor_in_the_observation_is_an_error_not_a_zero():
    """The plugin substitutes 0.0 when a motor returns no state. A zero that
    means 'no reading' is indistinguishable from a real zero, and both the
    workspace guard and FK would consume it as truth."""
    robot = StubRobot()
    original = robot.get_observation

    def missing():
        obs = original()
        del obs["elbow_flex.pos"]
        return obs

    robot.get_observation = missing
    _, d = driver(robot)
    with pytest.raises(B601DriverError, match="elbow_flex"):
        d.joint_state()


# --- eef_pose is FK over the same snapshot --------------------------------

def test_eef_pose_is_fk_of_the_current_joint_positions():
    robot, d = driver(StubRobot(positions_deg=[10, 0, 0, 0, 0, 0]))
    assert d.eef_pose() == pytest.approx((0.31, 0.0, 0.20))


def test_fk_receives_degrees_not_radians():
    """RobotKinematics.forward_kinematics takes joint_pos_deg, and so does the
    vendor's convention. Converting first would silently shrink every angle."""
    seen = []
    robot, d = driver(StubRobot(positions_deg=[90, 0, 0, 0, 0, 0]),
                      fk=lambda q: (seen.append(tuple(q)) or (0.3, 0.0, 0.2)))
    d.eef_pose()
    assert seen[0][0] == pytest.approx(90.0)


def test_eef_pose_without_kinematics_fails_loudly():
    """No URDF configured means no pose. Returning a placeholder would hand
    the workspace guard a number with no relationship to the arm."""
    robot = StubRobot()
    d = B601Driver(robot)
    with pytest.raises(B601DriverError, match="no kinematics"):
        d.eef_pose()


def test_a_single_observation_serves_both_state_and_pose():
    """FK must describe the joint reading it was computed from; two reads
    would describe two different instants."""
    robot = StubRobot()
    reads = []
    original = robot.get_observation
    robot.get_observation = lambda: (reads.append(1) or original())
    _, d = driver(robot)
    d.snapshot()
    assert len(reads) == 1


# --- move_to --------------------------------------------------------------

def test_move_to_solves_ik_and_sends_degrees():
    robot, d = driver()
    d.move_to((0.32, 0.0, 0.20), speed=0.1)
    action = robot.actions[-1]
    assert action["shoulder_pan.pos"] == pytest.approx(20.0)
    assert set(action) == {f"{m}.pos" for m in DEG}


def test_move_to_without_kinematics_fails_loudly():
    d = B601Driver(StubRobot())
    with pytest.raises(B601DriverError, match="no kinematics"):
        d.move_to((0.32, 0.0, 0.20), speed=0.1)


# --- IK must be VERIFIED, not trusted -------------------------------------
#
# Measured against the real RobotKinematics on the vendor URDF: one
# inverse_kinematics() call leaves up to 0.101 m of residual on a reachable
# target, because placo's frame task is soft and the library solves once. It
# converges to zero in three or four iterations.
#
# Unverified, move_to would send a joint command whose achieved pose is 10 cm
# from the Cartesian target SafeDriver just approved — the chokepoint checking
# one point while the arm goes to another.

class DriftingIK:
    """IK that approaches the target geometrically, like a soft solver."""

    def __init__(self, factor=0.1, floor=0.0):
        self.factor = factor
        self.floor = floor
        self.calls = 0

    def __call__(self, xyz, q0_deg):
        self.calls += 1
        current_x = 0.30 + q0_deg[0] * 0.001
        remaining = xyz[0] - current_x
        step = remaining * (1 - self.factor) if abs(remaining) > self.floor \
            else remaining
        return [(current_x + step - 0.30) / 0.001] + list(q0_deg[1:])


def test_move_to_iterates_until_fk_confirms_the_target():
    ik = DriftingIK(factor=0.1)
    robot, d = driver(ik=ik, ik_tolerance_m=1e-6)
    d.move_to((0.35, 0.0, 0.20), speed=0.1)
    assert ik.calls > 1, "one soft solve is not a solution"
    achieved = flat_fk([robot.actions[-1]["shoulder_pan.pos"]] + [0] * 5)
    assert achieved[0] == pytest.approx(0.35, abs=1e-6)


def test_move_to_refuses_a_solution_that_does_not_reach_the_target():
    """Fail closed. Sending a nearest-approximation is the clamp this
    repository refuses to do, one layer down."""
    robot, d = driver(ik=DriftingIK(factor=0.9, floor=0.02),
                      ik_tolerance_m=1e-4, ik_max_iterations=5)
    with pytest.raises(B601DriverError, match="did not converge"):
        d.move_to((0.35, 0.0, 0.20), speed=0.1)
    assert robot.actions == [], "an unconverged solution was sent"


def test_the_convergence_failure_names_the_residual():
    _, d = driver(ik=DriftingIK(factor=0.9, floor=0.02),
                  ik_tolerance_m=1e-4, ik_max_iterations=3)
    with pytest.raises(B601DriverError, match=r"0\.0\d+ m"):
        d.move_to((0.35, 0.0, 0.20), speed=0.1)


def test_each_iteration_seeds_the_next_with_the_previous_solution():
    seen = []

    def recording_ik(xyz, q0_deg):
        seen.append(tuple(q0_deg))
        return flat_ik(xyz, q0_deg)

    robot, d = driver(StubRobot(positions_deg=[7, 0, 0, 0, 0, 0]),
                      ik=recording_ik)
    d.move_to((0.32, 0.0, 0.20), speed=0.1)
    assert seen[0][0] == pytest.approx(7.0), "first guess is the current pose"


def test_a_single_solve_that_lands_within_tolerance_sends_immediately():
    ik = DriftingIK(factor=0.0)
    robot, d = driver(ik=ik)
    d.move_to((0.32, 0.0, 0.20), speed=0.1)
    assert ik.calls == 1
    assert len(robot.actions) == 1


def test_verification_needs_fk_so_ik_alone_is_refused():
    """Without FK there is no way to know where a joint solution lands."""
    d = B601Driver(StubRobot(), ik=flat_ik)
    with pytest.raises(B601DriverError, match="no kinematics"):
        d.move_to((0.32, 0.0, 0.20), speed=0.1)


def test_move_to_reports_an_unreachable_target_rather_than_sending_nothing():
    def failing_ik(xyz, q0):
        raise ValueError("no IK solution")

    robot, d = driver(ik=failing_ik)
    with pytest.raises(B601DriverError, match="no IK solution"):
        d.move_to((0.9, 0.0, 0.20), speed=0.1)
    assert robot.actions == []


# --- safe_home ------------------------------------------------------------

def test_safe_home_never_lets_the_plugin_raise_on_success():
    """safe_zero(exit_on_complete=True) raises KeyboardInterrupt when it
    SUCCEEDS. Our chokepoint latches on BaseException, so the default would
    turn every successful home into a latched fault."""
    robot, d = driver()
    d.safe_home(max_joint_velocity=1.0, timeout_s=12.0)
    assert ("safe_zero", False) in robot.calls


def test_safe_home_propagates_a_real_failure():
    robot, d = driver()

    def failing(step_interval_s=0.02, exit_on_complete=True):
        raise RuntimeError("overtemperature during safe_zero")

    robot.safe_zero = failing
    with pytest.raises(RuntimeError, match="overtemperature"):
        d.safe_home(max_joint_velocity=1.0, timeout_s=12.0)


# --- enable / disable -----------------------------------------------------

def test_disable_releases_torque_and_does_not_disconnect():
    """The plugin's disconnect() runs safe_zero — disconnecting MOVES the arm.
    disable() must be the thing you can always reach for, so it cannot be
    wired to a call that commands motion."""
    robot, d = driver()
    d.disable()
    assert robot.torque_disabled is True
    assert ("disconnect",) not in robot.calls


def test_enable_connects_only_when_disconnected():
    robot, d = driver(StubRobot(connected=False))
    d.enable()
    assert ("connect", True) in robot.calls
    robot.calls.clear()
    d.enable()
    assert robot.calls == []


def test_operations_on_a_disconnected_robot_fail_clearly():
    robot, d = driver(StubRobot(connected=False))
    with pytest.raises(B601DriverError, match="not connected"):
        d.joint_state()


# --- gripper --------------------------------------------------------------

def test_gripper_maps_normalised_force_onto_the_configured_travel():
    robot, d = driver(gripper_travel_deg=(0.0, 40.0))
    d.set_gripper(0.5)
    assert robot.actions[-1] == {"gripper.pos": pytest.approx(20.0)}


def test_gripper_without_a_configured_travel_refuses():
    """The force-to-position mapping is hardware-measured. Guessing it is how
    a gripper closes harder than anyone intended."""
    _, d = driver()
    with pytest.raises(B601DriverError, match="gripper travel"):
        d.set_gripper(0.5)


# --- the motor-order assumption -------------------------------------------

def test_motor_order_is_explicit_and_overridable():
    """URDF joint1..joint6 vs the plugin's names is an ASSUMED correspondence.
    Wrong order gives poses that look plausible and are wrong everywhere but
    home, so it has to be visible and changeable, not buried."""
    robot = StubRobot()
    reversed_order = tuple(reversed(LEROBOT_MOTOR_ORDER))
    d = B601Driver(robot, fk=flat_fk, ik=flat_ik, motor_order=reversed_order)
    robot.positions[reversed_order[0]] = 45.0
    assert d.joint_state()["positions"][0] == pytest.approx(math.pi / 4)
