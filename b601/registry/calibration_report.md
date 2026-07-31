# Calibration report — B601 cameras

**Status: not yet calibrated.** Produced on plan Day 3.

## Required content
- Camera manifest: serial, model, mount, resolution, fps, fixed exposure
- Method: camera-to-robot transform, or the documented image-space staging
  fallback (the plan permits either — record which, and why)
- **Measured** reprojection / position error at known table points, as a
  number with units. The plan is explicit that "good enough" must be measured,
  not an impression
- Restart procedure and the evidence that landmarks are stable across a restart
- Mount photographs
- SHA256 of the calibration artifact, matching `CALIBRATION_SHA256` in pins.env

## Why this is gating
A systematic perception bias is indistinguishable from policy error at
evaluation time. In the simulation track a stale reference coordinate produced
release errors of +0.078–0.082 m and inverted a cell that was otherwise the
strongest in the matrix. The physical analogue is a nudged mount, and it is
silent unless calibration is pinned and checked.
