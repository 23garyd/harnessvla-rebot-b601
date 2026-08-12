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

**Session 3 (2026-08-10) ended by GRIPPER FAILURE — 4 more episodes removed
by owner decision** (pre-deletion snapshot: `b601_train_full_20260810b`, 51
episodes). The end-position audit showed the failure began EARLIER than it
was noticed: the last episode of session 2 (then-46) already failed delivery
(block ended 78 px from the saucer), then 105 px and 147 px on the next two
— a worsening drop pattern — before one clean success and a final episode
that started in the goal state. Removed: then-46/47/48/50. Kept: the mid-
failure success (now episode 46) — it starts at a legitimate mat position,
completes the task, and any regrasp it contains is naturalistic recovery
data. The saucer was verified NOT to have moved (fixed at its mark, ±2 px,
throughout). **Collection is paused until the gripper is repaired; after
repair, record 2–3 verification episodes and replay them before resuming
scaled collection. A repaired-in-kind gripper is a registry note; a
REPLACED gripper model is an experiment-version event.**

**Session 4 (2026-08-11): reset-recorded-through-the-arm — 8 of 27 episodes
salvaged by frame-level trimming.** The operator pressed → and then reset via
the leader, but dropped keypresses (the failing keyboard's third incident)
and reset-window skips put the arm-driven un-place INSIDE recordings — the
worst contamination class, since "block in saucer → retrieve it" is
on-distribution at deployment and would undo the harness's verified
successes. Handling: per-episode cut points at the last block-arrival at the
saucer (+1.5 s); heads screened the same way (an un-place PREFIX is equally
poisonous — 8 of 16 candidates failed head screening, fully-occluded heads
failing closed); three trims discarded post-merge when their final frames
showed a fly-over cut (block beside the saucer or still gripped). Yield: 8
clean trimmed episodes merged back; 19 of session 4 deleted. Pre-surgery
snapshot: `b601_train_full_20260811` (74 episodes). Trim tooling notes: the
in-place delete mode of lerobot-edit-dataset corrupts its source (bug,
measured); LeRobotDataset.create requires robot_type and an explicit
.finalize() — omitting finalize truncates the episodes parquet.
**Corpus after surgery: 52 episodes, 32,240 frames, zero held-out leakage.**

**Session 5 (2026-08-11): the trim pipeline is now routine.** 20 recorded;
the correct rhythm held for seven mid-session episodes (ends 3–28 px from
the saucer) and reverted around it — a fatigue pattern, not a knowledge gap.
Handling per the session-4 protocol: 6 kept untouched, 3 dropped for
poisoned heads (fail closed), 11 tail-trimmed at last saucer arrival
(+2 s margin, raised after session 4's fly-over lesson), of which 1 had no
clean arrival and 4 were discarded post-merge on visual end-verification
(the "last arrival" was the un-place carry passing back over the saucer —
release detection would be needed to do better, not worth it). One end
verified via the wrist camera (occluded from above, block seated). Yield:
12 of 20. Snapshot: `b601_train_full_20260811b` (72 episodes).
**Corpus: 64 episodes, 38,094 frames, zero held-out leakage.** Standing
protocol: press → at delivery when possible; tails are trimmed as a
standard post-session step; NEVER touch the block in a recording's first
seconds — head contamination is the one unrepairable class.

**Session 6 (2026-08-12): boundary shift confirmed as an INPUT problem, not
an operator problem.** The operator deliberately waited 5 s after hearing
"Reset the environment" before touching the block — and the reset still
landed inside episodes. Episode boundaries land one phase late: each episode
records [demo -> return-home -> hand-reset], meaning the -> press at
return-home is not reaching the recorder when pressed ("recording does not
stop after I hit the right arrow" — operator report, corroborated by the
ep81 filmstrip). Session is X11 (Wayland capture theory excluded); spd-say
messages queue (~2 s lag measured) but cannot explain a 5 s gap. Keypress
event path (keyboard hardware / pynput listener) under live test. Salvage
per the standing trim protocol, upgraded to cut at ARM-IDLE-after-placement
(keeps the operator's return-home, the ideal terminal shape): 20 recorded ->
5 kept as-is + 8 trimmed, of which 3 discarded as fly-over cuts and 1
fail-closed (wrist view off-table at cut). Yield 9 of 20. All ends verified
(one via wrist camera). Snapshot: `b601_train_full_20260812` (84 episodes).
**Corpus: 73 episodes, 42,785 frames.** Also verified this session: saucer
within 14 px of witness ALL session, gripper delivering, starts followed the
focus zones (D and E filled), heads clean — the demonstrations themselves
are good; only the boundary placement is broken.

**Documented anomaly, episodes 41–45 (new numbering; kept):** same
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
