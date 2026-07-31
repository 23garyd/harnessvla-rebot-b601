# Dataset card — B601 demonstration set

**Status: not yet collected.** Populated during Week 2 (plan Days 6–10).

The dataset is the irreplaceable asset in this project. A rollout in the
simulation track could always be re-run; a teleoperation session cannot.
Everything here exists so a future reader can tell exactly what was recorded,
under what physical configuration, and what was excluded.

## To record per collection session
- Date, operator, session duration
- Experiment version (from `experiment_registry.md`) and `pin_check` output
- Camera manifest: serials, resolution, fps, exposure, mount photos
- Calibration file hash in force
- Objects, workspace regions, and the variation matrix cell each episode fills
- Episode count: attempted / accepted / excluded, **with the exclusion reason**

## Frozen split
Held-out evaluation placements are chosen **before** training and never
appear in the training set. Leakage is checked automatically at the Day-10
gate, not asserted by hand.

## Integrity
- `datasets/` is gitignored; the dataset **hash is committed here**
- Off-machine backup from the first pilot episode
- Excluded episodes are quarantined with a reason, never deleted
