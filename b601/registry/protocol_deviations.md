# Protocol deviations — reBot B601-RS

Every deliberate departure from the plan document, with its reason. Empty is a
valid state; an undocumented deviation is not.

| Date | Deviation | Reason | Effect on claims |
|---|---|---|---|
| 2026-07-31 | Repo scaffolded as "Day 0", before the plan's Day 1 | Day 1 is charter, concept definition and safety boundary — work that should not compete with directory layout and tooling | None: no hardware powered, no data collected, no experiment version frozen |
| 2026-08-06 | Fixed top-view camera is a **Microdia DSJ-2062-309 UVC webcam**, not the planned RealSense D435 | A D435 is not present on this machine. The fixed camera's job is scene localisation for staging and re-grounding, which needs RGB; `calibration_report.md` already permits an image-space staging fallback instead of a camera-to-robot transform | **No depth from above.** Any staging estimate needing depth must come from the D405 or the image-space fallback. Verified working at 640x480 MJPG 30 fps, matching the wrist camera's rate |
| 2026-08-06 | D405 records **colour only**, no depth stream | The D405 negotiated USB 2.1 (480 Mbps). 640x480 rgb8 at 30 fps is ~221 Mbps; adding depth of the same size roughly doubles it and does not fit in practice. ACT consumes RGB | None for the policy. Removes depth as an input to grasp verification and staging. Reversible by moving the D405 to a USB 3.x cable and port, which is an experiment-version bump once episodes exist |
| 2026-08-12 | **Patched the vendor lerobot fork (fourth patch)** — `c8642e7` -> next | `decode_video_frames_torchcodec` computed frame indices as `round(ts*fps)` with no bounds check; on video files holding many concatenated episodes, cumulative float error in the per-episode timestamp offsets tips the FINAL frame's index to exactly `num_frames`, and `get_frames_at` raises. Killed the first v1 training run 8 minutes in ('Invalid frame index=3963 … must be less than 3963'); the same defect had surfaced repeatedly during audits as boundary decode failures | Indices clamped to `[0, num_frames-1]` — worst case returns the true final frame one period early, and the existing tolerance assertion still rejects genuinely wrong frames. `LEROBOT_ORIGIN` re-pinned | None for data: pure read-path fix. Training relaunched from step 0 |
| 2026-08-12 | **Patched the vendor lerobot fork (third patch)** — `3b4f877` -> `c8642e7` | `lerobot-record` announced "Recording episode N" NON-blocking, so frames were already being saved while the sentence was still being spoken (~2 s of TTS latency). An operator who treats the announcement as the start signal is that late, and whatever their hands are finishing — withdrawing from a scene reset, repositioning the leader — lands in the episode head. Measured on this rig as 1–3 s head contamination; the boundary-motion audit that found it is in the dataset card. The episode-END path needed no change: exit_early is polled every frame (33 ms) | Announcement made blocking, so recording starts only when the voice finishes. Costs ~2 s per episode. `LEROBOT_ORIGIN` re-pinned and verifying | None retroactively — episodes already collected keep their audited status; sessions from here start cleaner |
| 2026-08-07 | **Patched the vendor lerobot fork again** — `editable+git:e77868a` -> `3b4f877` | `_build_frame_snapshot` in `cameras/realsense/camera_realsense.py` tested frames with `is not None`, but `get_depth_frame()` on a colour-only frameset returns a NULL frame object — falsy, never None — so `get_data()` on it raised `null pointer passed for argument "frame_ref"` for every frameset, the read loop suppressed it as a transient startup error, and a colour-only D405 delivered zero frames through the wrapper while the raw API streamed perfectly. Our manifest records colour-only (see the USB-2 deviation above), so this hit every recording attempt | Changed to truthiness, the librealsense-documented null-frame check. Committed in the vendor checkout, `LEROBOT_ORIGIN` re-pinned and verified. Measured after the fix: `async_read` 90/90 at 30.4 fps. Depth-and-colour configurations (how the branch was presumably tested upstream) never hit this, which is why it survived in the vendor tree | None for episodes: no episode was ever recorded under the broken wrapper (it recorded nothing at all). Episodes require this commit or later |
| 2026-08-07 | **Patched the vendor lerobot fork** — `editable+git:fe078af` -> `e77868a` | `_resolve_opencv_copy_source` in `lerobot/cameras/utils.py` read `camera_config.copy` unconditionally, but `OpenCVCameraConfig` on the `DepthCameraSupport` branch has no such field (its dataclass is fps, width, height, index_or_path, color_mode, rotation, warmup_s, fourcc; the only "copy" in that file is in the Apache licence header). `make_cameras_from_configs` therefore raised `AttributeError` for EVERY plain USB camera, so `lerobot-record` could not be used with one at all. `cameras/utils.py` evidently came from a version supporting the OpenCV stream-copy feature while `configuration_opencv.py` did not | Read via `getattr(..., "copy", False)`; absent means "not a copy", which is what `copy is False` already did, so the feature still works where the field exists. **Committed in the vendor checkout rather than left as a working-tree edit**, because `distribution_origin` refuses to pin a dirty tree — verified: the gate rejected the dirty tree, then rejected the origin drift, and `LEROBOT_ORIGIN` was re-recorded as `e77868a`. Episodes recorded before this commit (none) would not be comparable with episodes after |

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
