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

## Training corpus: `local/b601_train` — design frozen 2026-08-10, BEFORE episode 1

- **Task**: "pick up the red block and place it in the bowl" — identical
  string to the pilot. ONE red block; colour variation deliberately rejected
  (the thesis is planner-vs-primitive, not perception generality — extra
  colours split the episode budget across appearances and confound the
  Day-18 comparison). Saucer FIXED at its witness-marked position (a moving
  place-target makes a failed place ambiguous evidence: bad grasp or bad
  place?).
- **Placement policy**: free scatter — the operator starts the block
  anywhere comfortably reachable, no grid schedule. Two guards replace the
  grid: the reserved zone below, and an automated per-session coverage audit
  (frame 0 of every episode; red-blob centroid on the green mat; build the
  placement map; flag clustering and under-covered areas for the next
  session).
- **HELD-OUT ZONE (frozen)**: image-space rectangle **(150, 230)–(270, 350)**
  in the agentview frame under calibration `f31fe…`-current (the drift gate
  holds the camera fixed, so image coordinates are durable). The block never
  STARTS there during collection; Day-14 evaluation places it there. Diagram:
  `b601/registry/b601_train_zones.jpg`. Leakage audit = frame-0
  centroid inside the rectangle.
- **Target**: **150 accepted episodes** (plan budget 120–200), collected over
  3–5 sessions. Exclusions are quarantined with a reason, never deleted.
- **Session ritual**: HANDOVER.md morning ritual, saucer on its witness mark,
  identical room lighting to the exposure measurement (both cameras run
  fixed exposure), consistent demonstration strategy (same approach
  direction, same top-down grasp).

### Quarantined episodes (excluded from training via `dataset.episodes`, never deleted)

**PHYSICALLY REMOVED 2026-08-10 by owner decision** (supersedes the
quarantine-in-place): episodes 37 (keyboard failure, full 60 s timeout tail)
and 42–45 (reset-inside-recording, heavy form — 5–8 s contaminated prefixes
containing reverse-task motion: block starting in the saucer, the arm
returning from the previous place, a hand restaging the block). Removal via
`lerobot-edit-dataset delete_episodes` into a fresh copy (the tool's
in-place mode has a root-semantics bug that corrupts the source — measured;
use `--new_repo_id` mode only). The never-delete audit trail is preserved by
a frozen pre-deletion snapshot: **`/mnt/nvme3/b601/b601_train_full_20260810`**
(52 episodes). The working dataset renumbered: old 38–41 → 37–40, old
46–51 → **41–46**.

**Documented anomaly, episodes 41–46 (new numbering; kept):** same
reset-inside-recording pattern in light form — ~2–3 s prefixes (block in
saucer, hand repositioning it, arm parked and idle). Kept because the bulk
of each episode is a valid demonstration and the prefix states (hand in
frame, block in goal) cannot occur at deployment; their true start positions
were recovered from post-reset frames for the coverage audit. If the Day-14
policy underperforms, these six are the first candidates to drop.
**Corrected session rhythm from session 3 on:** during the reset window,
FIRST park the arm clear, THEN restage the block, THEN press → — never
reset after the next episode has begun.

## Frozen split
Held-out evaluation placements are chosen **before** training and never
appear in the training set. Leakage is checked automatically at the Day-10
gate, not asserted by hand. For `b601_train` the held-out set is the
reserved zone above, frozen before the first episode.

## Integrity
- `datasets/` is gitignored; the dataset **hash is committed here**
- Backup from the first pilot episode
- Excluded episodes are quarantined with a reason, never deleted

## Backup target (chosen 2026-08-06; mount path changed 2026-08-10)

    /mnt/nvme3/b601        (UUID=b0b0d284-79d6-4291-93ad-f27ef2f77022)

Verified a separate physical device from the repo disk (OWC Aura P12 Pro
4 TB, 3.3 TB free, ext4) against `/dev/nvme4n1p2`. Capacity is not a
constraint. Since 2026-08-10 an fstab entry (`nofail`) mounts it at boot,
replacing the transient udisks mount at `/media/demo/<uuid>` whose absence
after every reboot kept failing the record script's backup gate.

**It is not off-machine, and the risk log says off-machine.** A second internal
NVMe covers disk failure, which is the most likely loss, but not machine loss,
theft, fire, or an `rm` that takes both mounts. Recorded as a deliberate
accepted gap rather than a satisfied requirement. A truly off-machine copy of
the accepted episodes remains worth doing before Day 10.

**Writable since 2026-08-07** (`demo:demo` on the `b601` directory), and the
first pilot episode's backup landed there 2026-08-08. Mount by UUID only:
four identical OWC drives are installed and the kernel demonstrably shuffles
their `/dev/nvmeX` numbering across reboots — which is also why the fstab
entry pins the UUID, not a device name.
