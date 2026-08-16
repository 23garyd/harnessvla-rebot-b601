"""The live io: wires the harness state machine to a lerobot robot.

Thin by design — every rule lives in a tested piece (io_support, perception,
grasp_verifier, harness) or in the pinned config (harness_io.json). This
module only sequences hardware calls.

Safety path for EVERY command, staged moves and policy alike:
    target -> RateLimiter (per-tick clamp vs previous command)
           -> DivergenceGuard (sustained |cmd - converted state| aborts)
           -> robot.send_action
A guard trip raises HarnessAbort, which the state machine converts to an
error_abort with NO further motion — including no go-home.

The robot object only needs get_observation() / send_action(); the dry-run
FakeRobot in run_harness satisfies the same contract, so the entire stack
below the CAN bus is exercisable without the arm.
"""
from __future__ import annotations

import json
import time

import numpy as np

from b601.planner.io_support import (
    StateActionMap, RateLimiter, MovePlanner, DivergenceGuard,
)
from b601.planner import perception


class HarnessAbort(RuntimeError):
    """Raised when the divergence guard trips. Never caught below Harness."""


class TickRecorder:
    """Per-trial telemetry: JSONL of every command tick + MP4 per camera."""

    def __init__(self, out_dir, fps, enabled=True):
        self._dir = out_dir
        self._fps = fps
        self._enabled = enabled
        self._jsonl = None
        self._writers = {}

    def start_trial(self, trial_idx):
        if not self._enabled:
            return
        import os
        os.makedirs(self._dir, exist_ok=True)
        self._trial = trial_idx
        self._jsonl = open(f"{self._dir}/trial_{trial_idx:03d}.jsonl", "w")

    def tick(self, phase, state, command, images):
        if not self._enabled or self._jsonl is None:
            return
        self._jsonl.write(json.dumps({
            "t": time.time(), "phase": phase,
            "state": [round(float(v), 3) for v in state],
            "command": [round(float(v), 3) for v in command],
        }) + "\n")
        import cv2
        for name, img in images.items():
            if img is None:
                continue
            if name not in self._writers:
                h, w = img.shape[:2]
                self._writers[name] = cv2.VideoWriter(
                    f"{self._dir}/trial_{self._trial:03d}_{name}.mp4",
                    cv2.VideoWriter_fourcc(*"mp4v"), self._fps, (w, h))
            self._writers[name].write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

    def end_trial(self):
        if self._jsonl is not None:
            self._jsonl.close()
            self._jsonl = None
        for w in self._writers.values():
            w.release()
        self._writers = {}


class LiveIO:
    """Implements the io contract of b601.planner.harness.Harness."""

    def __init__(self, robot, policy_step, cfg, verifier, recorder,
                 sleeper=time.sleep, clock=time.monotonic):
        self._robot = robot
        self._policy_step = policy_step   # callable(obs_dict) -> action vec 7
        self._cfg = cfg
        self._verifier = verifier
        self._rec = recorder
        self._sleep = sleeper
        self._clock = clock
        self._joints = cfg["joints"]
        self._sam = StateActionMap(cfg["state_action_map"])
        self._limiter = RateLimiter(np.asarray(cfg["rate_limits_per_tick"]))
        self._mover = MovePlanner(np.asarray(cfg["move_step_per_tick"]),
                                  tolerance=cfg["move_tolerance_deg"],
                                  max_ticks=cfg["move_max_ticks"])
        d = cfg["divergence"]
        self._guard = DivergenceGuard(d["threshold_deg"], d["sustain_ticks"])
        self._n_arm = d["arm_joints"]
        self._dt = 1.0 / cfg["fps"]
        self._phase = "idle"

    # -- plumbing --------------------------------------------------------
    def _obs(self):
        return self._robot.get_observation()

    def _state_vec(self, obs):
        return np.array([float(obs[f"{j}.pos"]) for j in self._joints])

    def _images(self, obs):
        return {k: v for k, v in obs.items() if isinstance(v, np.ndarray)
                and getattr(v, "ndim", 0) == 3}

    def start_trial_reference(self):
        """Anchor the rate limiter at the arm's ACTUAL position."""
        state = self._state_vec(self._obs())
        self._limiter.reset(self._sam.to_action(state))

    def _send(self, target_action):
        obs = self._obs()
        state = self._state_vec(obs)
        cmd = self._limiter.clamp(np.asarray(target_action, dtype=float))
        conv = self._sam.to_action(state)
        if not self._guard.update(cmd[:self._n_arm], conv[:self._n_arm]):
            raise HarnessAbort(
                f"divergence guard tripped on joint "
                f"{self._joints[self._guard.tripped_joint]} during {self._phase}")
        self._robot.send_action(
            {f"{j}.pos": float(cmd[i]) for i, j in enumerate(self._joints)})
        self._rec.tick(self._phase, state, cmd, self._images(obs))
        return cmd

    def _move_to_state_pose(self, pose_state, phase):
        self._phase = phase
        target = self._sam.to_action(np.asarray(pose_state, dtype=float))
        current = self._sam.to_action(self._state_vec(self._obs()))
        for waypoint in self._mover.plan(current, target):
            t0 = self._clock()
            self._send(waypoint)
            rest = self._dt - (self._clock() - t0)
            if rest > 0:
                self._sleep(rest)

    # -- harness io contract ---------------------------------------------
    def perceive_block(self):
        return perception.block_pixel(self._obs().get("agentview"))

    def block_in_saucer(self):
        s = self._cfg["saucer"]
        frac = perception.saucer_red_fraction(
            self._obs().get("agentview"), tuple(s["center"]), s["radius_px"])
        return frac >= s["red_fraction_threshold"]

    def stage(self, pose):
        self._move_to_state_pose(pose, "stage")

    def invoke_policy(self):
        self._phase = "policy"
        budget = float(self._cfg["policy_seconds_per_attempt"])
        end = self._clock() + budget
        while self._clock() < end:
            t0 = self._clock()
            obs = self._obs()
            action = self._policy_step(obs)
            self._send(np.asarray(action, dtype=float))
            rest = self._dt - (self._clock() - t0)
            if rest > 0:
                self._sleep(rest)

    def lift_to_verify(self):
        self._move_to_state_pose(self._cfg["poses_state_space"]["verify"],
                                 "lift_to_verify")

    def verify_frame(self):
        obs = self._obs()
        return self._verifier.verify(obs.get("eye_in_hand"),
                                     float(obs[f"{self._joints[6]}.pos"]))

    def place_recover(self):
        self._move_to_state_pose(self._cfg["poses_state_space"]["place"],
                                 "place_recover")
        # open the gripper in place: same pose, gripper to open
        release = list(self._cfg["poses_state_space"]["place"])
        release[6] = self._cfg["gripper_open_state"]
        self._move_to_state_pose(release, "release")
        self._sleep(0.5)

    def go_home(self):
        self._move_to_state_pose(self._cfg["poses_state_space"]["park"],
                                 "go_home")
        self._phase = "idle"
