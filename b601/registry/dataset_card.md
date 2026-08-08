# Dataset card — B601 demonstration set

**Status: pilot in progress.** First episode recorded 2026-08-08; the full
set is populated during Week 2 (plan Days 6–10).

## Pilot: `local/b601_pilot` (Day-5 gate evidence)

**12 episodes, 7031 frames @ 30 fps** as of 2026-08-08 evening, both camera
streams throughout, backed up file-for-file to the NVMe target below.

| Episodes | Date | Task | Replay | Caveat |
|---|---|---|---|---|
| 0 | 2026-08-08 | pick up the red block and place it in the bowl | **correct** (operator judgement) | **Wrist stream untrainable** — recorded under the 8000 µs / gain 16 exposure placeholder, mean brightness 5–16/255. Valid as replay/gate evidence (replay uses no images); quarantined for training. Also recorded under the ORIGINAL workspace layout (black staging board present), unlike every later episode |
| 1–11 | 2026-08-08 | pick up the red block and place it in the bowl | **11 of 11 correct** (operator watched each replay, reported 2026-08-08) | Recorded under the rebuilt workspace (four corner tags, board removed), measured wrist exposure (8000 µs / gain 248), calibration `f31fe…`→current. These are the first training-grade episodes |

**DAY-5 GATE: MET.** The gate needs ≥9 of 10 replaying correctly, counted per
episode by a human watching the arm; the tally is 12 of 12 (episode 0 under
the old layout plus 11 of 11 under the rebuilt workspace). The recording
stack is approved for scaled collection, subject to the pre-collection
decisions in the risk log (staging method + scatter region, off-machine
backup). One rsync note: an earlier backup pass captured
LeRobot's transient `images/` frame scratch mid-encode; it was verified
redundant (all canonical parquet/mp4/meta present both sides) and removed
from the backup 2026-08-08.

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

**Writable since 2026-08-07** (`demo:demo` on the `b601` directory), and the
first pilot episode's backup landed there 2026-08-08. Two operational notes:
the udisks mount does NOT survive a reboot — the record script's backup gate
caught exactly that on the first post-reboot attempt; the morning ritual in
`HANDOVER.md` now includes `udisksctl mount -b /dev/disk/by-uuid/b0b0d284-…`
— and mount by UUID only: four identical OWC drives are installed and the
kernel demonstrably shuffles their `/dev/nvmeX` numbering across reboots.
