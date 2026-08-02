# Reference material

## RPent (the released HarnessVLA harness)

**Not vendored here.** It is an 11 MB pinned upstream clone that the B601
track reads for architecture, and runs nothing from. The simulation repo holds
it at the pin used for the reproduction:

    repo:   github.com/23garyd/harnessvla-sim-reproduction
    path:   RPent/
    pin:    6e4ba1805a459d74ad53569e833bae7ae2c59985

What the B601 plan asks you to read (Day 1):
- `RPent/robots/libero/` — the reference implementation of the harness loop
- `RPent/docs/` — architecture notes and diagram
- the HarnessVLA paper, arXiv:2607.08448

### The two files worth studying closely

`RPent/robots/libero/prompts/system.py` — how the planner is told to observe,
consult memory, and record what it read. Note it names the camera views
directly (`agentview`, wrist) ~75 times: the prompt is part of the camera
contract, not just the code.

`RPent/robots/libero/tools.py` — the primitive surface, and how a **scene +
wrist** camera pair is handled: separate RGB, metric depth, and depth→world
XYZ maps per camera, plus high-res variants. That two-camera structure maps
1:1 onto a D435-fixed + D405-wrist setup, which is why that hardware choice is
architecturally cheap here.

## Vendor SDK for the B601-RS

`github.com/Seeed-Projects/reBot-DevArm` is the **hardware** repository — STEP
files, BOMs, assembly steps, community gallery. There is no Python in it. The
control software is in other places:

- `github.com/vectorBH6/reBotArm_control_py` — the Python control library, and
  the one that matters here. `RebotArm(hw_yaml)` with `connect`, `set_zero`,
  `enable_all` / `disable_all`, `get_state` / `get_positions` /
  `get_velocities` / `get_torques`, `estop`, `disconnect`; joint groups
  (`arm`, `gripper`) exposing `mode_pos_vel` / `send_pos_vel`, `mode_mit` /
  `send_mit`, `mode_vel` / `send_vel`; Pinocchio forward/inverse kinematics
  under `kinematics/`. Requires Python 3.10+, Ubuntu 22.04+, and a USB2CAN
  bridge or CAN interface.
- Seeed Motorbridge Python SDK (`motorbridge.seeedstudio.com`) — motor-level
  read/write. **The -RS uses RobStride motors**; the -DM uses Damiao. Guides
  written for one model do not transfer to the other at this layer.
- LeRobot integration: `wiki.seeedstudio.com/rebot_arm_b601_rs_lerobot/`
- ROS2 integration: `wiki.seeedstudio.com/rebot_arm_b601_rs_ros2_integration/`

### The integration actually used: the LeRobot plugin

`b601/driver/b601.py` wraps `SeeedB601RSFollower` from
`lerobot-robot-seeed-b601` (PyPI 1.0.0, pure-python wheel; `lerobot>=0.4`,
`python-can`, `motorbridge`), **unmodified** — no fork. Kinematics live on our
side via `lerobot.model.kinematics.RobotKinematics` (placo).

Plugin surface: `connect(calibrate=True)`, `get_observation()`,
`send_action(action)`, `disconnect()`, `is_connected`, `calibrate()`,
`disable_torque()`, `safe_zero()`. Observations and actions are **flat keys in
degrees** — `{motor}.pos` / `.vel` / `.torque` — over
`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_yaw, wrist_roll,
gripper`, plus one key per camera. There is no Cartesian anything: a grep of
the plugin for `kinemat|pinocchio|urdf|cartesian|eef` returns nothing.

**Three behaviours read from its source, each contained in `b601/driver/b601.py`:**

| Behaviour | Why it matters here |
|---|---|
| `safe_zero(exit_on_complete=True)` raises `KeyboardInterrupt` **on success** — and True is the default | `SafeDriver` latches on `BaseException`, so the default turns every successful home into a latched fault. We always pass `False` |
| `disconnect()` calls `safe_zero()` | Disconnecting **moves the arm**. `disable()` maps to `disable_torque()`, never disconnect — the operation you reach for when something is wrong must not command motion |
| `send_action()` clips to the plugin's own `joint_limits` / `max_relative_target` and logs at `debug` | This repository rejects rather than clamps. Keep the plugin's limits **wider** than `limits.yaml` so ours bind first; then a clip below us is a bug, not a backstop. Open until the limits are measured |

Overheat (>100 °C) also raises `KeyboardInterrupt` from `send_action`. The
`BaseException` latch handles it; a plain `except Exception` would not.

### Kinematics: URDF, frame, and what is verified

From the vendor's `config/rebotarm_rs.yaml`:

    urdf_path:           urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf
    end_effector_frame:  gripper_end
    arm joints:          joint1 .. joint6   (+ prismatic joint_left/joint_right)

`b601/bringup/kinematics_check.py` cross-checks placo against Pinocchio over
the same URDF. Result on `00-arm-rs_asm-v3`: **max disagreement 0.000000000 m
over 200 joint vectors.** That validates the frame name, joint ordering and
units — not the URDF, since both solvers read the same file. Day-3 calibration
is what validates FK against the arm.

Two things it turned up:

- **FK(zero joints) = (0.30171, 0.0, 0.217747) m.** The scaffold's invented
  home of `(0.30, 0.00, 0.35)` is **0.1323 m** away, so `safe_home` would have
  faulted on every successful home. `limits.yaml` now carries the FK-derived
  value, still pending measurement.
- **placo resolves `filename="meshes/..."` against the URDF FILE's directory**,
  but the vendor ships the URDF one level below the meshes. Loading it in
  place fails with `Mesh meshes/base_link.STL could not be found`. Pinocchio
  builds the kinematic model without meshes and does not care.
  `staged_urdf()` stages a copy beside the meshes rather than editing the
  vendor file.

**`RobotKinematics` has three non-obvious requirements**, each found by running
it rather than reading it:

- **`joint_names` must be passed.** Left to its default it takes
  `robot.joint_names()`, which for this URDF is *eight* joints — `joint1..6`
  plus the two prismatic gripper fingers — and then indexes a six-element
  command vector out of range.
- **It constructs `placo.RobotWrapper(urdf_path)` directly**, so it inherits
  the mesh-resolution problem above. The URDF must be staged beside its meshes.
- **`orientation_weight` defaults to 0.01**, i.e. IK also tries to reach a
  target *orientation*. `Driver.move_to` carries no orientation, so the
  identity rotation would be imposed as a silent goal. We pass 0.0.

**One `inverse_kinematics()` call is not a solution.** placo's frame task is
soft and the library solves once. Measured on this URDF, over reachable
targets:

| target | residual after 1 call | 2 | 3 | 4 |
|---|---|---|---|---|
| (0.32, 0.02, 0.25) | 0.002793 m | 0.000023 | 0.0 | 0.0 |
| (0.30, 0.00, 0.30) | **0.101328 m** | 0.014051 | 0.000732 | 0.000001 |
| (0.35, −0.05, 0.22) | **0.108301 m** | 0.010838 | 0.000720 | 0.000001 |

Ten centimetres. `SafeDriver` validates the *requested* Cartesian pose, so an
unverified solution would send the arm somewhere the chokepoint never
approved. `B601Driver.move_to` therefore iterates and verifies with FK,
refusing to send anything whose achieved pose is outside `ik_tolerance_m` —
which doubles as the reachability check, since an unreachable target simply
never converges.

**The unverified assumption:** that the plugin's motor order corresponds to
`joint1..joint6`. Nothing enforces it, and a wrong order gives poses that look
plausible and are wrong everywhere except home. Confirm joint-by-joint on Day 2.

## Simulation track

`docs/sim_findings_that_transfer.md` in this repo distils the measured results
that constrain design decisions here. Read it before Day 16 (verification) and
Day 17 (memory) — several of its findings are the difference between a design
that works and one that reproduces a known failure.

Full record: `github.com/23garyd/harnessvla-sim-reproduction`, in particular
`track/registry/` (experiment registry, risk log, per-day progress with result
tables) and `track/report/reproduction_report.md`.
