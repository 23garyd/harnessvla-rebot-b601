# Calibration report — B601 cameras

**Status: method chosen and tooling built; reference not yet captured.**
Blocked on one physical step — ArUco markers placed in view (see below).

## The method, and why

The plan permits either a camera-to-robot transform or a documented
image-space fallback, and requires recording which and why. **Chosen for now:
a landmark drift reference, which is neither, and deliberately less.**

`b601/cameras/reference.py` records the pixel positions of fixed ArUco markers
once, and compares them at the start of every session. It yields no intrinsics
and no camera-to-robot transform. It detects only that a mount MOVED.

Why that is the right thing first:

- **ACT training does not need calibration.** The policy learns pixels →
  actions end-to-end; nothing in the LeRobot pipeline reads intrinsics or a
  transform. What training needs is CONSISTENCY — mounts that do not move,
  fixed exposure, identical modes — and a calibrated camera that gets nudged
  mid-collection is worse than an uncalibrated one that stays put.
- **The failure that actually costs episodes is drift, not inaccuracy.** Sim
  finding 3: a stale reference produced +0.078–0.082 m release errors and
  inverted the strongest cell in the matrix, invisibly, because it biased
  estimator selection rather than entering an action. The physical analogue is
  a nudged mount, and this check is aimed squarely at it.
- **It unblocks the pin regime.** `pin_check.sh --record` probes
  `calibration.json` and is all-or-nothing, so no pins at all could be recorded
  until something filled that slot. This artifact fills it honestly.

## What this defers, and when that comes due

A metric transform is needed the moment the planner turns a perceived object
location into a staging pose, because `SafeDriver.move_to` takes metres in the
base frame. That is **Days 15–18 (harness)**, not Days 6–14 (collection and
training).

**Decide before recording episodes**, because the board must be attached and
hand-eye poses captured while the workspace is set up: either commit to the
metric transform (`cv2.calibrateHandEye`, eye-to-hand, poses driven by
TELEOPERATION so no autonomous Cartesian motion is required and the powered
motion blockers do not apply), or commit to image-space staging and record that
choice here with its reasoning.

Useful asset either way: **the D405 is factory calibrated.** Colour intrinsics
at 640x480, read from librealsense 2026-08-06:

    fx=392.844  fy=392.373  ppx=322.751  ppy=237.971
    model=inverse_brown_conrady
    coeffs=[-0.051142, 0.062666, -0.000417, 0.001075, -0.021773]

So only `agentview` (a Microdia webcam, no factory data) would need intrinsic
calibration, and only if the metric route is taken.

## Required content — status

| Required | State |
|---|---|
| Camera manifest: serial, model, mount, resolution, fps, fixed exposure | **Done** — `b601/setup/cameras.json`, validated on load, plus format, backend and gain |
| Method recorded, with reasoning | **Done** — this section |
| **Measured** error at known table points, as a number with units | **Not done.** Requires the metric route; the drift check reports pixels, not millimetres |
| Restart procedure, evidence landmarks are stable across a restart | **Tooling done**, evidence not captured — needs markers placed |
| Mount photographs | **Not done** |
| SHA256 matching `CALIBRATION_SHA256` | Blocked on capturing the reference |

## To capture the reference

1. Place at least three or four `DICT_4X4_50` ArUco markers in `agentview`'s
   view. **Fix them to the same structure the workspace is fixed to**, and put
   them outside the area objects move through — the check cannot distinguish a
   moved camera from a moved marker, and objects move every episode by design.
   The printed board at `artifacts/day3/charuco_7x5_25mm.png` carries usable
   markers if a dedicated set is not to hand.
2. With the cameras in their **final mounted position**:
   `python -m b601.cameras.reference --record`
3. Thereafter, at the start of every session:
   `python -m b601.cameras.reference` — exit 0 clean, 1 if a mount moved.
4. Re-recording redefines "not drifted": it is a registry event and
   `CALIBRATION_SHA256` must be re-recorded with it.

`eye_in_hand` will report **NOT CHECKED**. That is correct and not a gap to
paper over: a wrist camera's landmarks move with the arm, so a reference for it
only means anything at a repeatable arm pose, which does not exist until
`safe_home` is trusted. It is reported explicitly so absence of a failure is
never read as evidence of no drift.

## Why this is gating

A systematic perception bias is indistinguishable from policy error at
evaluation time. In the simulation track a stale reference coordinate produced
release errors of +0.078–0.082 m and inverted a cell that was otherwise the
strongest in the matrix. The physical analogue is a nudged mount, and it is
silent unless something is pinned and checked.
