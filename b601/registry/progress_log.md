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
