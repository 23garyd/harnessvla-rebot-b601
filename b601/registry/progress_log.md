# Progress log — reBot B601-RS

One entry per working day. **Every entry that produces numbers embeds the
result table** — not a summary of it. This convention is carried over from the
simulation track, where it repeatedly turned out to be the only place a claim
could be checked against its evidence.

## Day 0 — repo scaffold (2026-07-31)

Before Day 1, so Day 1 is charter and safety rather than directory layout.

- Structure: `b601/{safety,driver,cameras,primitives,policy,planner,analysis,registry,manifests,setup,tests}`.
- **Safety layer first** (`b601/safety/limits.py` + `SafeDriver`): one chokepoint
  every motion passes through, pure functions, limits as data in
  `setup/limits.yaml` (all values PROVISIONAL pending Day-2 measurement).
- **Mock driver first** (`b601/driver/mock.py`): the whole suite runs with the
  arm unpowered, including induced empty grasps for the Day-16 verifier.
- **28 safety tests green**, no hardware.
- `pin_check.sh` gates two regimes: software (LeRobot) and **physical**
  (camera serials + calibration hash).
- Analysis modules vendored from `harnessvla-sim-reproduction@ffb0022`
  (`schemas`, `build_ledger`, `compare`, `disk_guard`, `manifests`) — verified
  identical at that commit and at the sim repo's later HEAD.
- Open: dataset backup target undecided; all limits provisional; no hardware
  powered; no data collected.

### Day 0 addendum — inheritance review of the vendored analysis layer

External review asked whether the sim→B601 inheritance path is sound. The
architecture is (findings + analysis tooling + RPent read at a pin; no
released checkpoint), but the vendored copies still carried sim assumptions:

| Defect | Consequence had it survived |
|---|---|
| `run_meta` stored no physical pins | `pin_check.sh` gated camera serials and calibration at launch; the record stored neither, so Day-18 could not attribute an episode to a configuration |
| No `safety_abort` terminal status | A latched SafeDriver fault could only be filed as `valid_failure` — counted as a task failure, absorbed into the rate the Day-18 "zero safety events" gate reads |
| `build_ledger` imported `track.analysis` | The vendored module could not be imported in this repo at all |
| `compare.summarize` raised on 0 pairs | Any Day-18 rebuild where exclusions emptied a cell would crash instead of reporting 0/0 |
| `limits.yaml` had no loader | Day-2 measured limits would have changed nothing; the file was documentation, not data |

Fixed with 47 new tests (47 → 94). Divergence from the sim copies is recorded
in `b601/analysis/VENDORED.md`; the zero-pair crash is latent upstream too.
No limit VALUES changed — the envelope is still the provisional Day-0 one.

### Day 0 addendum — chokepoint review (powered-motion blockers)

A second external review went at the driver layer, where the previous round
had not looked. Three gaps, all verified by direct execution before fixing:

| Defect | Consequence had it survived |
|---|---|
| A driver exception escaped `SafeDriver.move_to` without latching | Verified: an injected overcurrent was followed by an **accepted** motion. Worse than the missing latch, `check_step` measures the next waypoint from `eef_pose()`, so after an incomplete motion every later check is computed from a stale pose |
| Speed was bounded above only | Verified: `-5.0` and `NaN` both reached the driver (NaN fails every comparison; `inf` was already caught). The only guard in the module that did not reject NaN, while `check_pose`/`check_gripper`/`check_joint_velocity` all do |
| `safe_home` unchecked, uncounted, unlatched | Not fixable here — see the risk log. Now fault-latched and counted, with the gap stated in the module docstring instead of contradicted by it |

Same treatment applied to `set_gripper` and `safe_home`, which had the
identical unlatched-exception hole; `BaseException`, so an operator Ctrl-C
mid-motion latches like any other incomplete actuation.

Also: `PYTHON_EXECUTABLE` is now a gated pin. `B601_PY` is a legitimate
override (the robot PC may run a managed environment), but pins recorded under
one interpreter and verified under another compare two installations and
report agreement. It had been written into `pins.env` as a comment — recorded,
never gated. Checked first, before every pin whose value depends on it.

21 new tests (94 → 115). **Powered planner-controlled motion still waits on
the Day-2 `safe_home` contract.**

## Day 1 — charter and safety boundary (2026-07-31)

Recorded from what is verifiable in this repository. Where an item is a
mentor or hardware event, it is marked unevidenced rather than assumed.

| Day-1 deliverable | State |
|---|---|
| Project charter, scope, out-of-scope | `README.md`, `HANDOVER.md` — in scope: planner-staged frozen ACT primitive; explicitly out: running released LIBERO pi0.5 on the B601 |
| Paper-mechanism → B601 mapping | `docs/reference_material.md` (RPent read at pin `6e4ba18`, run from never) and `docs/sim_findings_that_transfer.md` (seven measured sim findings, each with its B601 consequence) |
| Data-flow diagram: instruction → perception → staging → ACT → verify → transport → retry | **Not present as a diagram.** The mapping exists in prose; a drawn flow does not |
| Safety checklist, restricted workspace, speed/acceleration limits | `b601/setup/limits.yaml` (workspace + motion, all PROVISIONAL) enforced by `b601/safety/`; **no acceleration limit exists** |
| Risk register | `b601/registry/risk_log.md`, four risks, two open |
| Daily engineering-log template | This file's per-day convention |
| System inventory (arm, CAN adapter, PSU, cameras, mounts, teleop, e-stop) | **Absent** — needs the hardware in front of you |
| **Acceptance gate: mentor approves scope and safety controls before any powered autonomous motion** | **NOT EVIDENCED IN THIS REPOSITORY.** No sign-off record exists. Everything below is gated on it |

## Day 2 — software half of bring-up (2026-08-01)

No hardware was powered. What landed is the code Day 2 needs to *have* before
the arm is switched on, so that on bring-up day the arm is the only new
variable.

**Safety chokepoint, hardened** (external review, two rounds — see the Day-0
addenda for the first). This round:

| Change | Why |
|---|---|
| Homing precondition no longer requires the current pose to be inside the workspace | It refused to home whenever the arm was out of bounds — after a fault, at power-on from an unknown pose, or when a bad estimate staged it outside. That is the state homing exists to recover from. The reading is still validated for shape and finiteness (`check_pose_reading`); only containment was dropped |
| `safe_home` postcondition asserts arrival at an approved home | It previously accepted any terminal pose inside the workspace — "stopped somewhere legal", not "came home". `HomeContract` (pose + arrival radius) is now required to home at all; `SafeDriver` refuses rather than degrading to a check it could pass without arriving |
| `home:` section added to `limits.yaml`, loaded by `load_home()` | The approved configuration is envelope data like everything else. **`tolerance_m` is the one number Day 2 must set FROM `repeatability.csv`** — an arrival radius tighter than the arm's measured repeatability would fault on every successful home |
| `base.py` states its blind spots again | The section had been dropped while the docstring claimed "every motion reaches the appropriate safety boundary". Trajectory monitoring, timeout enforcement, acceleration and collision are all still uncovered, and now say so |

**Repeatability harness** (`b601/bringup/repeatability.py`): five poses ×
four cycles = the gate's twenty motions, logging commanded vs achieved, error
per axis and Euclidean, duration, speed and faults to `repeatability.csv`,
with per-pose statistics and a text error histogram. Two refusals are built in:

- It **stops at the first fault** and reports *consecutive* clean motions.
  Twenty motions counted across a fault is not the quantity the gate names.
- It **cannot pass the gate by itself.** Collisions and manual corrections are
  human observations; nothing in the process perceives them. `gate_status()`
  requires an explicit operator attestation, so a green run can never be
  mistaken for a gate someone actually watched.

Dry run against `MockDriver`: 20/20 clean, gate correctly **NOT PASSED** —
no operator attestation.

**Vendor SDK located.** `Seeed-Projects/reBot-DevArm` is a CAD repository —
STEP files, BOMs, assembly steps, no Python. The B601-RS control API is
elsewhere: `vectorBH6/reBotArm_control_py` (RobStride motors for -RS, Damiao
for -DM; `RebotArm.connect/enable_all/get_state/estop`, `JointGroup.send_pos_vel`,
Pinocchio FK/IK), plus Seeed's Motorbridge Python SDK and the LeRobot
integration wiki. Recorded in `docs/reference_material.md`.

117 new tests (115 → 231, 1 skipped).

### Day-2 gate: NOT MET

| Requirement | State |
|---|---|
| Twenty consecutive low-speed motions, no fault, collision or manual correction | Not attempted — no hardware |
| `B601Driver` against the vendor SDK | Not written; API now identified |
| Wiring, zero position, motor IDs, CAN comms, gripper direction | Not done |
| Measured workspace/velocity limits replacing the placeholders | `limits.yaml` still PROVISIONAL |
| `home.tolerance_m` set from measured repeatability | Still a placeholder |
| `lerobot` / torch / vendor SDK pins frozen; `pin_check.sh --record` | Not run; no `pins.env` |
| Bring-up report, CAN/e-stop/unexpected-motion recovery checklist | Absent |
| Five-pose repeatability log, evidence video | Harness exists; no data |
| Mentor sign-off | Unevidenced |

### Day 2 addendum — kinematics, the real driver, and the codebase pin

**FK cross-check first, deliberately.** Before writing anything that depends
on kinematics, `b601/bringup/kinematics_check.py` solves the same joint
vectors with placo (what LeRobot's `RobotKinematics` wraps) and with Pinocchio
(what the vendor examples use), over the vendor URDF `00-arm-rs_asm-v3`, frame
`gripper_end`. **Max disagreement 0.000000000 m over 200 joint vectors.** That
validates frame name, joint ordering and units. It does not validate the URDF
— both read the same file — and the entry in the risk log says so.

It earned its keep immediately:

| Found | Consequence |
|---|---|
| **FK(zero joints) = (0.30171, 0.0, 0.217747) m** | The scaffold's invented home `(0.30, 0.00, 0.35)` is **0.1323 m** away, against a 0.02 m arrival radius. `safe_home` would have faulted on **every successful home** the first time it ran on hardware. `limits.yaml` now carries the FK-derived pose, still marked pending measurement |
| placo resolves mesh paths against the URDF **file**, the vendor ships it one level below `meshes/` | The vendor URDF fails to load in placo as shipped. `staged_urdf()` stages a copy beside the meshes rather than editing vendor files. Pinocchio is unaffected — it builds the model without meshes |

**`b601/driver/b601.py`** wraps `SeeedB601RSFollower` **unmodified** (option D
of the four evaluated — adapter targeting our `Driver`, not a fork of the
plugin and not loose scripts). Kinematics on our side via `RobotKinematics`,
injected so the suite needs neither placo, a URDF, nor CAN. One unit boundary:
degrees at the vendor edge, radians and metres inside. Three plugin behaviours
are contained rather than inherited — `safe_zero`'s KeyboardInterrupt-on-
success, `disconnect()` moving the arm, and `send_action()` clipping where we
reject. All three are in `docs/reference_material.md` with the source reading.

**`LEROBOT_ORIGIN` is now a gated pin.** The vendor installs a fork and warns
against upstream; both report the same `__version__`, and an editable clone
does not move it at all. The probe records `git+<url>@<commit>`,
`editable+git:<commit>`, `local+git:<commit>` or `pypi:<name>:<version>`, and
**refuses to record a dirty working tree** — a tree recorded dirty and
verified dirty compares equal while its contents differ. Checked before the
version, since the version is meaningless without it.

Impact if it had gone unfixed: not safety, but attribution. Episodes recorded
under an unidentified lerobot cannot be compared afterwards, and teleop
episodes are irreplaceable. That is why it lands now rather than before
evaluation.

40 new tests (231 → 271, 2 skipped — the `--record` end-to-end and the real-
URDF FK check, both environment-dependent).

**Still not started:** CAN bring-up, measured limits, the twenty-motion run,
the motor-order confirmation, mentor sign-off. The Day-2 gate is unchanged.

### Day 2 addendum 2 — verifying the adapter against the real library

`from_urdf()` had been written against an API read from documentation rather
than source. Shimming the real `lerobot.model.kinematics` over the vendor URDF
found three defects in it and one in the library's usage contract:

| Defect | Effect |
|---|---|
| `joint_names` not passed | `RobotKinematics` defaults to `robot.joint_names()` — eight joints for this URDF, including the two prismatic gripper fingers — then indexes a six-element vector out of range |
| URDF passed unstaged | It constructs `placo.RobotWrapper` directly, so it inherits the mesh-resolution failure; construction raised |
| `orientation_weight` left at its 0.01 default | IK also chases a target *orientation*. `move_to` carries none, so identity rotation was being imposed as a silent goal |
| **One `inverse_kinematics()` call is not a solution** | placo's frame task is soft and the library solves once. Measured: up to **0.101 m** residual on a reachable target, converging to zero in three or four iterations |

The last one is the serious one. `SafeDriver` validates the *requested*
Cartesian pose; sending an unverified joint solution would have put the arm up
to 10 cm from the point the chokepoint approved — the guard checking one
place while the arm goes to another. `move_to` now iterates and verifies the
solution with FK, refusing to send anything outside `ik_tolerance_m`. That
same check is the reachability test: an unreachable target never converges and
is rejected rather than approximated, which is Rule 1 one layer down.

Verified against the real solver: targets converge to under 0.1 mm, and
`(2.0, 0.0, 0.3)` is refused with a 1.98 m residual.

6 new tests (271 → 277). **New open risk: the URDF is unpinned** — every
guarded pose is FK over it, and nothing detects it changing.

### Day 2 addendum 3 — a third pin regime: the model

`pin_check.sh` gated software and physical state. Neither covered the thing
that now produces every checked pose. Four pins added, verified against the
vendor URDF:

| Pin | What it catches |
|---|---|
| `URDF_SHA256` | A re-exported or edited kinematic model. Measured on `00-arm-rs_asm-v3`: `2012b5aa3b58…`. The URDF is not in this repository, so the hash is the only thing that notices |
| `URDF_EE_FRAME` | Solving for a different frame. Read from `b601.driver.b601.URDF_EE_FRAME` rather than typed a second time — a pin that can drift from the value in use is not a pin |
| `PLACO_ORIGIN` | The solver that computes `eef_pose()`. `pypi:placo:0.9.23` here; not a default dependency, and safety-relevant the moment FK feeds the workspace guard |
| `SEEED_B601_ORIGIN` | A forked or re-released B601 plugin |

The origin probe is now generic (`distribution-origin <name>`), so one
implementation covers lerobot, placo and the plugin, including the fork case:
a published wheel and a git fork of it at the same version produce different
pins.

The regimes read: **software** (interpreter, lerobot codebase and version,
solver libraries) → **model** (URDF hash, end-effector frame) → **physical**
(camera serials, calibration hash). Checked in that order, because each later
value is only meaningful under the earlier ones.

14 new tests (277 → 291).

## Day 3 — review checkpoint, no code changed (2026-08-03)

A review of plan-versus-progress rather than a work day. Recorded because the
conclusion is about allocation, and allocation decisions are the kind that
look obvious in hindsight and invisible at the time.

**Verified state at `44aa501`:** 291 tests passing, 2 skipped, clean tree, in
sync with `garyd/main`.

**Assessment: the method is right; the allocation is no longer.**

What is working: safety before capability, everything exercisable unpowered,
measured sim findings driving design decisions, and gates recorded as NOT
EVIDENCED rather than assumed. The review waves earned their cost — latching
gaps, NaN and negative speeds, joint-state cardinality, a 0.101 m IK residual
and a 0.1323 m home-pose error would each have surfaced first on powered
hardware.

What is not: the effort is concentrated in one layer, and that layer is done
until the arm can answer its remaining questions.

| Package | Plan day | Lines |
|---|---|---|
| `b601/safety` + `b601/driver` | 1–2 | 291 tests |
| `b601/cameras` | 3 | **0** |
| `b601/primitives` | 4 | **0** |
| `b601/policy` | 11–14 | **0** |
| `b601/planner` | 15–17 | **0** |

Two risks logged today: the critical path is hardware and has not started, and
effort concentrates where tests are easiest to write. A third records the
parallel-agent merge that reconciled overlapping safety code by hand.

**Recommended order:** record the Day-1 mentor gate; power on, starting with
the torque-off hand-driven reads (motor order, gripper travel — no commanded
motion, and they close the most dangerous assumption in the codebase); stop
hardening the safety layer; use waiting time on the Day-3 camera config and
sync checker and the Day-4 primitive interfaces, both mock-testable and both
on the Week-1 gate; close the `agentview` camera-naming decision before any
recording, since dataset keys are fixed at record time.

**Note for anyone quoting a test count:** an earlier recap circulated citing
194 tests at merge `736d30f`. That predates the FK cross-check, the B601
driver adapter, the IK convergence fix and the model pin regime. The current
figure is 291.

## Day 3 — cameras: manifest, sync checker, and a wrong model caught (2026-08-06)

First day with hardware powered. The arm was brought up, calibrated and
teleoperated by the operator before this work started; what landed here is the
camera half of Day 3.

**Environment note that changes the picture.** The robot-facing environment is
the conda env `lerobot` (`/home/demo/miniforge3/envs/lerobot`), not the repo
`.venv`. The **`sm_120` gate PASSES there** — torch 2.7.1+cu128, arch list
includes `sm_120`/`compute_120`, and a real CUDA kernel executes — so the
platform condition in `protocol_deviations.md` is **met and the A6000 can be
released**. The same gate FAILS in `.venv`, whose torch is a cu126 build
topping out at `sm_90`. Two consequences are open, both logged as risks:
`pin_check.sh` hardcodes `.venv/bin/python` and so cannot pin the environment
that drives the arm, and **`placo`/`pinocchio` are absent from the conda env**,
which leaves every Cartesian guard inert there.

**URDF located and hashed.** `2012b5aa3b58…`, matching the value recorded on
Day 2 — the same kinematic model the earlier FK and home-pose work was measured
against. Staged as a machine-local symlink; `b601/setup/urdf/` is now gitignored
on the established rule that the bytes stay out and the hash is committed.

**Camera manifest is now data** (`b601/setup/cameras.json` +
`b601/cameras/config.py`). `probe.camera_serials` had gated CAMERA_SERIALS since
Day 0 while reading exactly one field per entry; model, mount, resolution, frame
rate, pixel format and exposure were documentation. The loader validates all of
them and refuses a manifest whose cameras disagree on frame rate.

Hardware, measured rather than assumed:

| Camera | Role | Serial | Negotiated |
|---|---|---|---|
| Intel RealSense D405 | `eye_in_hand`, wrist | `353322271941` | 640x480 rgb8 @30, **USB 2.1** |
| Microdia DSJ-2062-309 | `agentview`, fixed top | `DSJ-250318-J` | 640x480 MJPG @30 |

640x480@30 is the only resolution/rate **both** cameras can reach on their
current links: the top camera has no 15 fps MJPG mode at all, and the D405 is on
a 480 Mbps link, which fits colour but not colour plus depth. Colour only is not
a compromise here — ACT consumes RGB and the plan permits an image-space staging
fallback.

**The sync checker's first model was wrong, and the hardware proved it.**
`b601/cameras/sync.py` ran against a real 150-frame capture from both cameras:

| Stream | Mean interval | Jitter p95 | Jitter max | Dropped |
|---|---|---|---|---|
| `agentview` | 33.02 ms | 3.12 ms | 27.31 ms | 0 |
| `eye_in_hand` | 33.30 ms | 0.22 ms | 0.42 ms | 0 |

Both within a whisker of 30 fps, both clean — and the checker **failed them**,
reporting a 76 ms cross-camera offset. Three defects, all in the checker:

| Defect | Why it was wrong |
|---|---|
| Paired frame **index** against frame index | The two streams differ by 0.28 ms/frame in rate, so index-paired offset accumulates without bound (76 ms at 150 frames, more in a longer episode). Two USB cameras with no hardware sync always drift. A long episode would have failed however good the cameras were |
| Bounded jitter on its **max** | The 27.31 ms came entirely from the first two intervals (6.0 and 13.6 ms) — buffered frames flushing at stream start, which every V4L2 capture does. Steady state was 3.12 ms |
| Paired frames outside the **common window** | Equal frame counts at unequal rates leave the slower stream running past the other's last frame. Those frames have no counterpart because capture stopped, not because the cameras disagreed; they reported a 69.8 ms max gap on a healthy recording |

Corrected: pair by **nearest timestamp**, which is how a recorder assembles an
observation; bound jitter on p95; exclude and **count** frames outside the common
window. The same recording then reads 9.04 ms p95 pairing gap — 0.27 of a frame
period — and passes. The index offset and drift rate are still reported, as
diagnostics, because they are what say a frame-index recorder would be wrong.

**Requirement this produces for the recording pipeline: pair frames by
timestamp, never by frame index.** That is not a preference; at 0.28 ms/frame
the two streams are more than a frame apart by index within 120 frames.

Also found, and not yet fixed: **both cameras are running auto exposure**, and
the top camera is also running auto white balance. The manifest records fixed
values and the capture probe proved they can be applied, but nothing in a
recording path applies them yet.

78 new tests (291 → 369, 2 skipped).

### Day-3 gate: NOT MET

| Requirement | State |
|---|---|
| Camera manifest with serials, mounts, modes, fixed exposure | **Landed and validated**, exposure for the wrist still a placeholder |
| Timestamp-sync checker | **Landed**, and corrected against real capture |
| Calibration: camera-to-robot transform or documented image-space fallback | Not started |
| **Measured** reprojection/position error at known table points | Absent — `calibration_report.md` still a template |
| Landmark stability across a restart | Not tested |
| `CALIBRATION_SHA256` / `CAMERA_SERIALS` recorded via `pin_check.sh --record` | Blocked: `--record` is all-or-nothing and needs the calibration file |
| Fixed exposure and white balance actually applied in the capture path | **Not done** |

## Day 4–5 — 2026-08-08: first episodes, Day-5 gate MET, training pipeline proven

The 0-frame D405 was root-caused (two stacked defects: the vendor null-frame
bug, fixed as `3b4f877` and re-pinned, and the one-session-per-reset firmware
behaviour, worked around by `b601.cameras.reset` in the session script — see
risk_log). Wrist exposure measured under workspace lighting (8000 µs /
gain 248) after episode 0 recorded a near-black wrist stream on the
placeholder. The drift gate caught two real events (a 26 px camera bump; a
cable drooped over a marker) and one wrong metric of its own — check-time
stability now votes over a burst (`observed_landmarks`) instead of demanding
perfect attendance, for the same reason sync jitter uses p95. Workspace
rebuilt by the operator: four dark corner tags, occlusion zones cleared.

**`local/b601_pilot`: 12 episodes, 7031 frames.** Replay verdicts by the
operator watching the arm: **12 of 12 correct.**

### Day-5 gate: MET (threshold ≥9 of 10)

**ACT training pipeline smoke test PASSED** on episodes 1–11 (episode 0 is
training-quarantined): 52M-param ACT, 1000 steps on the RTX 5090, loss
9.80 → 1.87 monotone, 74 ms/update with 4–13 ms data loading (AV1 decode
keeps up), checkpoint + optimizer state saved and verified on disk
(`artifacts/act_smoke_2026-08-08`). The policy is junk by design; the
pipeline is the deliverable. Days 11–14 training has no untested toolchain
left.

Before scaled collection (Days 6–10): staging method + block-scatter region
(one decision, see HANDOVER), off-machine backup, and the Day-1 mentor gate
paperwork. 495 tests, 2 skipped.

---

## Days 6–18 — consolidated entry (written 2026-08-24, reconstructed)

**Why this entry is retrospective.** Per-day entries stopped after Day 5
(2026-08-08) while work continued to 2026-08-23. The authority for this period
is `experiment_registry.md` (current) and the commit record, both of which were
kept; this entry consolidates them so the progress log stops lying by omission.
Anything below is traceable to a registry row or a commit. It is not a
substitute for the per-day discipline — that resumes with the next session.

### Days 6–10 — collection (2026-08-10 → 08-12)

`local/b601_train`: **168 certified episodes, 96,058 frames, zero held-out
leakage**, snapshot `b601_train_final168_20260812`. Target was 150.

Collection was not clean, and the audit trail is the deliverable as much as the
corpus is:

| Session | Finding | Disposition |
|---|---|---|
| 2 | reset-inside-recording | 4 quarantined, 6 kept |
| — | gripper-failure session | 4 removed, 1 success kept |
| 4 | frame-level trims | 8 of 27 salvaged |
| 5 | trim pipeline routine | corpus at 64 |
| 6 | boundary shift, framed as input-path | corpus at 73; framing later contradicted by operator observation |
| — | **orphan rows: every index table desynced since session 2** | root-caused; 66 episodes revalidated on a corrected map |
| — | merge damaged `file-008` (episodes 46, 48–50) | excluded; v1 trained on 164 of 168 |

Two vendor patches logged in this window (blocking record announcement;
frame-index clamp), each re-pinned. **Staging method decided: image-space**,
with rationale and foreclosures recorded in `calibration_report.md` — there is
no metric camera-to-robot calibration, by decision rather than omission.

### Days 11–12 — training (2026-08-12)

ACT 52M, 100k steps, batch 8, lr 1e-5 on the RTX 5090. **Loss 4.60 → 0.062
monotone** over 8.5 epochs, grad norm 114 → 4.4, ~70 ms/update. Five
checkpoints, 2.9 GB, backed up to the NVMe. `artifacts/act_b601_v1_20260812`.

### Days 13–14 — evaluation, and two hard results (2026-08-13 → 08-14)

**SAFETY EVENT (2026-08-14): a stall broke the arm.** Root cause: *the safety
layer was absent from the eval path*. The chokepoint that the entire Day-0
design was built around was not in the loop that ran the policy. Fixes landed
the same day: per-tick motion clamp in the eval path, per-joint clamp derived
from the demonstrated envelope, command-stream rate limits, and the
safety-event mechanism itself corrected. Fifth vendor patch logged.

This is the single most important finding of the period and it is not a
software defect in isolation — it is the failure mode the sim track named as
"a guard that cannot see the failure it guards", reappearing physically.

One evaluation was **voided** before that (2026-08-13): a photometric shift,
not policy failure. Voided rather than reported.

**Day-14 gate: FAILED.**

| Condition | Result |
|---|---|
| Held-out zone | **0/10** |
| In-distribution controls | **3/5 (60% one-shot)** |

The primitive works where it was demonstrated and does not generalise to the
untrained zone — **the exact profile the harness thesis presupposes**. The
checkpoint was therefore frozen *as an imperfect primitive*, and Day 18
proceeds against the +15 pp-over-one-shot bar. This is a stronger test than the
plan anticipated, which assumed a ≥70% primitive.

### Days 15–18 — the harness, and four live shakedowns (2026-08-15 → 08-23)

Built: loop state machine (every branch tested unpowered), live I/O wiring,
**grasp verifier calibrated at 416/417 holds**, staging table (block pixel →
pre-grasp pose, fail-closed, LOO p90 under 6°; v4 after v3 read the gripper
convention backwards).

Four shakedowns on the real arm, each producing a mechanism rather than a score:

| # | Result | Finding |
|---|---|---|
| 1 | 2/4 train, 0/1 held-out | **Operator-in-frame makes the policy RETREAT.** Proven by occlusion probes: swapping a 107×120 px patch flips RETREAT↔CONTINUE. Training tails contain the operator reaching in post-place, so person-in-frame = episode over = go home |
| 2 | 2/3 train, 0/1 held-out | Out-of-frame rule **worked**: 5/7 policy segments continue from the staged pose, against 0/7 before. **First live firing of the verify → place-recovery branch.** Residual failure is grasp precision |
| 3 | 0/3 | Closed fingers **plowed the cube** — open-loop approach plus lagging gripper, and half the demonstrated p99.9 envelope still reads as very fast. Fixes: open gripper first (closed-loop, state ≥ 240), quarter-speed staging |
| 4 | 0/3 | Plowing gone. Diagnosis moved up a level: **no open-loop table can stage accurately where no demonstration went.** But the block was in the wrist view at stage-end in 9 of 9 attempts |

**Conclusion driving current work:** close the loop. A servo phase after every
stage drives the block's wrist-frame centroid to the demonstrated pre-grasp
target (median (360,404), n=84) using measured pan (−12.8 px/deg). Landed
2026-08-23; not yet tried on hardware.

### State at the end of this period

566 tests, 2 skipped. Zero open risks (7 monitoring, 2 mitigated). Datasets:
`b601_train` 7.6 G, `eval_b601_v1` 3.1 G, `b601_pilot` 584 M. Trial footage:
`outputs/harness_trials`, 40 videos, 3.8 G, **untracked and unmanifested**.

## Shakedown 5 — 2026-08-24: the servo under-acted, and the thesis met a boundary

3 held-out trials, 9 attempts. Servo traces plus servo-end and close frames
extracted for all 9.

### Result: 0/3

| Defect | Measurement |
|---|---|
| Reach axis under-acted | Spent its 12° budget in 12 ticks (1°/tick against large y-errors) then exited. **6 of 8 servo phases ended at ~12 ticks having moved pan only 3° against 50–100 px errors** |
| Shallow-stage oscillation | 2 servos flipped pan direction 4–5 times — the jerkiness the operator saw. Gain × lag overshoot |
| Servo skipped | 1 attempt: block not in wrist view at stage-end |
| Outcome | Servo-end frames show the cube still off-centre in **9 of 9** |

The servo is fixable. That is not the finding.

### THE STRATEGIC FINDING — sessions 2 through 5

**~15 held-out policy grasp attempts. Zero grasps.** Including attempts that
ended **7–10 px from demonstrated coverage** after the cube was shoved to the
coverage edge — that is, attempts whose delivery was demonstrably good.

The frozen policy's final 5 cm is wrong in this region **regardless of delivery
quality**. Staging and retries *multiply* a per-attempt grasp probability, and
that probability is approximately zero here. Multiplying zero returns zero for
any number of attempts.

This bounds the harness thesis rather than refuting it. "An agent harness makes
an imperfect primitive more reliable" holds where the primitive retains
non-zero competence. Where competence has collapsed, the harness has to
**complete** the task, not re-attempt it. Four shakedowns removed four delivery
mechanisms; the fifth showed delivery was never the binding constraint in this
region.

It is worth recording that this is a more informative outcome than a successful
rescue would have been, and that it was only visible because held-out trials
were run separately from in-distribution ones and counted separately.

### Decision point — recorded for the owner, NOT taken

| Option | What it is | Consequence |
|---|---|---|
| **A — harness recovery grasp** | After a verified policy failure: servo-centre (fixed), descend a measured depth, close to the measured hold band, lift, verify. All quantities measured; every part already proven live — the symmetric place-recovery branch works | **Changes the claim** to "the harness completes what the primitive cannot", policy still invoked first. The only option that can still produce a positive Day-18 result |
| **B — run Day-18 as-is** | Report the negative result with the full causal chain | Defensible and cheap. The chain is strong: five sessions, each with a measured mechanism |
| **C — tune the servo, re-shakedown** | Weakest | Coverage-edge attempts failed too, so delivery quality is not what is binding |

**Day 18 cannot be scheduled until this is chosen** — A and B are different
experiments, and as currently designed the comparison would measure 0 against 0.

### Registry note

This entry was added 2026-08-25. Sessions 1–4 and this one are recorded in
`experiment_registry.md` as they happened; the progress log lagged again, which
is the same drift that put it 16 days behind in August. The registry is the
authority for trial results; this log is the narrative.
