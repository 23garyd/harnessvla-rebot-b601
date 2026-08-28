# Experiment v2 — rerun design

**Status: SET UP 2026-08-27. Blocked on the rigid camera mount (owner task),
then the reference re-record.**

## Why v2 (each reason measured in v1, see experiment_registry + risk_log)

1. **v1 could not falsify the harness thesis.** The primitive's held-out
   per-attempt success was exactly zero, and retries can only multiply what
   exists. v2's test design gives the harness something to multiply.
2. **Tail contamination taught a spurious stop cue.** Occlusion probes proved
   the frozen v1 policy reads "person near mat" as end-of-episode and goes
   home — because v1 episode tails contain exactly that correlation.
3. **The camera mount creeps between sessions.** Measured from footage:
   <1 px within episodes (no shake), but up to ~10 px between same-evening
   sessions — past the 3 px gate bound, invisible to a start-only gate,
   ~1 cm of staging bias.
4. **In-distribution reliability was only 60%** (3/5 baseline). More data +
   the fixes above should raise the primitive's floor everywhere.

## The corpus (200 episodes, dataset `local/b601_train_v2`)

Placement design — see `~/Desktop/v2_placement_map.jpg`:

**Coordinates below are in the NEW (rigid-mount, 2026-08-27) camera frame.**
The mount changed the view entirely (~450 px median tag displacement); the
physical held-out region carries over via the four-tag homography
(independently confirmed: the block left physically inside the zone lands
inside the transformed box), the saucer was re-measured directly
(homography carries ~20 px lens-distortion error at this closer view), and
the interpolation points — arbitrary test choices, not physical fixtures —
were redefined cleanly in the new frame.

| Region | Rule during recording | Role at evaluation |
|---|---|---|
| **Extrapolation zone** (red): agentview (365,148)–(475,255) [physical region carried from v1; ±20 px homography tolerance — exact eval target pixels re-measured at eval setup] | NEVER place the block here | H1–H5 targets — the hard bound; expect low/zero primitive competence (v1's held-out result) |
| **Interpolation disks** (orange): 25 px radius at I1 (250,250), I2 (320,300), I3 (300,170), I4 (170,280), I5 (420,310) | Do not place INSIDE a disk; placing near/around them is expected and good | I1–I5 targets — novel points inside demonstrated territory. This is where the harness thesis is falsifiable: a decent primitive has partial competence here, and retry/verify should multiply it |
| Everywhere else on the mat | Place freely, spread evenly, vary orientation | Controls (C1–C5, chosen at eval setup) |

Saucer witness in the new frame: **(192,181)**, visual radius ~39 px
(measured from the blue-disk blob). Note from the mount check: under
DAYLIGHT the pinned exposure washes the red block to near-white
(undetectable by the same HSV gate the audits use) — the evening-lighting
rule is not just for the policy, it is what keeps perception alive.

Session plan: 5 sessions × 40 episodes (the v1 pace). After each session the
existing audit runs (alignment guard first, then behavioral checks) plus a
coverage map so thin areas get filled next session.

**Tail-hygiene protocol (in `record_session_v2.sh`, printed every session):**
end every episode by RETURNING THE FOLLOWER TO PARK before pressing the right
arrow; never enter the camera's view while frames are being saved; consistent
seated operator position. This removes the person-and-motion end-of-episode
correlations v1's policy latched onto.

## New instrumentation (built 2026-08-27)

- **Session-END drift re-check** in `record_session_v2.sh`: catches
  mid-session creep retroactively; a failing exit check quarantines the
  session's episodes instead of blending two geometries into the corpus.
- **Per-trial drift gate** in the harness runner
  (`b601/planner/trial_gate.py`, 4 tests): between trials, agentview frames
  from the robot's own camera run through the phantom-rejecting aggregation
  and the pinned reference; a drifted mount REFUSES the trial.
- Everything else carries over unchanged: gate stack, rate limiter,
  divergence guard, verifier, harness, probe tooling, standing rules
  (operator out of frame whenever the policy drives; evening lighting;
  anchors validated against pixels).

## Order of work

1. **Owner: install the rigid mount.** Then, in one sitting:
   `python -m b601.cameras.reference --record` (arm parked, all four tags
   healthy) and `bash b601/setup/pin_check.sh --record` — the mount change
   deliberately redefines "not drifted" (registry event, this row is it).
   Camera moved => the v1 staging table and v1 policy are NOT transferable;
   v2 trains and stages from v2 data only.
2. Record: `bash b601/setup/record_session_v2.sh 40` per session (append
   later sessions with `--resume=true`); replay-verify a sample; audit after
   each session.
3. Train ACT v2 (same recipe as v1: 100k steps, image-space); freeze.
4. Baseline eval (Day-14 protocol, 15 trials: 5 I, 5 H, 5 C — interleaved,
   operator-initiated, out of frame, per-trial drift gate).
5. Rebuild staging table + verifier calibration from the v2 corpus
   (builders exist; anchors re-validated against pixels per the standing
   guard).
6. Harness comparison, same 15-trial protocol. Gates: on I-targets the
   original bar (≥85% or +15pp over baseline); H-targets reported as the
   extrapolation bound; success attribution (policy vs harness-completed)
   as fixed in the recovery-grasp registry row.

## What is deliberately NOT carried over

- v1 policy checkpoint, v1 staging table, v1 verifier thresholds (all are
  functions of the old camera geometry and corpus). The code and tests all
  carry; only the data artifacts regenerate.
