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

`b601/driver/b601.py` will adapt this to the `Driver` interface. Two mappings
are not one-to-one and need deciding on hardware, not on paper: `eef_pose()`
needs Pinocchio FK over the URDF, and `move_to(xyz, speed)` needs IK plus a
bounded joint trajectory — the vendor API is joint-space (`send_pos_vel`),
while `Driver` is Cartesian.

## Simulation track

`docs/sim_findings_that_transfer.md` in this repo distils the measured results
that constrain design decisions here. Read it before Day 16 (verification) and
Day 17 (memory) — several of its findings are the difference between a design
that works and one that reproduces a known failure.

Full record: `github.com/23garyd/harnessvla-sim-reproduction`, in particular
`track/registry/` (experiment registry, risk log, per-day progress with result
tables) and `track/report/reproduction_report.md`.
