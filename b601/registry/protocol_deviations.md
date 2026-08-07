# Protocol deviations — reBot B601-RS

Every deliberate departure from the plan document, with its reason. Empty is a
valid state; an undocumented deviation is not.

| Date | Deviation | Reason | Effect on claims |
|---|---|---|---|
| 2026-07-31 | Repo scaffolded as "Day 0", before the plan's Day 1 | Day 1 is charter, concept definition and safety boundary — work that should not compete with directory layout and tooling | None: no hardware powered, no data collected, no experiment version frozen |
| 2026-08-06 | Fixed top-view camera is a **Microdia DSJ-2062-309 UVC webcam**, not the planned RealSense D435 | A D435 is not present on this machine. The fixed camera's job is scene localisation for staging and re-grounding, which needs RGB; `calibration_report.md` already permits an image-space staging fallback instead of a camera-to-robot transform | **No depth from above.** Any staging estimate needing depth must come from the D405 or the image-space fallback. Verified working at 640x480 MJPG 30 fps, matching the wrist camera's rate |
| 2026-08-06 | D405 records **colour only**, no depth stream | The D405 negotiated USB 2.1 (480 Mbps). 640x480 rgb8 at 30 fps is ~221 Mbps; adding depth of the same size roughly doubles it and does not fit in practice. ACT consumes RGB | None for the policy. Removes depth as an input to grasp verification and staging. Reversible by moving the D405 to a USB 3.x cable and port, which is an experiment-version bump once episodes exist |

## Platform decisions — NOT deviations (2026-08-06)

The plan names "Ubuntu PC with RTX 5090" as the primary platform, and the
machine chosen matches it. Recorded here anyway because the *rejected*
alternatives cost real analysis, and without it someone will reasonably
propose them again in week 3.

| Machine | Role | Why |
|---|---|---|
| **EPYC + RTX 5090, 32 GB** | **Robot PC** — CAN, cameras, teleop, recording, ACT training, inference, harness runs, Day-20 demo | Matches the plan. `sm_120` with 32 GB VRAM; EPYC core count helps the one CPU-bound part of training (parallel video decode feeding the GPU). One machine means ONE pin regime, which is what `pin_check.sh` is built to identify |
| **ASUS + RTX A6000** | **Fallback robot PC** until the `sm_120` check passes; spare training capacity afterwards | `sm_86` is a mature, fully supported target. It is the insurance against Blackwell toolchain immaturity, and must stay available until that check passes |
| **Ubuntu + 2× Titan Xp** | Development and CI — the unpowered suite, mock-driven primitives/planner work, dataset inspection | See below. Deliberately NOT the robot PC |

**Why not the Titan Xp box, even though it is already wired to the arm.**
Titan Xp is Pascal (`sm_61`). NVIDIA's R570 driver branch was announced as the
last supporting Maxwell/Pascal/Volta, which caps the driver, which caps CUDA,
which caps the usable PyTorch. PyTorch has separately been trimming older
architectures as it adds Blackwell targets, so `sm_61` may not survive in
whatever wheel LeRobot resolves to. Compute was never the issue — ~12 TFLOPS
FP32 against a workload needing a few GFLOPs per chunk is ample — the issue is
building a 20-day project on a frozen driver branch and a shrinking support
window when a supported card is available. No tensor cores also forecloses the
plan's optional SmolVLA stretch goal. (The "NVLink" pair is an SLI bridge;
Titan Xp has no NVLink, and single-GPU inference would not use it either way.)

**Why training is local, not remote.** ACT is a small policy and the plan's
Days 11–14 are training days when the arm is idle, so a separate training box
solves a scheduling problem that does not exist. Splitting would put the
training environment outside the pin regime and add a dataset transfer step.

**The decision has one open condition.** The 5090 needs a working `sm_120`
PyTorch for *both* training and inference; if LeRobot's dependency resolution
pins a torch without those kernels, the robot PC cannot run the policy at all.
That check is a Day-2 gate in `RUNBOOK.md`, and the A6000 is the named
fallback. Do not release the A6000 until it passes.

**Unaffected by any of this:** off-machine backup for the demonstration
episodes is still required before the first pilot (Day 5). A single-machine
setup does not remove it — an operator session cannot be regenerated.
| 2026-08-07 | **Patched the vendor lerobot fork** — `editable+git:fe078af` -> `e77868a` | `_resolve_opencv_copy_source` in `lerobot/cameras/utils.py` read `camera_config.copy` unconditionally, but `OpenCVCameraConfig` on the `DepthCameraSupport` branch has no such field (its dataclass is fps, width, height, index_or_path, color_mode, rotation, warmup_s, fourcc; the only "copy" in that file is in the Apache licence header). `make_cameras_from_configs` therefore raised `AttributeError` for EVERY plain USB camera, so `lerobot-record` could not be used with one at all. `cameras/utils.py` evidently came from a version supporting the OpenCV stream-copy feature while `configuration_opencv.py` did not | Read via `getattr(..., "copy", False)`; absent means "not a copy", which is what `copy is False` already did, so the feature still works where the field exists. **Committed in the vendor checkout rather than left as a working-tree edit**, because `distribution_origin` refuses to pin a dirty tree — verified: the gate rejected the dirty tree, then rejected the origin drift, and `LEROBOT_ORIGIN` was re-recorded as `e77868a`. Episodes recorded before this commit (none) would not be comparable with episodes after |
