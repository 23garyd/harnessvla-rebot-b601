"""The servo LOOP in live_io (the controller itself is covered in
test_harness_io). Two live-measured failure modes from the 2026-08-28
recovery shakedown (outputs/harness_trials/20260828_074607), where all six
recovery servos exhausted their budget without converging:

1. y-correction split across lift+elbow self-cancels: the v2 per-joint fit
   shows lift -3.75 / elbow +10.23 px/deg on image y at depth — the equal
   split spends two joints to move the image almost nowhere. The correction
   must go to the ELBOW alone.

2. re-anchoring the command to the CURRENT state each tick ratifies
   uncommanded drift: with gravity droop at the deep pose, command(n+1) =
   state(n) = command(n) - droop ratchets the arm downward (measured -19 deg
   of never-commanded reach motion in one 50-tick servo run). The loop must
   hold a persistent target so drift is resisted, not adopted.
"""
import numpy as np
import pytest

from b601.planner import perception
from b601.planner.live_io import LiveIO, TickRecorder

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex",
          "wrist_yaw", "wrist_roll", "gripper"]
IDENTITY = {"m": [1, 1, 1, 1, 1, 1, 1], "c": [0, 0, 0, 0, 0, 0, 0]}
TARGET = (387.0, 395.0)
JX_PAN, JY_ELBOW = -12.8, 10.2
START = [10.0, 40.0, 30.0, -20.0, 0.0, 5.0, 265.0]


def make_cfg():
    return {
        "joints": JOINTS,
        "state_action_map": IDENTITY,
        "rate_limits_per_tick": [10.0] * 7,
        "move_step_per_tick": [10.0] * 7,
        "move_tolerance_deg": 1.0,
        "move_max_ticks": 600,
        "divergence": {"threshold_deg": 30.0, "sustain_ticks": 30,
                       "arm_joints": 6},
        "fps": 30,
        "gripper_open_state": 265.0,
        "servo": {
            "target": list(TARGET), "tolerance_px": 10.0, "gain": 0.3,
            "max_step_deg": 1.0, "max_total_deg": 40.0, "max_ticks": 360,
            "stall_ticks": 60, "jx_pan": JX_PAN, "jy_elbow": JY_ELBOW,
            "lead_cap_deg": 5.0,
        },
    }


class PlantRobot:
    """Linear image plant on a command-tracking arm.

    Centroid follows the true jacobian from pan/elbow STATE. lift_droop
    models gravity deflection at the deep pose: the lift joint settles a
    constant offset BELOW whatever was last commanded (a PD servo under
    load), which is exactly the plant that turns command re-anchoring into
    a downward ratchet."""

    def __init__(self, start_centroid, lift_droop=0.0):
        self.state = np.array(START, dtype=float)
        self._c0 = np.array(start_centroid, dtype=float)
        self._ref = self.state.copy()
        self._droop = float(lift_droop)
        self.commands = []

    def centroid(self):
        cx = self._c0[0] + JX_PAN * (self.state[0] - self._ref[0])
        cy = self._c0[1] + JY_ELBOW * (self.state[2] - self._ref[2])
        return (float(cx), float(cy))

    def get_observation(self):
        obs = {f"{j}.pos": float(self.state[i])
               for i, j in enumerate(JOINTS)}
        obs["eye_in_hand"] = np.zeros((480, 640, 3), dtype=np.uint8)
        return obs

    def send_action(self, action):
        cmd = np.array([float(action[f"{j}.pos"]) for j in JOINTS])
        self.commands.append(cmd)
        self.state = cmd.copy()
        if self._droop:
            self.state[1] = cmd[1] - self._droop


def make_io(robot, tmp_path, monkeypatch):
    monkeypatch.setattr(perception, "wrist_block_pixel",
                        lambda img: robot.centroid())
    rec = TickRecorder(str(tmp_path), fps=30, enabled=False)
    io = LiveIO(robot, policy_step=None, cfg=make_cfg(), verifier=None,
                recorder=rec, sleeper=lambda s: None)
    io.start_trial_reference()
    return io


class TestServoLoop:

    def test_y_error_corrected_by_elbow_alone(self, tmp_path, monkeypatch):
        """Block 40 px low in the wrist frame, x already on target: the
        loop must converge by moving ONLY the elbow — pan and lift must
        hold (the lift half of the old split is what cancelled progress
        and plunged the arm at the deep pose)."""
        robot = PlantRobot(start_centroid=(TARGET[0], TARGET[1] + 40.0))
        io = make_io(robot, tmp_path, monkeypatch)
        assert io._servo_to_pregrasp() is True
        cmds = np.array(robot.commands)
        assert abs(cmds[-1][1] - START[1]) < 0.01, "lift must not move"
        assert abs(cmds[-1][0] - START[0]) < 0.01, "pan must not move"
        d_elbow = cmds[-1][2] - START[2]
        assert -6.0 < d_elbow < -1.0, (
            f"elbow should walk ~-40px/{JY_ELBOW} = -3.9 deg, got {d_elbow}")

    def test_uncommanded_droop_is_resisted_not_ratified(self, tmp_path,
                                                        monkeypatch):
        """Lift settles 0.4 deg below every command (gravity at the deep
        pose) while the servo corrects a pure-x error. The loop must NOT
        walk its lift command downward tick after tick: the servo never
        commanded lift, so the last lift command must stay at the start
        value instead of ratcheting away with the droop."""
        robot = PlantRobot(start_centroid=(TARGET[0] + 90.0, TARGET[1]),
                           lift_droop=0.4)
        io = make_io(robot, tmp_path, monkeypatch)
        assert io._servo_to_pregrasp() is True
        cmds = np.array(robot.commands)
        drift = cmds[-1][1] - cmds[0][1]
        assert abs(drift) < 1.0, (
            f"lift command ratcheted {drift:+.1f} deg with the droop "
            f"over {len(cmds)} sends — re-anchoring ratified the sag")
