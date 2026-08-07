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
- Backup from the first pilot episode
- Excluded episodes are quarantined with a reason, never deleted

## Backup target (chosen 2026-08-06)

    /media/demo/b0b0d284-79d6-4291-93ad-f27ef2f77022/b601

Verified a separate physical device from the repo disk: `/dev/nvme3n1p1`
(OWC Aura P12 Pro 4 TB, 3.3 TB free, ext4) against `/dev/nvme4n1p2`. Capacity
is not a constraint.

**It is not off-machine, and the risk log says off-machine.** A second internal
NVMe covers disk failure, which is the most likely loss, but not machine loss,
theft, fire, or an `rm` that takes both mounts. Recorded as a deliberate
accepted gap rather than a satisfied requirement. A truly off-machine copy of
the accepted episodes remains worth doing before Day 10.

**Not yet writable.** The mount is `root:root 755`. Before the first pilot
episode:

    sudo mkdir -p /media/demo/b0b0d284-79d6-4291-93ad-f27ef2f77022/b601
    sudo chown demo:demo /media/demo/b0b0d284-79d6-4291-93ad-f27ef2f77022/b601
