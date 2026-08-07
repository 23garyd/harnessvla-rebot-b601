# Calibration report — B601 cameras

**Status: drift reference CAPTURED and verifying. No metric calibration.**

Measured 2026-08-06, `agentview`, immediately after recording:
**median landmark displacement 0.03–0.05 px, max 0.1 px** against a 3.00 px
tolerance. That is the repeatability floor of the method on this scene, not a
drift measurement — but it means the tolerance has roughly 30x headroom over
detection noise, so a real mount movement will stand out clearly.

`CALIBRATION_SHA256=0c26d532b47c…` is recorded in `pins.env` and verifies.

## The method, and why

The plan permits either a camera-to-robot transform or a documented
image-space fallback, and requires recording which and why. **Chosen for now:
a landmark drift reference, which is neither, and deliberately less.**

`b601/cameras/reference.py` records landmark positions once and compares them
at the start of every session. It yields no intrinsics and no camera-to-robot
transform. It detects only that a mount MOVED.

**No markers were needed.** The workspace was measured first: 1512 ORB features
in the frame periphery, 609 of them strong. So the method used is
`orb_homography` — features matched against a stored reference image, RANSAC
homography, and the displacement of a fixed 9-point probe grid under that
homography IS the drift. RANSAC is what makes it usable without markers: a
cable or tool moved in the periphery produces outlier matches, and only a
coherent shift across many features moves the estimate. The ArUco path remains
implemented and is selected automatically if markers are ever placed.

The reference IMAGE is what features match against, so its SHA256 is recorded
inside `calibration.json` — which `CALIBRATION_SHA256` pins in turn. Swapping
the image under a pinned artifact would otherwise silently redefine "not
drifted"; the check verifies that hash before comparing.

`eye_in_hand` is deliberately NOT referenced: only fixed mounts are. A wrist
camera's view moves with the arm, so a reference would measure the arm rather
than the mount. It reports NOT CHECKED every run.

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
| Restart procedure, evidence landmarks are stable across a restart | **Partly done.** The check round-trips at 0.03–0.05 px median across a full camera open/close cycle. Not yet evidenced across a machine REBOOT, which is the case that matters most and is worth one run to confirm |
| Mount photographs | **Not done** |
| SHA256 matching `CALIBRATION_SHA256` | **Done** — `0c26d532b47c…`, recorded and verifying |

## Operating it

At the start of every session — or just run `b601.cameras.preflight`, which
includes this:

    python -m b601.cameras.reference        # exit 0 clean, 1 if a mount moved

Re-record ONLY when the cameras have deliberately moved, or the workspace
periphery has been rearranged enough that matching fails:

    python -m b601.cameras.reference --record

**Re-recording redefines "not drifted".** It is a registry event, and
`CALIBRATION_SHA256` must be re-recorded with `pin_check.sh --record`
afterwards or the gate will fail — correctly.

THE STANDING CAVEAT for the marker-free method: the reference is the scene's
own texture, so rearranging the periphery (moving a cable, a tool, a monitor)
degrades matching and eventually reads as drift. RANSAC absorbs a few such
changes; it will not absorb a redecoration. If the check starts failing and the
cameras demonstrably have not moved, that is the likely cause — and placing
ArUco markers, which the ArUco path picks up automatically, is the fix.

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
