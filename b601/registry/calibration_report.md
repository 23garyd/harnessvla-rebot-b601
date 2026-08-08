# Calibration report — B601 cameras

**Status: ArUco drift reference CAPTURED and verifying. No metric calibration.**

**RE-RECORDED 2026-08-08** after the drift gate caught a real event: the top
camera was nudged during 2026-08-07's USB-cable work (median 6.47 px, all
markers displaced right 3–7 px with inconsistent directions — a small
rotation), and marker id1's original spot turned out to sit under the arm's
park pose, so the arm occluded it at every session start. id1 was relocated
(down-right, out of the dark top-left corner where it would not decode) and
the reference re-recorded with the arm parked in its session-start pose.
Legitimate re-record: zero episodes exist, so no comparability was broken.

Current reference, `DICT_4X4_50`, stable 15/15 with ≤0.2 px jitter:

| id | centre (px) |
|---|---|
| 1 | (117.3, 207.5) |
| 6 | (91.3, 327.8) |
| 2 | (580.0, 363.4) |

**Three landmarks, not four — deliberate.** The fourth tag (id11, top-right)
prints too faint: its dark cells read as pale grey and detection flickers
8–10/15 frames even after re-inking. The recorder's stability guard excluded
it, correctly: a marginal marker baked into the reference turns every future
session gate into a coin flip on lighting. The top-right corner is therefore
unguarded until the tag is REPLACED with a dark print (proven-good ids are
taken; pick 3, 4 or 5 — avoid mat-phantom ids 10, 17, 22, 33, 34, 36, 37, 38,
41, 44, 45), which is a cheap re-record whenever convenient before scaled
collection.

Measured immediately after recording: **median displacement 0.03 px, max
0.2 px** against a 3.00 px tolerance.

`CALIBRATION_SHA256=cbe222c033a9…` recorded in `pins.env` and verifying
(supersedes `a80f3c57b141`, which superseded the ORB reference
`0c26d532b47c`; `pin_check` correctly FAILED on each hash change before the
re-record).

### The 2026-08-07 reference (superseded)

Four markers, recorded before the camera nudge: id1 (149.7, 173.9),
id11 (538.6, 143.9), id6 (103.7, 319.2), id2 (593.0, 362.6), spanning
489 x 219 px. Verified at 0.09 px median immediately after recording. Its
capture story below still holds — the marker-size and print-quality findings
transfer unchanged.

**Getting here took four attempts, and the failures are the useful part:**

| Attempt | Result | Cause |
|---|---|---|
| markers ~12 px | 1 of 4 decoded, 5/12 frames | too small — 4x4 needs ~40 px, giving each bit cell ~2 px at 12 px |
| larger, 32–38 px | 3 of 4, all 15/15 | the fourth was washed out: darkest pixel 120 vs 57–98, no continuous black border to find |
| fourth moved inward | still 0/15 | not size, focus or contrast — sharpness 3179 and contrast 192 sat mid-range among the working three, and NO dictionary decoded it. The printed pattern itself was not a valid marker |
| fourth swapped | **4 of 4**, 39–41 px | — |

Do not chase a missing marker with looser `DetectorParameters`: tried, and the
permissive settings invented `id37` twice among 7307 rejected candidates.

## The method, and why

The plan permits either a camera-to-robot transform or a documented
image-space fallback, and requires recording which and why. **Chosen for now:
a landmark drift reference, which is neither, and deliberately less.**

`b601/cameras/reference.py` records landmark positions once and compares them
at the start of every session. It yields no intrinsics and no camera-to-robot
transform. It detects only that a mount MOVED.

**Both methods are implemented and the right one is chosen automatically.**
`aruco_landmarks` is used when stable markers are visible, which they now are.
`orb_homography` is the fallback and was in force 2026-08-06 before markers
existed: it matches ORB features against a stored reference image (this
workspace offers 1512 in the periphery, 609 strong), RANSAC-estimates a
homography, and takes the displacement of a fixed 9-point probe grid under it
as the drift.

ArUco is preferred here for a specific reason: the ORB periphery in this scene
includes a **chair, a monitor and garage floor**, all of which can move. RANSAC
absorbs a few outliers, not a rearrangement. Markers fixed to the workspace are
immune to that.

**PHANTOM REJECTION IS MANDATORY HERE, and measured.** The green cutting mat's
grid makes ArUco hallucinate: across four separate captures it produced ids
10, 17, 22, 34, 37, 38, 45 and 225 — each typically seen once at 6–18 px — and
on one occasion id 190 in 10 of 12 frames with 108 px of jitter. Recording any
of them would bake in a landmark that vanishes on the next run and fails the
check forever after. `--record` therefore takes a 12-frame burst and keeps only
landmarks present in EVERY frame within 2 px (`stable_landmarks`). It rejected
`id45` on the recording run that produced the table above.

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
