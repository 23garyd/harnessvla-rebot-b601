#!/usr/bin/env python
"""Harness trial runner. Conda-env (robot-facing) entry point.

    python -m b601.planner.run_harness --trials 5            # live
    python -m b601.planner.run_harness --dry-run --trials 1  # no robot

SAFETY (live): autonomous powered motion. The operator stays within reach
of the e-stop for every trial. Trials NEVER auto-start: each one waits for
ENTER. Every command — staged moves and policy alike — passes the per-tick
rate limiter and the divergence guard; a guard trip ends the trial with no
further motion, including no go-home.

Dry-run replaces the robot with a corpus-frame player (perfect-tracking
state model) and exercises everything else for real: perception, staging
table, policy inference on the GPU, verifier, telemetry. It cannot react
to motion, so trials are expected to end in give-up; the point is that the
whole stack runs.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]


def load_cfg():
    with open(REPO / "b601" / "setup" / "harness_io.json") as f:
        return json.load(f)


class PolicyStepper:
    """Frozen-primitive inference, identical plumbing to lerobot-record:
    build_dataset_frame -> predict_action (pre/post processors from the
    checkpoint, dataset stats from the TRAINING corpus meta)."""

    def __init__(self, policy_path, device=None):
        import torch
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
        from lerobot.policies.factory import make_policy, make_pre_post_processors
        from lerobot.utils.utils import get_safe_torch_device

        self._torch = torch
        cfg = PreTrainedConfig.from_pretrained(policy_path)
        cfg.pretrained_path = policy_path
        meta = LeRobotDatasetMetadata(
            "local/b601_train_v2", root=str(REPO / "datasets" / "b601_train_v2"))
        self._features = meta.features
        self._policy = make_policy(cfg, ds_meta=meta)
        self._pre, self._post = make_pre_post_processors(
            policy_cfg=cfg, pretrained_path=policy_path,
            dataset_stats=meta.stats,
            preprocessor_overrides={"device_processor": {"device": cfg.device}},
        )
        self._device = get_safe_torch_device(cfg.device)
        self._use_amp = cfg.use_amp
        self._task = "pick up the red block and place it in the bowl"

    def reset(self):
        self._policy.reset()
        self._pre.reset()
        self._post.reset()

    def __call__(self, obs):
        from lerobot.datasets.utils import build_dataset_frame
        from lerobot.utils.constants import OBS_STR
        from lerobot.utils.control_utils import predict_action

        frame = build_dataset_frame(self._features, obs, prefix=OBS_STR)
        action = predict_action(
            observation=frame, policy=self._policy, device=self._device,
            preprocessor=self._pre, postprocessor=self._post,
            use_amp=self._use_amp, task=self._task,
            robot_type="seeed_b601_rs_follower",
        )
        vec = action.numpy() if hasattr(action, "numpy") else np.asarray(action)
        vec = np.asarray(vec, dtype=float).reshape(-1)
        if vec.shape != (7,):
            raise RuntimeError(f"policy action shape {vec.shape}, expected 7")
        return vec


class FakeRobot:
    """Dry-run stand-in: corpus frames on loop, perfect-tracking state."""

    def __init__(self, cfg, episode=10):
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        self._joints = cfg["joints"]
        m = np.asarray(cfg["state_action_map"]["m"], dtype=float)
        c = np.asarray(cfg["state_action_map"]["c"], dtype=float)
        self._inv = lambda a: (np.asarray(a) - c) / m
        ds = LeRobotDataset("local/b601_train_v2",
                            root=str(REPO / "datasets" / "b601_train_v2"),
                            tolerance_s=0.04)
        eps = ds.meta.episodes
        a = int(eps["dataset_from_index"][episode])
        self._frames = []
        for i in range(a, a + 90, 3):
            item = ds[int(i)]
            self._frames.append({
                "agentview": (item["observation.images.agentview"]
                              .permute(1, 2, 0).numpy() * 255).astype(np.uint8),
                "eye_in_hand": (item["observation.images.eye_in_hand"]
                                .permute(1, 2, 0).numpy() * 255).astype(np.uint8),
            })
        self._i = 0
        park = np.asarray(cfg["poses_state_space"]["park"], dtype=float)
        self._state = park.copy()

    def get_observation(self):
        f = self._frames[self._i % len(self._frames)]
        self._i += 1
        obs = dict(f)
        for j, name in enumerate(self._joints):
            obs[f"{name}.pos"] = float(self._state[j])
        return obs

    def send_action(self, action):
        cmd = np.array([float(action[f"{j}.pos"]) for j in self._joints])
        self._state = self._inv(cmd)


def make_real_robot(cfg):
    from lerobot.robots.utils import make_robot_from_config
    from lerobot.utils.import_utils import register_third_party_plugins
    register_third_party_plugins()
    from lerobot_robot_seeed_b601.config_seeed_b601_rs_follower import (
        SeeedB601RSFollowerConfig,
    )
    from b601.cameras.config import load_cameras
    from b601.cameras.lerobot_config import cameras_arg
    import draccus
    from lerobot.cameras import CameraConfig
    # importing registers the CameraConfig subclasses draccus decodes to
    from lerobot.cameras.opencv.configuration_opencv import (  # noqa: F401
        OpenCVCameraConfig,
    )
    from lerobot.cameras.realsense.configuration_realsense import (  # noqa: F401
        RealSenseD405ColorCameraConfig,
    )
    cam_cfgs = {}
    for name, cc in cameras_arg(load_cameras()).items():
        cam_cfgs[name] = draccus.decode(CameraConfig, cc)
    robot_cfg = SeeedB601RSFollowerConfig(
        port="can0", id="follower1", cameras=cam_cfgs)
    robot = make_robot_from_config(robot_cfg)
    robot.connect()
    return robot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--policy", default=str(
        REPO / "artifacts/act_b601_v2_20260828/checkpoints/100000/pretrained_model"))
    ap.add_argument("--policy-seconds", type=float, default=None,
                    help="override policy budget per attempt (dry-run tuning)")
    ap.add_argument("--out", default=str(REPO / "outputs" / "harness_trials"))
    args = ap.parse_args()

    from b601.planner.grasp_verifier import GraspVerifier
    from b601.planner.harness import Harness
    from b601.planner.live_io import LiveIO, TickRecorder
    from b601.staging.table import StagingTable

    cfg = load_cfg()
    if args.policy_seconds is not None:
        cfg["policy_seconds_per_attempt"] = args.policy_seconds

    table = StagingTable.load(str(REPO / "b601" / "setup" / "staging_table.json"))
    deep_path = REPO / "b601" / "setup" / "staging_table_deep.json"
    deep_table = StagingTable.load(str(deep_path)) if deep_path.exists() else None
    verifier = GraspVerifier.load(str(REPO / "b601" / "setup" / "grasp_verifier.json"))
    policy = PolicyStepper(args.policy)
    print("policy loaded")

    robot = FakeRobot(cfg) if args.dry_run else make_real_robot(cfg)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = f"{args.out}/{stamp}{'_dry' if args.dry_run else ''}"
    recorder = TickRecorder(out_dir, cfg["fps"])
    io = LiveIO(robot, policy, cfg, verifier, recorder)
    harness = Harness(table, io, verify_burst=cfg["verify_burst"],
                      verify_majority=cfg["verify_majority"],
                      deep_table=deep_table,
                      recovery_from_attempt=cfg.get(
                          "recovery", {}).get("from_attempt"))

    results = []
    for trial in range(1, args.trials + 1):
        if not args.dry_run:
            from b601.planner.trial_gate import trial_drift_check
            while True:
                input(f"\n=== trial {trial}/{args.trials}: stage the block, "
                      "park the arm, HANDS CLEAR + OUT OF FRAME, e-stop in "
                      "reach. ENTER to start === ")
                # the start-of-session gate cannot see mid-session creep
                # (measured: ~10 px between v1 same-evening sessions)
                report = trial_drift_check(robot.get_observation)
                print("  " + report.summary())
                if report.passed:
                    break
                print("  trial REFUSED on a drifted mount — fix the camera "
                      "(or deliberately re-record the reference + pins), "
                      "then try again")
        recorder.start_trial(trial)
        io.start_trial_reference()
        policy.reset()
        t0 = time.monotonic()
        result = harness.run_trial()
        recorder.end_trial()
        rec = {
            "trial": trial, "outcome": result.outcome, "detail": result.detail,
            "seconds": round(time.monotonic() - t0, 1),
            "attempts": [
                {"index": a.index, "pixel": list(a.pixel),
                 "staging_distance_px": a.staging_distance_px,
                 "held": a.held, "reason": a.reason}
                for a in result.attempts
            ],
        }
        results.append(rec)
        print(json.dumps(rec, indent=1))
        with open(f"{out_dir}/results.json", "w") as f:
            json.dump(results, f, indent=1)
        if result.outcome == "error_abort":
            print("\n!! ERROR ABORT — arm NOT homed. Inspect before continuing.")
            break
    print(f"\ntelemetry: {out_dir}")


if __name__ == "__main__":
    main()
